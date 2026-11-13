"""Outils créés : la bibliothèque de tes propres outils de terminal, plus le
clonage de projets GitHub et la création de nouveaux projets.

La bibliothèque est un simple fichier JSON (`outils-crees.json`, à côté du
dossier de travail ; change l'emplacement avec TILEX_OUTILS).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .tools import ToolError, resolve_workspace_path


class OutilError(Exception):
    """Erreur à montrer telle quelle à l'utilisateur."""


# ------------------------------------------------------------------ bibliothèque
def outils_path(config: Config) -> Path:
    custom = os.environ.get("TILEX_OUTILS")
    if custom:
        return Path(custom).expanduser().resolve()
    return config.workspace.parent / "outils-crees.json"


def load(config: Config) -> list[dict]:
    path = outils_path(config)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise OutilError(f"Le fichier {path} est abîmé (JSON invalide).")
    return [t for t in data if isinstance(t, dict) and t.get("nom") and t.get("commande")]


def _save(config: Config, tools: list[dict]) -> None:
    path = outils_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tools, indent=2, ensure_ascii=False), encoding="utf-8")


def find(config: Config, nom: str) -> dict | None:
    for t in load(config):
        if t["nom"].lower() == nom.strip().lower():
            return t
    return None


def add(config: Config, nom: str, commande: str, description: str = "") -> str:
    nom, commande = nom.strip(), commande.strip()
    if not nom or not commande:
        raise OutilError("Il faut un nom et une commande : /ajouter-outil <nom> = <commande>")
    tools = [t for t in load(config) if t["nom"].lower() != nom.lower()]
    replaced = len(tools) != len(load(config))
    tools.append({"nom": nom, "commande": commande, "description": description.strip()})
    tools.sort(key=lambda t: t["nom"].lower())
    _save(config, tools)
    return f"Outil « {nom} » {'mis à jour' if replaced else 'ajouté'} dans la bibliothèque."


def remove(config: Config, nom: str) -> str:
    tools = load(config)
    kept = [t for t in tools if t["nom"].lower() != nom.strip().lower()]
    if len(kept) == len(tools):
        raise OutilError(f"Aucun outil nommé « {nom.strip()} ».")
    _save(config, kept)
    return f"Outil « {nom.strip()} » retiré."


def describe(config: Config) -> str:
    tools = load(config)
    if not tools:
        return ("Ta bibliothèque est vide. Ajoute un outil :\n"
                "  /ajouter-outil <nom> = <commande>\n"
                "  ex : /ajouter-outil sauvegarde = bash ~/scripts/backup.sh")
    width = max(len(t["nom"]) for t in tools)
    lines = [f"  {t['nom']:<{width}}  {t['commande']}" for t in tools]
    return "Outils créés (F2 pour choisir, /outil <nom> pour lancer) :\n" + "\n".join(lines)


# ------------------------------------------------------------------ projets
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
_SSH = re.compile(r"^git@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+$")


def normalize_repo_url(url: str) -> str:
    """Accepte `proprio/depot`, une adresse https://… ou git@hôte:proprio/depot."""
    url = url.strip()
    if _SHORT.match(url):
        return f"https://github.com/{url}"
    if url.startswith("https://") and " " not in url and len(url) > len("https://x/y"):
        return url
    if _SSH.match(url):
        return url
    raise OutilError("Adresse de dépôt non reconnue. Exemples : /cloner proprio/depot  ou  "
                     "/cloner https://github.com/proprio/depot")


def _project_dir(config: Config, nom: str) -> Path:
    if not _NAME_OK.match(nom):
        raise OutilError("Nom de dossier invalide : lettres, chiffres, tirets, points seulement.")
    try:
        target = resolve_workspace_path(config, nom)
    except ToolError as e:
        raise OutilError(str(e))
    if target.exists():
        raise OutilError(f"Le dossier « {nom} » existe déjà dans le dossier de travail.")
    return target


def clone(config: Config, url: str, nom: str = "", timeout: int = 900) -> Path:
    """Clone un dépôt dans le dossier de travail. Retourne le dossier créé."""
    if not shutil.which("git"):
        raise OutilError("git n'est pas installé (sudo apt install git).")
    full = normalize_repo_url(url)
    nom = nom.strip() or full.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    target = _project_dir(config, nom)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")   # jamais de question cachée
    try:
        proc = subprocess.run(["git", "clone", "--", full, str(target)], capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        shutil.rmtree(target, ignore_errors=True)
        raise OutilError("Le clonage a pris trop de temps : arrêté.")
    if proc.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        last = (proc.stderr.strip().splitlines() or ["erreur inconnue"])[-1]
        raise OutilError(f"Clonage impossible : {last}")
    return target


def new_project(config: Config, nom: str) -> Path:
    """Crée un nouveau projet vide (README + dépôt git) dans le dossier de travail."""
    nom = nom.strip()
    target = _project_dir(config, nom)
    target.mkdir(parents=True)
    (target / "README.md").write_text(f"# {nom}\n\nNouveau projet créé avec LexOS.\n",
                                      encoding="utf-8")
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(target)], capture_output=True, timeout=30)
    return target


def run_captured(config: Config, commande: str, timeout: int = 600) -> tuple[int, str]:
    """Lance une commande de la bibliothèque et retourne (code, sortie)."""
    try:
        proc = subprocess.run(commande, shell=True, cwd=str(config.workspace),
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"Arrêté après {timeout} s."
    return proc.returncode, (proc.stdout + proc.stderr).strip()
