"""Outils que l'agent peut appeler : web, vision, fichiers, commandes.

Règles de sécurité :
- Les fichiers sont limités au dossier de travail (workspace).
- Les pages web locales / réseau privé sont refusées (protection SSRF).
- Écraser un fichier ou lancer une commande demande TOUJOURS ta confirmation.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import shutil
import socket
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from .config import Config
from .ollama_client import OllamaClient

# Commandes qui peuvent détruire le système : même en mode /auto, on redemande toujours.
DANGEROUS = re.compile(
    r"(\brm\s+(-\w*\s+)*-\w*[rf]\w*\s+(/|~|\$HOME|\*)(\s|$)"      # rm -rf / ~ * $HOME
    r"|\bmkfs\b|\bdd\b[^|;&]*\bof=/dev/|>\s*/dev/(sd|nvme|mmcblk)"     # formatage / écrasement disque
    r"|:\(\)\s*\{|\bchmod\s+-R\s+\S+\s+/(\s|$)|\bchown\s+-R\s+\S+\s+/(\s|$)"
    r"|\b(shutdown|reboot|poweroff|halt)\b|\bsudo\b|\bsu\s+-?\s*$"
    r"|\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z)?sh\b)")
# Programmes courants qu'on regarde d'abord pour dire à l'IA ce qui est installé.
COMMON_TOOLS = ["git", "python3", "pip", "node", "npm", "docker", "curl", "wget", "ssh", "scp",
                "rsync", "tar", "zip", "unzip", "grep", "sed", "awk", "jq", "find", "tree",
                "make", "gcc", "go", "cargo", "rustc", "java", "nmap", "ffmpeg", "sqlite3",
                "htop", "tmux", "vim", "nano", "ip", "ping", "df", "du", "ps", "systemctl",
                "apt", "ollama", "gh"]
SHELL_TIMEOUT = 120

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
        # Mode « auto » de TerminalCodex : lance les commandes sans demander à chaque fois
        # (sauf les commandes dangereuses : DANGEROUS). Désactivé par défaut.
        self.auto_approve = False

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


# --------------------------------------------------------------------- TerminalCodex
def _installed(name: str) -> bool:
    return shutil.which(name) is not None


def _tool_list_installed(self, search: str = "") -> str:
    """Programmes présents sur ce PC. `search` cherche un nom précis dans tout le PATH."""
    if search.strip():
        name = search.strip()
        path = shutil.which(name)
        return f"{name} : {path}" if path else f"{name} : introuvable sur ce PC."
    found = [t for t in COMMON_TOOLS if _installed(t)]
    return ("Installés : " + ", ".join(found) + "\n(Tout autre programme du PATH peut aussi être "
            "lancé ; list_installed_tools(search=\"nom\") vérifie un programme précis.)")


def _tool_list_library(self) -> str:
    """Les outils créés par l'utilisateur (bibliothèque « Outils créés »)."""
    from . import outils
    try:
        tools = outils.load(self.config)
    except outils.OutilError as e:
        raise ToolError(str(e)) from e
    if not tools:
        return "La bibliothèque est vide."
    return "\n".join(f"{t['nom']} — {t['commande']}" + (f"  ({t['description']})" if t.get("description") else "")
                     for t in tools)


def sudo_noninteractive(command: str) -> str:
    """« sudo » ne doit jamais attendre un mot de passe (personne ne peut le taper ici) :
    on ajoute -n. Le mot de passe se donne une seule fois, avec /sudo, dans le vrai terminal."""
    return re.sub(r"\bsudo\b(?!\s+-n\b)", "sudo -n", command)


SUDO_HELP = ("sudo a besoin du mot de passe. Dis à l'utilisateur de taper /sudo une fois "
             "(il l'écrit dans son terminal, il n'est jamais enregistré), puis réessaie.")


def _run_shell_confirmed(self, command: str, label: str) -> str:
    command = command.strip()
    if not command:
        raise ToolError("Commande vide.")
    risky = bool(DANGEROUS.search(command))
    if risky:
        if not self.confirm(f"⚠ COMMANDE DANGEREUSE — la lancer quand même ?\n    {command}"):
            raise ToolError("L'utilisateur a refusé cette commande.")
    elif not self.auto_approve and not self.confirm(f"{label}\n    {command}"):
        raise ToolError("L'utilisateur a refusé cette commande.")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", PAGER="cat", DEBIAN_FRONTEND="noninteractive")
    command = sudo_noninteractive(command)
    try:
        done = subprocess.run(command, shell=True, cwd=self.config.workspace, capture_output=True,
                              text=True, timeout=SHELL_TIMEOUT, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"La commande a dépassé {SHELL_TIMEOUT} secondes (elle a été arrêtée). "
                        "Lance-la en arrière-plan ou découpe-la.") from e
    note = ""
    if done.returncode != 0 and "sudo" in command and re.search(
            r"password is required|mot de passe est (requis|nécessaire)|a terminal is required",
            done.stderr):
        note = f"\n--- note ---\n{SUDO_HELP}"
    return (f"code de sortie : {done.returncode}\n--- sortie ---\n{done.stdout}\n"
            f"--- erreurs ---\n{done.stderr}{note}")


