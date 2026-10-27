"""Outils que l'agent peut appeler : web, vision, fichiers, commandes.

Règles de sécurité :
- Les fichiers sont limités au dossier de travail (workspace).
- Les pages web locales / réseau privé sont refusées (protection SSRF).
- Écraser un fichier ou lancer une commande demande TOUJOURS ta confirmation.
"""

from __future__ import annotations

import ipaddress
import os
import shlex
import socket
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from .config import Config
from .ollama_client import OllamaClient

MAX_OUTPUT = 8000          # caractères renvoyés au modèle par outil
MAX_DOWNLOAD = 1_000_000   # octets lus par page web
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class ToolError(Exception):
    """Erreur renvoyée au modèle sous forme de texte (il peut se corriger)."""


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n[... tronqué, {len(text) - MAX_OUTPUT} caractères de plus]"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip() + " ")


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def check_public_url(url: str) -> None:
    """Refuse tout sauf http(s) vers une adresse publique."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ToolError("URL invalide : seuls http:// et https:// sont acceptés.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as e:
        raise ToolError(f"Nom de domaine introuvable : {parsed.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ToolError("Adresse privée ou locale refusée pour des raisons de sécurité.")


TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Cherche sur le web. Utilise-le pour vérifier un fait ou trouver de l'information récente.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Les mots à chercher"},
            "max_results": {"type": "integer", "description": "Nombre de résultats (1 à 10)"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Télécharge une page web et retourne son texte.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "describe_image",
        "description": "Regarde une image du dossier de travail et la décrit (ou répond à une question sur elle).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Chemin de l'image dans le dossier de travail"},
            "question": {"type": "string", "description": "Ce qu'on veut savoir (par défaut : décris l'image)"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "Liste les fichiers d'un dossier du projet.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Dossier (par défaut : la racine du projet)"}}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Lit un fichier texte du projet.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Crée ou remplace un fichier texte du projet. Crée les dossiers au besoin.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "draw_diagram",
        "description": ("Dessine un schéma (organigramme, plan de projet, étapes, architecture) à partir "
                        "de code Mermaid. Crée une page .html à ouvrir dans le navigateur (et un .png si "
                        "possible) dans le dossier schemas/. Exemple de code : "
                        "'flowchart TD\\n  A[Idée] --> B[Code]\\n  B --> C[Test]'."),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Le diagramme en Mermaid (commence par flowchart TD, sequenceDiagram, mindmap…)"},
            "name": {"type": "string", "description": "Nom court du fichier, sans extension (ex : plan-projet)"},
            "title": {"type": "string", "description": "Titre affiché au-dessus du schéma"},
        }, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "machine_info",
        "description": "Dit quelle est la puissance de l'ordinateur (niveau fort, moyen ou léger) pour savoir quels moteurs sont utilisables.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Lance une commande dans le dossier du projet (ex: python main.py, pytest). Demande la confirmation de l'utilisateur.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]}}},
]


def resolve_workspace_path(config: Config, path: str) -> Path:
    """Résout un chemin et refuse tout ce qui sort du dossier de travail.

    Fonction indépendante de Toolbox pour que d'autres interfaces (le menu
    LexOS Pro, par exemple) puissent réutiliser la même règle de sécurité
    sans dupliquer la logique."""
    root = config.workspace.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ToolError("Chemin refusé : en dehors du dossier de travail.")
    return target


class Toolbox:
    def __init__(self, config: Config, client: OllamaClient,
                 confirm: Callable[[str], bool] | None = None):
        self.config = config
        self.client = client
        self.confirm = confirm or self._ask_terminal

    # ------------------------------------------------------------ utilitaires
    @staticmethod
    def _ask_terminal(question: str) -> bool:
        return input(f"\n⚠️  {question} [o/N] ").strip().lower() in {"o", "oui", "y", "yes"}

    def _resolve(self, path: str) -> Path:
        return resolve_workspace_path(self.config, path)

    def call(self, name: str, arguments: dict) -> str:
        """Exécute un outil. Toute erreur devient un texte que le modèle peut lire."""
        func = getattr(self, f"tool_{name}", None)
        if func is None:
            return f"Erreur : outil inconnu « {name} »."
        try:
            return _truncate(str(func(**arguments)))
        except ToolError as e:
            return self._fail(name, arguments, f"Erreur : {e}")
        except TypeError as e:
            return self._fail(name, arguments, f"Erreur : arguments invalides pour {name} ({e}).")
        except Exception as e:  # on ne plante jamais la boucle de l'agent
            return self._fail(name, arguments, f"Erreur inattendue ({type(e).__name__}) : {e}")

    def _fail(self, name: str, arguments: dict, message: str) -> str:
        """Note l'erreur dans la mémoire partagée pour éviter de la refaire —
        sauf un refus volontaire de l'utilisateur, qui n'est pas une erreur."""
        if "a refusé" not in message:
            from .memory import remember_error
            context = f"{name}(" + ", ".join(f"{k}={v!r}" for k, v in arguments.items())[:120] + ")"
            remember_error(self.config, context, message[:200])
        return message

    # ------------------------------------------------------------------- web
    def tool_web_search(self, query: str, max_results: int = 5) -> str:
        try:
            from ddgs import DDGS
        except ImportError as e:
            raise ToolError("Le paquet « ddgs » n'est pas installé (pip install ddgs).") from e
        max_results = max(1, min(int(max_results), 10))
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return "Aucun résultat."
        return "\n\n".join(
            f"{r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}" for r in results
        )

    def tool_fetch_page(self, url: str) -> str:
        for _ in range(4):  # suit au plus 3 redirections, en revérifiant chaque adresse
            check_public_url(url)
            r = requests.get(url, timeout=15, stream=True, allow_redirects=False,
                             headers={"User-Agent": "ti-lex-agent/0.1"})
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            raw = r.raw.read(MAX_DOWNLOAD, decode_content=True)
            text = raw.decode(r.encoding or "utf-8", errors="replace")
            if "html" in r.headers.get("content-type", "").lower():
                text = html_to_text(text)
            return text
        raise ToolError("Trop de redirections.")

    # ---------------------------------------------------------------- vision
    def tool_describe_image(self, path: str, question: str = "Décris cette image en détail.") -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"Image introuvable : {path}")
        if target.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ToolError("Format non supporté (png, jpg, jpeg, webp, gif, bmp).")
        return self.client.describe_image(target, question)

    # --------------------------------------------------------------- fichiers
    def tool_list_files(self, path: str = ".") -> str:
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolError(f"Pas un dossier : {path}")
        root = self.config.workspace.resolve()
        entries = sorted(target.iterdir())[:200]
        if not entries:
            return "(dossier vide)"
        return "\n".join(
            str(e.relative_to(root)) + ("/" if e.is_dir() else "") for e in entries
        )

    def tool_read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"Fichier introuvable : {path}")
        return target.read_text(encoding="utf-8", errors="replace")

    def tool_write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        if target.exists() and not self.confirm(f"Écraser le fichier existant « {path} » ?"):
            raise ToolError("L'utilisateur a refusé d'écraser ce fichier.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Écrit : {path} ({len(content)} caractères)"

    # --------------------------------------------------------------- moteurs
    def tool_draw_diagram(self, code: str, name: str = "schema", title: str | None = None) -> str:
        from .schema import SchemaError, dessiner, nom_sur

        base = self._resolve(f"schemas/{nom_sur(name)}")
        if base.with_suffix(".html").exists() and not self.confirm(
                f"Remplacer le schéma existant « schemas/{base.name} » ?"):
            raise ToolError("L'utilisateur a refusé de remplacer ce schéma.")
        try:
            crees = dessiner(code, base, self.config.moteurs, title)
        except SchemaError as e:
            raise ToolError(str(e)) from e
        root = self.config.workspace.resolve()
        liste = ", ".join(str(p.relative_to(root)) for p in crees)
        conseil = "" if any(p.suffix == ".png" for p in crees) else (
            " (Pas d'image .png : mermaid-cli n'est pas installé. Ouvre la page .html dans le navigateur.)")
        return f"Schéma créé : {liste}.{conseil}"

    def tool_machine_info(self) -> str:
        from .hardware import detecter

        m = detecter()
        moteurs = {
            "fort": "schémas ; images rapides ; vraie génération vidéo courte",
            "moyen": "schémas ; images (plus lentes) ; vidéo montée à partir d'images",
            "leger": "schémas ; petites images sur le processeur (lent) ; vidéo montée à partir d'images",
        }[m.niveau]
        return f"{m.resume()}\nMoteurs adaptés à ce niveau : {moteurs}."

    # -------------------------------------------------------------- commandes
    def tool_run_command(self, command: str) -> str:
        if not self.confirm(f"Lancer cette commande ?\n    {command}"):
            raise ToolError("L'utilisateur a refusé cette commande.")
        try:
            # Sous Windows, les chemins utilisent \ : shlex.split(posix=True) les
            # casserait en les traitant comme des caractères d'échappement.
            args = shlex.split(command, posix=(os.name != "nt"))
        except ValueError as e:
            raise ToolError(f"Commande mal formée : {e}") from e
        if not args:
            raise ToolError("Commande vide.")
        try:
            done = subprocess.run(args, cwd=self.config.workspace, capture_output=True,
                                  text=True, timeout=60)
        except FileNotFoundError as e:
            raise ToolError(f"Programme introuvable : {args[0]}") from e
        except subprocess.TimeoutExpired as e:
            raise ToolError("La commande a dépassé 60 secondes.") from e
        return f"code de sortie : {done.returncode}\n--- sortie ---\n{done.stdout}\n--- erreurs ---\n{done.stderr}"
