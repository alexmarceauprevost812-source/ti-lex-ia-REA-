"""Réglages de l'agent, lus depuis les variables d'environnement."""

import os
from dataclasses import dataclass, field
from pathlib import Path


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
    max_steps: int = 12
    request_timeout: int = 300

    def __post_init__(self) -> None:
        if not self.ollama_host.startswith(("http://", "https://")):
            self.ollama_host = "http://" + self.ollama_host
        self.workspace.mkdir(parents=True, exist_ok=True)
