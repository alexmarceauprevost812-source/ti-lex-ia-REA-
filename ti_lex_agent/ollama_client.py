"""Client minimal pour l'API HTTP d'Ollama (aucune dépendance en dehors de requests)."""

from __future__ import annotations

import base64
from pathlib import Path

import requests

from .config import Config


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, config: Config):
        self.config = config

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             model: str | None = None, options: dict | None = None) -> dict:
        """Envoie une conversation et retourne le message de réponse du modèle."""
        payload: dict = {
            "model": model or self.config.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        try:
            r = requests.post(
                f"{self.config.ollama_host}/api/chat",
                json=payload,
                timeout=self.config.request_timeout,
            )
        except requests.ConnectionError as e:
            raise OllamaError(
                f"Impossible de joindre Ollama à {self.config.ollama_host}. "
                "Est-il lancé ? (commande : ollama serve)"
            ) from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama a répondu {r.status_code} : {r.text[:300]}")
        return r.json()["message"]

    def describe_image(self, image_path: Path, question: str) -> str:
        """Demande au modèle de vision de décrire une image."""
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        msg = self.chat(
            [{"role": "user", "content": question, "images": [b64]}],
            model=self.config.vision_model,
        )
        return msg.get("content", "")
