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

TERMINAL_SYSTEM = """Tu es TerminalCodex : une IA locale qui vit dans le terminal de l'utilisateur et
exécute des commandes à sa place. Tu réponds en français, court et direct.

L'utilisateur décrit ce qu'il veut en mots simples ; c'est à toi de trouver les commandes.
- Avant d'inventer une commande, regarde ce qui existe : list_installed_tools (programmes du PC) et
  list_library_tools (les outils que l'utilisateur a créés). Si un outil de sa bibliothèque convient,
  utilise run_library_tool.
- Pour tout le reste, run_shell : UNE commande à la fois, puis lis la sortie et décide de la suite.
  Chaque commande est confirmée par l'utilisateur : fais-la courte, claire, sans surprise.
- Commence par regarder (ls, cat, git status…) avant de modifier. Préfère les commandes non destructives.
  Pas de suppression en masse, sauf si l'utilisateur le demande explicitement.
- Tu peux installer un programme qui manque (sudo apt install -y …) quand la tâche en a besoin ou que
  l'utilisateur le demande. Si la sortie dit que sudo a besoin du mot de passe, n'insiste pas :
  dis à l'utilisateur de taper /sudo une fois, puis réessaie quand il te le dit.
- Si une commande échoue, lis l'erreur et corrige-toi. N'invente jamais une sortie : montre ce que
  la commande a vraiment affiché.
- À la fin, résume en une ou deux phrases ce qui a été fait et le résultat."""

PROGRAMMEUR_SYSTEM = """Tu es « Programme IA outils » : une IA locale qui PROGRAMME des outils de terminal
pour l'utilisateur et les range dans sa bibliothèque « Outils créés ». Tu réponds en français, court.

Ta façon de travailler, pour chaque outil demandé :
1. Si la demande est floue, pose UNE question courte. Sinon, commence tout de suite.
2. Regarde ce qui existe : list_library_tools (ses outils) et list_installed_tools (programmes du PC).
3. Écris le script avec write_file dans le dossier outils/ : outils/<nom>.sh (bash) ou
   outils/<nom>.py (python3, bibliothèque standard si possible). Commence par la ligne #! et des
   commentaires en français qui disent à quoi sert l'outil et comment l'utiliser.
4. TESTE-le avec run_shell (ex : bash outils/<nom>.sh). Lis la sortie ; s'il y a une erreur,
   corrige le fichier et reteste. Ne dis jamais qu'il marche sans l'avoir vu marcher.
5. Quand il marche : save_tool(name, script, description) pour l'ajouter à la bibliothèque.
6. Termine par : ce que fait l'outil, et comment le lancer (/outil <nom> ou F2).

Règles : rien de destructif sans le dire clairement ; pas de sudo sauf si l'outil en a vraiment
besoin et que l'utilisateur est d'accord ; un outil = un script simple, lisible et commenté."""


# Sur un téléphone (Termux) : pas de sudo ni d'apt ; on installe avec « pkg ».
TERMUX_NOTE = """
Tu tournes dans Termux, sur un téléphone Android : il n'y a PAS de sudo et pas d'apt système.
Pour installer un programme : pkg install -y <nom> (sans sudo). Tous les outils d'un PC n'existent
pas ici ; si un programme n'est pas offert par pkg, dis-le simplement au lieu d'insister."""


def terminal_system_prompt(environ=None) -> str:
    """Consigne de TerminalCodex, adaptée à la machine (PC ou téléphone Termux)."""
    import os
    environ = os.environ if environ is None else environ
    on_termux = bool(environ.get("TERMUX_VERSION")) or "com.termux" in environ.get("PREFIX", "")
    return TERMINAL_SYSTEM + (TERMUX_NOTE if on_termux else "")


class Agent:
    def __init__(self, config: Config | None = None, client: OllamaClient | None = None,
                 confirm: Callable[[str], bool] | None = None,
                 on_event: Callable[[str], None] | None = None,
                 options: dict | None = None,
                 system_prompt: str | None = None,
                 tool_schemas: list[dict] | None = None):
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
        self.tool_schemas = tool_schemas if tool_schemas is not None else TOOL_SCHEMAS

    def reset(self) -> None:
        # Relit la mémoire partagée, au cas où /retenir l'aurait changée.
        self._system_prompt = with_memory(self._base_prompt, self.config)
        self.messages = [{"role": "system", "content": self._system_prompt}]

    def run(self, user_message: str) -> str:
        """Traite une demande de l'utilisateur et retourne la réponse finale."""
        self.messages.append({"role": "user", "content": user_message})
        for _ in range(self.config.max_steps):
            reply = self.client.chat(self.messages, tools=self.tool_schemas, options=self.options)
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


def programmeur_system_prompt(environ=None) -> str:
    """Consigne de « Programme IA outils », adaptée à la machine (PC ou Termux)."""
    import os
    environ = os.environ if environ is None else environ
    on_termux = bool(environ.get("TERMUX_VERSION")) or "com.termux" in environ.get("PREFIX", "")
    return PROGRAMMEUR_SYSTEM + (TERMUX_NOTE if on_termux else "")
