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

    def chat_stream(self, messages: list[dict], model: str | None = None,
                    options: dict | None = None):
        """Comme chat(), mais en flux : génère les morceaux de texte au fur et à
        mesure, pour que l'interface les affiche en direct au lieu d'attendre."""
        import json
        payload: dict = {
            "model": model or self.config.model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options
        try:
            r = requests.post(
                f"{self.config.ollama_host}/api/chat",
                json=payload,
                timeout=self.config.request_timeout,
                stream=True,
            )
        except requests.ConnectionError as e:
            raise OllamaError(
                f"Impossible de joindre Ollama à {self.config.ollama_host}. "
                "Est-il lancé ? (commande : ollama serve)"
            ) from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama a répondu {r.status_code} : {r.text[:300]}")
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("error"):
                raise OllamaError(str(data["error"]))
            chunk = (data.get("message") or {}).get("content", "")
            if chunk:
                yield chunk
            if data.get("done"):
                break

    def list_models(self) -> list[str]:
        """Liste les modèles déjà présents dans Ollama (GET /api/tags)."""
        try:
            r = requests.get(f"{self.config.ollama_host}/api/tags",
                             timeout=self.config.request_timeout)
        except requests.ConnectionError as e:
            raise OllamaError(
                f"Impossible de joindre Ollama à {self.config.ollama_host}. "
                "Est-il lancé ? (commande : ollama serve)"
            ) from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama a répondu {r.status_code} : {r.text[:300]}")
        return [m["name"] for m in r.json().get("models", [])]

    def describe_image(self, image_path: Path, question: str) -> str:
        """Demande au modèle de vision de décrire une image."""
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        msg = self.chat(
            [{"role": "user", "content": question, "images": [b64]}],
            model=self.config.vision_model,
        )
        return msg.get("content", "")
