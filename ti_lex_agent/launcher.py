"""Menu LexOS Pro : Chat, Codex, REA, Heretic.

Fonctionne en local (installé sur le disque) ou depuis une clé USB — rien ici
ne dépend d'un chemin fixe. Les 4 choix utilisent les modèles déjà présents
dans Ollama (vérifiables avec `ollama list`) ; change-les avec les variables
d'environnement si tes noms diffèrent.
"""

from __future__ import annotations

import os

from .agent import Agent
from .cli import run_conversation
from .config import Config
from .memory import remember, with_memory
from .ollama_client import OllamaClient, OllamaError
from .params import DEFAULTS
from .tools import IMAGE_EXTENSIONS, ToolError, resolve_workspace_path

# Modèles de repli, utilisés quand le modèle principal n'est pas installé sur
# ce PC (ex : un ordinateur moins puissant que celui où Heretic a tourné).
# Changeables avec TILEX_CHAT_FALLBACK, TILEX_CODEX_FALLBACK, etc.
FALLBACK_CHAT = "llama3.2:1b"
FALLBACK_CODEX = "qwen2.5-coder:1.5b"
FALLBACK_REA = "qwen2.5:3b"

ORANGE = "\033[38;5;208m"
GREY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"

BANNER = rf"""{ORANGE}{BOLD}
     _      _____  __  _____  ____
    | |    |  ___| \ \/ / _ \/ ___|
    | |    | |__    \  / | | \___ \
    | |___ |  __|   /  \ |_| |___) |
    |_____||____|  /_/\_\___/|____/{RESET}
    {GREY}P R O   —   U S B - C   /   L O C A L{RESET}
"""

MENU = f"""
  {ORANGE}1{RESET}  Chat     conversation générale
  {ORANGE}2{RESET}  Codex    assistant de code
  {ORANGE}3{RESET}  REA      agent complet (web, vision, fichiers)
  {ORANGE}4{RESET}  Heretic  chat direct, sans filtre
  {GREY}0  quitter{RESET}
"""

CHAT_SYSTEM = (
    "Tu es l'assistant de Ti-Lex. Réponds en français québécois, clairement et "
    "directement."
)
CODEX_SYSTEM = (
    "Tu es un assistant de programmation pour Ti-Lex. Comprends le but et les "
    "contraintes avant de proposer un changement. Fournis du code exploitable "
    "avec les chemins et commandes exacts. Signale tes hypothèses et les limites "
    "de ce que tu peux vérifier. Ne prétends pas avoir exécuté une commande que "
    "tu n'as pas exécutée."
)
HERETIC_SYSTEM = (
    "Tu es TI-LEX-IA, l'assistant local de Normandin. Réponds en français "
    "québécois, de façon claire et directe."
)


def _env_model(var: str, default: str) -> str:
    return os.environ.get(var, default)


def _has_model(available: list[str], name: str) -> bool:
    """Ollama liste parfois le tag implicite (ex: le modèle 'x' peut apparaître
    comme 'x:latest') — on compare le nom exact et le préfixe avant ':'."""
    return name in available or any(m.split(":")[0] == name.split(":")[0] for m in available)


def resolve_model(client: OllamaClient, primary: str, fallback: str, label: str) -> str | None:
    """Vérifie que le modèle principal est présent ; sinon propose le repli.

    Retourne le nom à utiliser, ou None si ni l'un ni l'autre n'est installé
    (le message d'erreur explique quoi faire).
    """
    try:
        available = client.list_models()
    except OllamaError as e:
        print(f"Erreur : {e}")
        return None
    if _has_model(available, primary):
        return primary
    print(f"{GREY}« {primary} » n'est pas installé sur ce PC — "
          f"essai du modèle plus léger « {fallback} »...{RESET}")
    if _has_model(available, fallback):
        if label == "Heretic":
            print(f"{GREY}Note : « {fallback} » est un modèle normal, PAS décensuré — "
                  f"Heretic doit d'abord tourner dessus pour ça (voir /heretic).{RESET}")
        return fallback
    print(
        f"Erreur : ni « {primary} » ni « {fallback} » ne sont installés.\n"
        f"    Installe-en un avec : ollama pull {fallback}"
    )
    return None


