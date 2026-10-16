"""Modifier les poids d'un modèle avec Heretic, puis l'importer dans Ollama."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .config import Config

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MODEL_RE = re.compile(r"^[\w.-]+/[\w.-]+$|^[\w./~-]+$")  # « org/modele » Hugging Face ou chemin local


class ModelOpsError(Exception):
    pass


def find_heretic() -> str:
    venv = Path(os.environ.get("HERETIC_VENV", Path.home() / "venvs" / "heretic"))
    for candidate in (shutil.which("heretic"), str(venv / "bin" / "heretic")):
        if candidate and Path(candidate).exists():
            return candidate
    raise ModelOpsError(
        "Heretic est introuvable. Installe-le avec : bash scripts/install_heretic.sh"
    )


def run_heretic(model: str, confirm: Callable[[str], bool]) -> str:
    """Lance Heretic en mode interactif (c'est lui qui pose ses questions)."""
    if not MODEL_RE.match(model) or model.startswith("-"):
        raise ModelOpsError("Nom de modèle invalide (ex : Qwen/Qwen3-4B-Instruct-2507).")
    exe = find_heretic()
    if not confirm(
        f"Lancer Heretic sur « {model} » ?\n"
        "    Ça utilise ta carte graphique pendant plusieurs minutes et crée un NOUVEAU\n"
        "    modèle (l'original n'est pas modifié). Heretic retire des garde-fous du modèle."
    ):
        raise ModelOpsError("Annulé.")
    code = subprocess.run([exe, model]).returncode
    if code != 0:
        raise ModelOpsError(f"Heretic s'est arrêté avec le code {code}.")
    return "Heretic a terminé. Si tu as sauvegardé le modèle, importe-le avec : /importer <dossier> <nom>"


def import_to_ollama(folder: str, name: str, config: Config,
                     confirm: Callable[[str], bool]) -> str:
    """Crée un modèle Ollama à partir d'un dossier (safetensors) ou d'un fichier .gguf."""
    if not NAME_RE.match(name):
        raise ModelOpsError("Nom invalide : minuscules, chiffres, . _ - seulement (ex : qwen3-libre).")
    src = Path(folder).expanduser().resolve()
    if not src.exists():
        raise ModelOpsError(f"Introuvable : {src}")
    if src.is_dir() and not (src / "config.json").exists() and not list(src.glob("*.gguf")):
        raise ModelOpsError("Ce dossier ne ressemble pas à un modèle (ni config.json, ni .gguf).")
    if not confirm(f"Créer le modèle Ollama « {name} » depuis {src} ?"):
        raise ModelOpsError("Annulé.")
    if not shutil.which("ollama"):
        raise ModelOpsError("La commande « ollama » est introuvable.")
    modelfile = config.workspace / f"Modelfile.{name}"
    modelfile.write_text(f"FROM {src}\n", encoding="utf-8")
    done = subprocess.run(["ollama", "create", name, "-f", str(modelfile)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise ModelOpsError(f"ollama create a échoué :\n{done.stderr or done.stdout}")
    return (f"Modèle « {name} » créé. Utilise-le avec : /model {name}\n"
            "Teste-le : un modèle modifié peut perdre les appels d'outils.")
