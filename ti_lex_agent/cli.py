"""Interface en ligne de commande : `python -m ti_lex_agent`."""

from __future__ import annotations

import argparse

from .agent import Agent
from .config import Config
from .ollama_client import OllamaError


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

    agent = Agent(config, on_event=print)
    print(f"Ti-Lex agent — modèle : {config.model} — dossier : {config.workspace}")

    try:
        if args.prompt:
            print(agent.run(" ".join(args.prompt)))
            return 0
        print("Écris ta demande. /reset pour oublier la conversation, /quit pour sortir.\n")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                return 0
            if text == "/reset":
                agent.reset()
                print("Conversation effacée.")
                continue
            print(agent.run(text), "\n")
    except OllamaError as e:
        print(f"Erreur : {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