def _handle_image(config: Config, client: OllamaClient, messages: list[dict], text: str) -> None:
    """/image <chemin> [question] — décrit une image avec le modèle de vision
    et l'ajoute à la conversation, pour que Chat/Codex puissent réagir dessus
    même si leur propre modèle ne gère pas les images."""
    parts = text.removeprefix("/image ").strip().split(maxsplit=1)
    if not parts or not parts[0]:
        print("Usage : /image <chemin-dans-le-dossier-de-travail> [question]\n")
        return
    rel_path, question = parts[0], (parts[1] if len(parts) > 1 else "Décris cette image en détail.")
    try:
        target = resolve_workspace_path(config, rel_path)
    except ToolError as e:
        print(f"Erreur : {e}\n")
        return
    if target.suffix.lower() not in IMAGE_EXTENSIONS:
        print("Erreur : format non supporté (png, jpg, jpeg, webp, gif, bmp).\n")
        return
    if not target.is_file():
        print(f"Erreur : image introuvable : {rel_path}\n")
        return
    print(f"{GREY}Analyse de l'image avec le modèle de vision ({config.vision_model})...{RESET}")
    try:
        description = client.describe_image(target, question)
    except OllamaError as e:
        print(f"Erreur : {e}\n")
        return
    messages.append({"role": "user", "content": f"[Image jointe : {rel_path}]\n{description}"})
    print(f"{GREY}Image décrite et ajoutée à la conversation — pose ta question dessus.{RESET}\n")


def _simple_chat(config: Config, model: str, system: str, label: str) -> None:
    """Conversation sans outils : plus rapide, pour Chat / Codex / Heretic.
    Partage la mémoire des autres interfaces et peut y ajouter avec /retenir."""
    client = OllamaClient(config)
    messages = [{"role": "system", "content": with_memory(system, config)}]
    print(f"\n{ORANGE}{BOLD}— {label} —{RESET}  (modèle : {model})  "
          f"/image <fichier>  /retenir <texte>  /menu pour revenir\n")
    while True:
        try:
            text = input(f"{ORANGE}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text in {"/quit", "/exit", "/menu"}:
            return
        if text.startswith("/retenir "):
            print(remember(config, text.removeprefix("/retenir ")), "\n")
            continue
        if text.startswith("/image "):
            _handle_image(config, client, messages, text)
            continue
        messages.append({"role": "user", "content": text})
        try:
            reply = client.chat(messages, model=model)
        except OllamaError as e:
            print(f"Erreur : {e}")
            messages.pop()
            continue
        messages.append(reply)
        print(reply.get("content", "").strip(), "\n")


def _run_rea(config: Config, model: str) -> None:
    rea_config = Config(
        ollama_host=config.ollama_host,
        model=model,
        vision_model=config.vision_model,
        workspace=config.workspace,
    )
    rea_options = dict(DEFAULTS)
    agent = Agent(rea_config, on_event=print, options=rea_options)
    print(f"\n{ORANGE}{BOLD}— REA —{RESET}  (modèle : {rea_config.model})  "
          f"dossier : {rea_config.workspace}  /menu pour revenir au menu\n")
    run_conversation(agent, rea_config, rea_options, extra_quit={"/menu"})


def main() -> int:
    config = Config()
    client = OllamaClient(config)
    print(BANNER)
    while True:
        print(MENU)
        try:
            choice = input(f"{ORANGE}choix >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in {"0", "/quit", "q"}:
            return 0
        elif choice == "1":
            model = resolve_model(client, _env_model("TILEX_CHAT_MODEL", "qwen3-vl:4b"),
                                  _env_model("TILEX_CHAT_FALLBACK", FALLBACK_CHAT), "Chat")
            if model:
                _simple_chat(config, model, CHAT_SYSTEM, "Chat")
        elif choice == "2":
            model = resolve_model(client, _env_model("TILEX_CODEX_MODEL", "qwen2.5-coder:7b"),
                                  _env_model("TILEX_CODEX_FALLBACK", FALLBACK_CODEX), "Codex")
            if model:
                _simple_chat(config, model, CODEX_SYSTEM, "Codex")
        elif choice == "3":
            model = resolve_model(client, _env_model("TILEX_REA_MODEL", "heretic:latest"),
                                  _env_model("TILEX_REA_FALLBACK", FALLBACK_REA), "REA")
            if model:
                if model != "heretic:latest":
                    print(f"{GREY}Note : les petits modèles enchaînent les outils moins "
                          f"bien — surveille si REA utilise 🔧 correctement.{RESET}")
                _run_rea(config, model)
        elif choice == "4":
            model = resolve_model(client, _env_model("TILEX_HERETIC_MODEL", "heretic:latest"),
                                  _env_model("TILEX_CHAT_FALLBACK", FALLBACK_CHAT), "Heretic")
            if model:
                _simple_chat(config, model, HERETIC_SYSTEM, "Heretic")
        else:
            print("Choix invalide — tape 1, 2, 3, 4 ou 0.")


if __name__ == "__main__":
    raise SystemExit(main())
