"""Interface en ligne de commande : `python -m ti_lex_agent`."""

from __future__ import annotations

import argparse

from .agent import Agent
from .config import Config
from .memory import remember
from .modelops import ModelOpsError, import_to_ollama, run_heretic
from .ollama_client import OllamaError
from .params import DEFAULTS, describe, set_param

AIDE = (
    "/reset                    oublie la conversation (garde la mémoire partagée)\n"
    "/retenir <texte>           ajoute un fait à la mémoire partagée (Chat, Codex, REA, Heretic)\n"
    "/model <nom>               change le modèle utilisé\n"
    "/params                    affiche les réglages de génération\n"
    "/temp <valeur>             raccourci pour /param temperature <valeur>\n"
    "/param <nom> <valeur>      change un réglage (temperature, top_p, ...)\n"
    "/heretic <org/modele>      lance Heretic officiel sur un modèle Hugging Face\n"
    "/importer <dossier> <nom>  importe un modèle modifié dans Ollama\n"
    "/quit"
)


def confirm(question: str) -> bool:
    return input(f"\n⚠️  {question} [o/N] ").strip().lower() in {"o", "oui", "y", "yes"}


def run_conversation(agent: Agent, config: Config, options: dict,
                     extra_quit: set[str] | None = None) -> None:
    """Boucle de conversation interactive, avec les commandes /model, /temp, etc.

    `extra_quit` ajoute des mots qui terminent la boucle sans quitter tout le
    programme (utilisé par launcher.py pour revenir au menu avec /menu).
    """
    quit_words = {"/quit", "/exit"} | (extra_quit or set())
    print("Écris ta demande. /aide pour voir les commandes.\n")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text in quit_words:
            return
        if text == "/reset":
            agent.reset()
            print("Conversation effacée.")
            continue
        if text == "/aide":
            print(AIDE)
            continue
        if text.startswith("/retenir "):
            print(remember(config, text.removeprefix("/retenir ")))
            continue
        if text.startswith("/model "):
            config.model = text.removeprefix("/model ").strip()
            print(f"Modèle principal : {config.model}")
            continue
        if text == "/params":
            print(describe(options))
            continue
        if text.startswith("/temp "):
            text = "/param temperature " + text.removeprefix("/temp ")
        if text.startswith("/param "):
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                print("Usage : /param <nom> <valeur>  (ex : /param temperature 0.9)")
                continue
            try:
                print(set_param(options, parts[1], parts[2]))
            except ValueError as e:
                print(f"Erreur : {e}")
            continue
        if text.startswith("/heretic "):
            try:
                print(run_heretic(text.removeprefix("/heretic ").strip(), confirm))
            except ModelOpsError as e:
                print(f"Erreur : {e}")
            continue
        if text.startswith("/importer "):
            parts = text.split(maxsplit=2)
            if len(parts) != 3:
                print("Usage : /importer <dossier-ou-fichier-gguf> <nom-du-modele>")
                continue
            try:
                print(import_to_ollama(parts[1], parts[2], config, confirm))
            except ModelOpsError as e:
                print(f"Erreur : {e}")
            continue
        print(agent.run(text), "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ti-lex-agent", description="Agent local Ti-Lex (Ollama).")
    p.add_argument("--model", help="Modèle principal (défaut : qwen3:8b)")
    p.add_argument("--vision-model", help="Modèle de vision (défaut : qwen2.5vl:7b)")
    p.add_argument("--workspace", help="Dossier de travail de l'agent (défaut : ./workspace)")
    p.add_argument("prompt", nargs="*", help="Une demande unique (sinon : mode conversation)")
    args = p.parse_args(argv)

    config = Config()
    if args.model:
        config.model = args.model
    if args.vision_model:
        config.vision_model = args.vision_model
    if args.workspace:
        from pathlib import Path
        config.workspace = Path(args.workspace).resolve()
        config.workspace.mkdir(parents=True, exist_ok=True)

    options = dict(DEFAULTS)
    agent = Agent(config, on_event=print, options=options)
    print(f"Ti-Lex agent — modèle : {config.model} — dossier : {config.workspace}")

    try:
        if args.prompt:
            print(agent.run(" ".join(args.prompt)))
            return 0
        run_conversation(agent, config, options)
        return 0
    except OllamaError as e:
        print(f"Erreur : {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