def _tool_run_shell(self, command: str) -> str:
    """Lance une commande shell (pipes, &&, redirections permis) dans le dossier de travail."""
    return _run_shell_confirmed(self, command, "Lancer cette commande ?")


def _tool_run_library_tool(self, name: str) -> str:
    """Lance un outil de la bibliothèque « Outils créés » par son nom."""
    from . import outils
    tool = outils.find(self.config, name)
    if tool is None:
        raise ToolError(f"Aucun outil nommé « {name} » dans la bibliothèque (list_library_tools).")
    return _run_shell_confirmed(self, tool["commande"], f"Lancer l'outil « {tool['nom']} » ?")


Toolbox.tool_list_installed_tools = _tool_list_installed
Toolbox.tool_list_library_tools = _tool_list_library
Toolbox.tool_run_shell = _tool_run_shell
Toolbox.tool_run_library_tool = _tool_run_library_tool

_TERMINAL_NEW = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": ("Lance une commande shell sur l'ordinateur de l'utilisateur, dans son dossier de "
                        "travail (pipes, &&, redirections permis). L'utilisateur confirme chaque commande. "
                        "Une seule commande à la fois ; lis la sortie avant la suivante."),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "La commande complète"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "list_installed_tools",
        "description": "Dit quels programmes sont installés sur ce PC (ou si un programme précis l'est).",
        "parameters": {"type": "object", "properties": {
            "search": {"type": "string", "description": "Nom d'un programme précis (facultatif)"}}}}},
    {"type": "function", "function": {
        "name": "list_library_tools",
        "description": "Liste les outils créés par l'utilisateur (sa bibliothèque « Outils créés »).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_library_tool",
        "description": "Lance un outil de la bibliothèque de l'utilisateur par son nom.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nom de l'outil"}}, "required": ["name"]}}},
]
_TERMINAL_KEEP = {"list_files", "read_file", "write_file", "web_search", "fetch_page"}
TERMINAL_TOOL_SCHEMAS: list[dict] = (
    _TERMINAL_NEW + [t for t in TOOL_SCHEMAS if t["function"]["name"] in _TERMINAL_KEEP])


# ------------------------------------------------------------------ Programme IA outils
INTERPRETERS = {".sh": "bash", ".bash": "bash", ".py": "python3"}


def _tool_save_tool(self, name: str, script: str, description: str = "") -> str:
    """Ajoute un script du dossier de travail à la bibliothèque « Outils créés »."""
    from . import outils
    target = self._resolve(script)
    if not target.is_file():
        raise ToolError(f"Script introuvable : {script} (écris-le d'abord avec write_file).")
    target.chmod(target.stat().st_mode | 0o755)
    runner = INTERPRETERS.get(target.suffix.lower())
    command = f"{runner} {shlex.quote(str(target))}" if runner else shlex.quote(str(target))
    try:
        message = outils.add(self.config, name, command, description)
    except outils.OutilError as e:
        raise ToolError(str(e)) from e
    return (f"{message} Commande : {command}\n"
            f"L'utilisateur le lance avec /outil {name.strip()} ou F2.")


Toolbox.tool_save_tool = _tool_save_tool

PROGRAMMEUR_TOOL_SCHEMAS: list[dict] = TERMINAL_TOOL_SCHEMAS + [
    {"type": "function", "function": {
        "name": "save_tool",
        "description": ("Ajoute un script terminé et TESTÉ à la bibliothèque « Outils créés » de "
                        "l'utilisateur, sous un nom court. À appeler seulement quand le script marche."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Nom court de l'outil (ex : sauvegarde)"},
            "script": {"type": "string", "description": "Chemin du script dans le dossier de travail (ex : outils/sauvegarde.sh)"},
            "description": {"type": "string", "description": "Ce que fait l'outil, en une phrase"},
        }, "required": ["name", "script"]}}},
]
