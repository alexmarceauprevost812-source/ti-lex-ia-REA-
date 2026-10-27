"""Réglages de l'agent, lus depuis les variables d'environnement."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _dossier_moteurs() -> Path:
    """TILEX_MOTEURS si défini ; sinon « moteurs/ » à la racine de la clé
    (à côté du projet) s'il existe ; sinon « moteurs/ » dans le projet."""
    if os.environ.get("TILEX_MOTEURS"):
        return Path(os.environ["TILEX_MOTEURS"]).resolve()
    projet = Path(__file__).resolve().parent.parent
    a_cote = projet.parent / "moteurs"
    return a_cote if a_cote.is_dir() else projet / "moteurs"


@dataclass
class Config:
    ollama_host: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    )
    # Modèle principal : doit supporter les appels d'outils (tool calling).
    model: str = field(default_factory=lambda: os.environ.get("TILEX_MODEL", "qwen3:8b"))
    # Modèle de vision : sert uniquement à décrire les images.
    vision_model: str = field(
        default_factory=lambda: os.environ.get("TILEX_VISION_MODEL", "qwen2.5vl:7b")
    )
    # Dossier de travail : l'agent ne peut lire/écrire que là-dedans.
    workspace: Path = field(
        default_factory=lambda: Path(os.environ.get("TILEX_WORKSPACE", "workspace")).resolve()
    )
    # Dossier des moteurs (schémas, images, voix, vidéo). Sur la clé USB-C, il
    # se trouve à côté du dossier ti-lex-ia-REA- : on le trouve tout seul.
    moteurs: Path = field(default_factory=lambda: _dossier_moteurs())
    max_steps: int = 12
    request_timeout: int = 300

    def __post_init__(self) -> None:
        if not self.ollama_host.startswith(("http://", "https://")):
            self.ollama_host = "http://" + self.ollama_host
        self.workspace.mkdir(parents=True, exist_ok=True)
