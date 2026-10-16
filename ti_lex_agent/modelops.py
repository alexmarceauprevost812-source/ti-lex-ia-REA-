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
# Référence de modèle Ollama : accepte le tag avec deux-points (ex : llama3.2:1b,
# registry/biblio/modele:tag). Doit commencer par une lettre/chiffre, pas de « - ».
OLLAMA_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


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


def _require_ollama() -> None:
    if not shutil.which("ollama"):
        raise ModelOpsError("La commande « ollama » est introuvable.")


def _run_ollama(args: list[str]) -> str:
    done = subprocess.run(["ollama", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise ModelOpsError((done.stderr or done.stdout or "").strip() or f"ollama {args[0]} a échoué.")
    return done.stdout


def copy_model(src: str, dst: str, confirm: Callable[[str], bool]) -> str:
    """Renomme/duplique un modèle Ollama (ollama cp)."""
    if not src:
        raise ModelOpsError("Modèle source manquant.")
    if not NAME_RE.match(dst):
        raise ModelOpsError("Nom de destination invalide : minuscules, chiffres, . _ - (ex : qwen3-copie).")
    if not confirm(f"Copier « {src} » vers « {dst} » ?"):
        raise ModelOpsError("Annulé.")
    _require_ollama()
    _run_ollama(["cp", src, dst])
    return f"Modèle « {dst} » créé à partir de « {src} »."


def delete_model(name: str, confirm: Callable[[str], bool]) -> str:
    """Supprime un modèle Ollama (ollama rm) — irréversible."""
    if not name:
        raise ModelOpsError("Modèle à supprimer manquant.")
    if not confirm(f"SUPPRIMER le modèle « {name} » ? C'est irréversible."):
        raise ModelOpsError("Annulé.")
    _require_ollama()
    _run_ollama(["rm", name])
    return f"Modèle « {name} » supprimé."


def pull_model(name: str, confirm: Callable[[str], bool]) -> str:
    """Télécharge un modèle depuis la bibliothèque Ollama (ollama pull)."""
    if not OLLAMA_REF_RE.match(name):
        raise ModelOpsError("Nom de modèle invalide (ex : llama3.2:1b).")
    if not confirm(f"Télécharger « {name} » depuis la bibliothèque Ollama ?"):
        raise ModelOpsError("Annulé.")
    _require_ollama()
    _run_ollama(["pull", name])
    return f"Modèle « {name} » téléchargé."


def show_model(name: str) -> str:
    """Retourne le Modelfile d'un modèle (ollama show --modelfile)."""
    if not name:
        raise ModelOpsError("Modèle manquant.")
    _require_ollama()
    return _run_ollama(["show", "--modelfile", name])


def create_variant(base: str, name: str, system: str, temperature, config: Config,
                   confirm: Callable[[str], bool]) -> str:
    """Crée une variante d'un modèle avec un prompt système et/ou une température
    fixés d'avance (ollama create à partir d'un Modelfile généré)."""
    if not NAME_RE.match(name):
        raise ModelOpsError("Nom invalide : minuscules, chiffres, . _ - seulement (ex : qwen3-quebec).")
    if not base:
        raise ModelOpsError("Modèle de base manquant.")
    lines = [f"FROM {base}"]
    if temperature not in (None, ""):
        try:
            t = float(temperature)
        except (TypeError, ValueError):
            raise ModelOpsError("Température invalide (ex : 0.7).")
        if not 0.0 <= t <= 2.0:
            raise ModelOpsError("Température hors plage (0.0 à 2.0).")
        lines.append(f"PARAMETER temperature {t}")
    if system and system.strip():
        escaped = system.replace('"""', '\\"\\"\\"')
        lines.append(f'SYSTEM """{escaped}"""')
    if len(lines) == 1:
        raise ModelOpsError("Rien à changer : donne un prompt système et/ou une température.")
    if not confirm(f"Créer la variante « {name} » à partir de « {base} » ?"):
        raise ModelOpsError("Annulé.")
    _require_ollama()
    modelfile = config.workspace / f"Modelfile.{name}"
    modelfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run_ollama(["create", name, "-f", str(modelfile)])
    return f"Variante « {name} » créée. Choisis-la via la variable TILEX_*_MODEL ou /model {name}."


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
