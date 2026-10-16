"""La boucle de l'agent : le modèle choisit un outil, on l'exécute, on lui redonne le résultat."""

from __future__ import annotations

from typing import Callable

from .config import Config
from .memory import with_memory
from .ollama_client import OllamaClient
from .tools import TOOL_SCHEMAS, Toolbox

SYSTEM_PROMPT = """Tu es l'assistant de Ti-Lex, un agent local qui aide à bâtir des projets.
Tu réponds en français, directement et sans détour.

Tu as des outils : recherche web, lecture de pages, description d'images, lecture/écriture
de fichiers et commandes dans le dossier du projet.
- Pour vérifier un fait ou une info récente, utilise web_search puis fetch_page. Ne devine pas.
- Pour travailler sur un projet : list_files d'abord, puis read_file, puis write_file.
- Après avoir écrit du code, teste-le avec run_command quand c'est possible.
- Si un outil renvoie une erreur, corrige-toi et réessaie autrement.
- Quand tu as fini, réponds avec un court résumé de ce qui a été fait."""


class Agent:
    def __init__(self, config: Config | None = None, client: OllamaClient | None = None,
                 confirm: Callable[[str], bool] | None = None,
                 on_event: Callable[[str], None] | None = None,
                 options: dict | None = None,
                 system_prompt: str | None = None):
        self.config = config or Config()
        self.client = client or OllamaClient(self.config)
        self.tools = Toolbox(self.config, self.client, confirm)
        self.on_event = on_event or (lambda _msg: None)
        # Prompt système de base : celui par défaut, ou un sur-mesure (ex :
        # mode codex-terminal, orienté commandes shell).
        self._base_prompt = system_prompt or SYSTEM_PROMPT
        self._system_prompt = with_memory(self._base_prompt, self.config)
        self.messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        # Réglages de génération (température, etc.) — voir params.py. Partagé par
        # référence avec l'appelant, pour que /temp change aussi les prochains tours.
        self.options: dict = options if options is not None else {}

    def reset(self) -> None:
        # Relit la mémoire partagée, au cas où /retenir l'aurait changée.
        self._system_prompt = with_memory(self._base_prompt, self.config)
        self.messages = [{"role": "system", "content": self._system_prompt}]

    def run(self, user_message: str) -> str:
        """Traite une demande de l'utilisateur et retourne la réponse finale."""
        self.messages.append({"role": "user", "content": user_message})
        for _ in range(self.config.max_steps):
            reply = self.client.chat(self.messages, tools=TOOL_SCHEMAS, options=self.options)
            self.messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                return reply.get("content", "").strip()
            for call in calls:
                fn = call["function"]
                name, args = fn["name"], fn.get("arguments") or {}
                self.on_event(f"🔧 {name}({', '.join(f'{k}={v!r}'[:80] for k, v in args.items())})")
                result = self.tools.call(name, args)
                self.messages.append({"role": "tool", "tool_name": name, "content": result})
        return "(J'ai atteint la limite d'étapes sans finir. Demande-moi de continuer.)"
