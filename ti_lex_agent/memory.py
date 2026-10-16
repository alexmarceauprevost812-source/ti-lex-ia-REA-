"""Mémoire partagée entre les 4 IA locales (Chat, Codex, REA, Heretic).

Un seul fichier texte, lu par les 4 interfaces au démarrage et complété à la
main avec la commande /retenir. Par défaut, il vit à côté du dossier de
travail — si ce dernier est sur la clé USB-C, la mémoire voyage avec elle.
Rien n'est deviné automatiquement : seul ce que tu demandes explicitement de
retenir y va, pour éviter qu'une erreur du modèle devienne une « mémoire ».
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path

from .config import Config

MAX_INJECT_CHARS = 4000       # ce qu'on remet dans le prompt système, sans le gonfler
MIN_FREE_BYTES = 20 * 1024 * 1024  # 20 Mo de marge : on arrête d'écrire avant que la clé soit pleine


def memory_path(config: Config) -> Path:
    custom = os.environ.get("TILEX_MEMORY")
    if custom:
        return Path(custom).expanduser().resolve()
    return config.workspace.parent / "memoire-ia.md"


def load_memory(config: Config) -> str:
    path = memory_path(config)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-MAX_INJECT_CHARS:]


def remember(config: Config, text: str) -> str:
    text = text.strip()
    if not text:
        return "Rien à retenir : texte vide."
    path = memory_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [{stamp}] {text}\n")
    return f"Retenu (partagé avec Chat, Codex, REA, Heretic) : {text}"


def _has_room(path: Path, min_free: int = MIN_FREE_BYTES) -> bool:
    """Vérifie l'espace libre sur le disque qui contiendra le fichier — pour ne
    jamais remplir une petite clé USB-C avec un historique d'erreurs."""
    probe = path.parent if path.parent.exists() else Path.home()
    try:
        return shutil.disk_usage(probe).free > min_free
    except OSError:
        return True  # on ne bloque pas l'agent si l'espace est impossible à vérifier


def remember_error(config: Config, context: str, error: str) -> None:
    """Note une erreur d'outil pour éviter de la refaire.

    Silencieux et sans danger : n'écrit rien si l'erreur est déjà connue ou si
    la clé/le disque manque de place, et ne lève jamais d'exception (une
    mémoire qui plante ne doit jamais faire planter un outil).
    """
    error = error.strip()
    if not error:
        return
    path = memory_path(config)
    try:
        if not _has_room(path):
            return
        existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        if error in existing:
            return  # déjà notée — on évite de répéter la même ligne
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- [erreur à éviter] {context} → {error}\n")
    except OSError:
        pass


def with_memory(system_prompt: str, config: Config) -> str:
    mem = load_memory(config)
    if not mem:
        return system_prompt
    return (f"{system_prompt}\n\nCe que tu sais déjà, retenu plus tôt (partagé entre Chat, "
            f"Codex, REA et Heretic) :\n{mem}")
