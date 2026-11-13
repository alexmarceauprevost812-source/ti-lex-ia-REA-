"""Interface plein écran LexOS : REA, Codex, Chat et TerminalCodex dans la même fenêtre.

Même écran pour tous les modes ; seul le moteur change (modèle, outils,
consigne). Heretic reste dans son propre menu (`lexos-ia`).

    lexos-tui                       # ouvre l'interface
    lexos-tui --workspace ~/projet  # choisit le dossier de travail

Raccourcis : Ctrl+T change de mode · Ctrl+B fichiers · Ctrl+O aperçu ·
Ctrl+P moteur (modèle) · Ctrl+N nouvelle conversation · Échap arrête ·
Ctrl+Q quitte. Tout est aussi accessible à la souris, et avec des commandes
tapées (/aide pour les voir).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pygments.style import Style as PygmentsStyle
from pygments.token import (Comment, Error, Generic, Keyword, Name, Number, Operator,
                            Punctuation, String, Token)
from rich import box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import PygmentsSyntaxTheme, Syntax
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import Button, DirectoryTree, Footer, Input, OptionList, Static, Tab, Tabs
from textual.widgets.option_list import Option

from . import outils
from .agent import Agent, programmeur_system_prompt, terminal_system_prompt
from .config import Config
from .launcher import (CHAT_SYSTEM, CODEX_SYSTEM, FALLBACK_CHAT, FALLBACK_CODEX,
                       FALLBACK_REA, _env_model, _has_model)
from .memory import remember, with_memory
from .ollama_client import OllamaClient, OllamaError
from .params import DEFAULTS, describe, set_param
from .tools import (PROGRAMMEUR_TOOL_SCHEMAS, TERMINAL_TOOL_SCHEMAS, ToolError,
                    resolve_workspace_path)

# --------------------------------------------------------------------------- couleurs
BLACK = "#000000"
WHITE = "#ffffff"          # ce que tu écris
SKY = "#87ceeb"            # ce que l'IA répond (bleu ciel, comme Heretic)
GREY = "#7d8a9c"
NEON_CYAN = "#00f0ff"
NEON_PINK = "#ff2bd6"
NEON_GREEN = "#39ff14"
NEON_YELLOW = "#ffe600"
NEON_ORANGE = "#ff9f1c"
AI_COLOR = NEON_ORANGE     # ce que l'IA écrit : orange néon
GOLD = "#ffd700"           # les commandes lancées : jaune or
TYPE_SECONDS = 1.2         # durée max de l'écriture fluide d'une réponse
NEON_PURPLE = "#b967ff"
RED = "#ff3860"

# --------------------------------------------------------------------------- animations
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
NEON_CYCLE = [NEON_CYAN, NEON_PINK, NEON_GREEN, NEON_YELLOW, NEON_ORANGE, NEON_PURPLE]
BRAND = "LEXOS"
ANIM_STEP = 0.12           # secondes entre deux images


def spinner_frame(tick: int) -> str:
    return SPINNER[tick % len(SPINNER)]


def brand_text(tick: int, busy: bool) -> Text:
    """Le logo LEXOS : « LEX » en blanc, « OS » en orange néon. Au repos, un éclat
    néon glisse doucement d'une lettre à l'autre, puis fait une pause. Quand le
    modèle travaille, les lettres changent de couleur néon."""
    out = Text()
    glint = (tick // 2) % (len(BRAND) + 6)
    for i, ch in enumerate(BRAND):
        if busy:
            out.append(ch, style=f"bold {NEON_CYCLE[(tick + i) % len(NEON_CYCLE)]}")
        elif i == glint:
            out.append(ch, style=f"bold {NEON_CYAN}")
        else:
            out.append(ch, style=f"bold {WHITE if i < 3 else NEON_ORANGE}")
    return out


class NeonStyle(PygmentsStyle):
    """Couleurs néon sur fond noir pour le code (REA, Codex et Chat)."""

    name = "lexos-neon"
    background_color = BLACK
    highlight_color = "#101820"
    styles = {
        Token: "#f2f2f2",
        Comment: f"italic #5f7385",
        Keyword: f"bold {NEON_PINK}",
        Keyword.Constant: f"bold {NEON_YELLOW}",
        Keyword.Type: f"{NEON_CYAN}",
        Operator: f"{NEON_PINK}",
        Operator.Word: f"bold {NEON_PINK}",
        Punctuation: "#c3ccd8",
        Name: "#f2f2f2",
        Name.Builtin: f"{NEON_YELLOW}",
        Name.Function: f"bold {NEON_CYAN}",
        Name.Class: f"bold {NEON_GREEN}",
        Name.Decorator: f"{NEON_PURPLE}",
        Name.Exception: f"bold {RED}",
        Name.Tag: f"{NEON_PINK}",
        Name.Attribute: f"{NEON_GREEN}",
        Name.Constant: f"{NEON_YELLOW}",
        Name.Variable.Magic: f"{NEON_PURPLE}",
        String: f"{NEON_GREEN}",
        String.Escape: f"{NEON_YELLOW}",
        String.Interpol: f"{NEON_CYAN}",
        String.Doc: f"italic #4fae3b",
        Number: f"{NEON_ORANGE}",
        Generic.Deleted: f"{RED}",
        Generic.Inserted: f"{NEON_GREEN}",
        Generic.Heading: f"bold {NEON_CYAN}",
        Generic.Subheading: f"bold {NEON_PURPLE}",
        Generic.Error: f"{RED}",
        Error: f"{RED}",
    }


NEON_THEME = PygmentsSyntaxTheme(NeonStyle)

NOIR = Theme(
    name="lexos-noir",
    primary=SKY,
    secondary=NEON_CYAN,
    accent=NEON_PINK,
    foreground=WHITE,
    background=BLACK,
    surface=BLACK,
    panel="#050a0f",
    success=NEON_GREEN,
    warning=NEON_YELLOW,
    error=RED,
    dark=True,
)


# ------------------------------------------------------------------ texte → affichage
_FENCE_OPEN = re.compile(r"^[ \t]*```[ \t]*([\w+#.-]*)[ \t]*$")


def split_blocks(text: str) -> list[tuple[str, str, str]]:
    """Sépare une réponse en morceaux ("text"|"code", contenu, langage).

    Un bloc de code pas encore refermé (réponse en cours d'écriture) est quand
    même rendu comme du code, pour que la couleur apparaisse en direct."""
    blocks: list[tuple[str, str, str]] = []
    prose: list[str] = []
    code: list[str] = []
    lang = ""
    in_code = False

    def flush_prose() -> None:
        if prose and "\n".join(prose).strip():
            blocks.append(("text", "\n".join(prose).strip("\n"), ""))
        prose.clear()

    for line in text.split("\n"):
        if not in_code:
            m = _FENCE_OPEN.match(line)
            if m:
                flush_prose()
                in_code, lang, code = True, m.group(1), []
            else:
                prose.append(line)
        elif line.strip().startswith("```"):
            blocks.append(("code", "\n".join(code), lang))
            in_code = False
        else:
            code.append(line)
    if in_code:
        blocks.append(("code", "\n".join(code), lang))
    else:
        flush_prose()
    return blocks


def split_think(text: str) -> tuple[str, bool]:
    """Retire les blocs <think>…</think> des modèles Qwen3.

    Retourne (texte visible, True si le modèle est encore en train de réfléchir)."""
    if "</think>" in text and "<think>" not in text:
        text = text.split("</think>", 1)[1]
    visible = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    thinking = False
    idx = visible.find("<think>")
    if idx != -1:
        visible, thinking = visible[:idx], True
    return visible.lstrip("\n"), thinking


def code_panel(code: str, lang: str) -> Panel:
    syntax = Syntax(code, (lang or "text").lower(), theme=NEON_THEME,
                    background_color=BLACK, word_wrap=True, padding=(0, 1))
    return Panel(syntax, title=lang or "code", title_align="left", box=box.ROUNDED,
                 border_style=NEON_CYAN, style=f"on {BLACK}")


def render_ai(label: str, text: str) -> RenderableType:
    visible, thinking = split_think(text)
    parts: list[RenderableType] = [Text(f"{label} ▸", style=f"bold {AI_COLOR}")]
    for kind, body, lang in split_blocks(visible):
        if kind == "text":
            parts.append(Markdown(body, style=AI_COLOR, inline_code_theme=NeonStyle))
        else:
            parts.append(code_panel(body, lang))
    if thinking:
        parts.append(Text("💭 réflexion…", style=f"italic {GREY}"))
    elif len(parts) == 1:
        parts.append(Text("…", style=GREY))
    return Group(*parts)


def fmt_call(name: str, args: dict) -> str:
    """Résumé lisible d'un appel d'outil."""
    if name == "run_shell" and "command" in args:
        return f"$ {str(args['command'])[:200]}"
    main = next((args[k] for k in ("path", "command", "query", "url") if k in args), None)
    if name == "write_file" and "content" in args:
        return f"{name}  {args.get('path', '?')}  ({len(str(args['content']))} car.)"
    if main is not None:
        return f"{name}  {str(main)[:100]}"
    return f"{name}  " + ", ".join(f"{k}={str(v)[:40]!r}" for k, v in args.items())


def summarize_result(result: str, max_lines: int = 6, width: int = 140) -> str:
    lines = [ln for ln in result.splitlines() if ln.strip()]
    shown = [ln[:width] + ("…" if len(ln) > width else "") for ln in lines[:max_lines]]
    if len(lines) > max_lines:
        shown.append(f"… (+{len(lines) - max_lines} lignes)")
    return "\n".join(shown)


def pick_model(available: list[str], primary: str, fallback: str) -> tuple[str, str | None]:
    """Choisit le modèle à utiliser sans rien afficher. Retourne (nom, remarque)."""
    if not available or _has_model(available, primary):
        return primary, None
    if _has_model(available, fallback):
        return fallback, f"« {primary} » n'est pas installé — j'utilise « {fallback} »."
    return available[0], (f"« {primary} » et « {fallback} » sont absents — j'utilise "
                          f"« {available[0]} », le seul disponible.")


# --------------------------------------------------------------------------- accueil
@dataclass(frozen=True)
class Logo:
    """Un mot en grandes lettres (police « slant », comme la bannière KALI). Chaque lettre
    est donnée à sa place finale : superposées, elles redonnent le mot exact."""
    width: int
    white: int
    letters: list


TILEX_LOGO = Logo(
    width=34, white=3,   # les 3 premières lettres en blanc, le reste en orange néon
    letters=[
        [   # T
            '  ______',
            ' /_  __/',
            '  / /',
            ' / /',
            '/_/',
        ],
        [   # I
            '        ____',
            '          _/',
            '       / /',
            '     _/ /',
            '    /___/',
        ],
        [   # -
            '',
            '',
            '          _____',
            '         _____/',
            '',
        ],
        [   # L
            '                 __',
            '                / /',
            '               / /',
            '                /___',
            '             /_____/',
        ],
        [   # E
            '                       ______',
            '                      / ____/',
            '                     / __/',
            '                    / /___',
            '                    _____/',
        ],
        [   # X
            '                             _  __',
            '                              |/ /',
            '                            |   /',
            '                           /   |',
            '                          /_/|_|',
        ],
    ],
)

TERMINALCODEX_LOGO = Logo(
    width=71, white=8,   # les 8 premières lettres en blanc, le reste en orange néon
    letters=[
        [   # T
            '  ______',
            ' /_  __/',
            '  / /',
            ' / /',
            '/_/',
        ],
        [   # e
            '',
            '        __',
            '      / _ \\',
            '     /  __/',
            '     \\___/',
        ],
        [   # r
            '',
            '            _____',
            '           / ___/',
            '            /',
            '          _/',
        ],
        [   # m
            '',
            '                 ____ ___',
            '                  __ `__ \\',
            '               / / / / / /',
            '              /_/ /_/ /_/',
        ],
        [   # i
            '                            _',
            '                           (_)',
            '                          / /',
            '                           /',
            '                         _/',
        ],
        [   # n
            '',
            '                              ___',
            '                              __ \\',
            '                             / / /',
            '                           _/ /_/',
        ],
        [   # a
            '',
            '                                   ____ _',
            '                                  / __ `/',
            '                                   /_/ /',
            '                                 \\__,_/',
        ],
        [   # l
            '                                          __',
            '                                         / /',
            '                                          /',
            '                                         /',
            '                                       _/',
        ],
        [   # C
            '                                            ______',
            '                                             ____/',
            '                                            /',
            '                                           /___',
            '                                         \\____/',
        ],
        [   # o
            '',
            '                                                  ___',
            '                                                / __ \\',
            '                                               / /_/ /',
            '                                               \\____/',
        ],
        [   # d
            '                                                            __',
            '                                                       ____/ /',
            '                                                      / __  /',
            '                                                       /_/ /',
            '                                                     \\__,_/',
        ],
        [   # e
            '',
            '                                                              __',
            '                                                              _ \\',
            '                                                              __/',
            '                                                           \\___/',
        ],
        [   # x
            '',
            '                                                                  _  __',
            '                                                                 | |/_/',
            '                                                                 >  <',
            '                                                                _/|_|',
        ],
    ],
)

PROGRAMMEUR_LOGO = Logo(
    width=71, white=9,   # « Programme » en blanc, « IA » en orange néon
    letters=[
        [   # P
            '    ____',
            '   / __ \\',
            '  / /_/ /',
            ' / ____/',
            '/_/',
        ],
        [   # r
            '',
            '         _____',
            '          ___/',
            '         /',
            '      /_/',
        ],
        [   # o
            '',
            '              ____',
            '               __ \\',
            '            / /_/ /',
            '            \\____/',
        ],
        [   # g
            '',
            '                    ____ _',
            '                   / __ `/',
            '                    /_/ /',
            '                  \\__, /',
        ],
        [   # r
            '',
            '                          _____',
            '                           ___/',
            '                          /',
            '                        _/',
        ],
        [   # a
            '',
            '                               ____ _',
            '                                __ `/',
            '                             / /_/ /',
            '                             \\__,_/',
        ],
        [   # m
            '',
            '                                     ____ ___',
            '                                      __ `__ \\',
            '                                     / / / / /',
            '                                   _/ /_/ /_/',
        ],
        [   # m
            '',
            '                                               ____ ___',
            '                                              / __ `__ \\',
            '                                               / / / / /',
            '                                             _/ /_/ /_/',
        ],
        [   # e
            '',
            '                                                         ___',
            '                                                        / _ \\',
            '                                                          __/',
            '                                                       \\___/',
        ],
        [   # I
            '                                                               ____',
            '                                                              /  _/',
            '                                                              / /',
            '                                                             / /',
            '                                                            ___/',
        ],
        [   # A
            '                                                                   ___',
            '                                                                      |',
            '                                                                 / /| |',
            '                                                                / ___ |',
            '                                                                _/  |_|',
        ],
    ],
)

# Animation jouée à la première entrée dans un outil : (logo, sous-titre).
INTROS = {
    "terminalcodex": (TERMINALCODEX_LOGO, "l'IA locale qui lance les commandes pour toi"),
    "programmeur": (PROGRAMMEUR_LOGO, "l'IA locale qui programme tes outils"),
}

SPLASH_ROWS = 12            # hauteur du « ciel » ; le mot se pose tout en bas, bien droit
SPLASH_GAP = 3              # images d'écart entre deux lettres qui tombent
SPLASH_SLIDE = 2            # colonnes par ligne de chute : 2 ≈ une descente à 45°
SPLASH_STEP = 0.05          # secondes entre deux images
MENU_STEP = 0.13            # secondes entre l'apparition de deux choix
INTRO_HOLD = 2.0            # secondes où le mot reste affiché avant d'ouvrir l'outil
MENU_CHOICES = [
    ("rea", "REA", "agent complet : web, vision, fichiers, commandes"),
    ("codex", "Codex", "assistant de programmation"),
    ("chat", "Chat", "conversation générale"),
    ("terminalcodex", "TerminalCodex", "écris ce que tu veux : l'IA lance les commandes"),
    ("programmeur", "Programme IA outils", "décris un outil : l'IA le programme et le range"),
    ("outils", "Outils créés", "ta bibliothèque d'outils"),
    ("cloner", "Cloner un projet GitHub", "copie un dépôt dans ton dossier de travail"),
    ("nouveau", "Nouveau projet", "démarre un projet vide"),
    ("quitter", "Quitter", ""),
]


def splash_letter_pos(index: int, tick: int) -> tuple[int, int]:
    """(ligne du haut, décalage vers la droite) de la lettre `index` à l'image `tick`.
    Une lettre descend du ciel à 45° : tant qu'elle est en l'air elle est décalée de
    SPLASH_SLIDE colonnes par ligne qu'il lui reste à descendre. Posée : décalage 0."""
    target = SPLASH_ROWS - 5
    y = min(target, -5 + tick - index * SPLASH_GAP)
    return y, (target - y) * SPLASH_SLIDE


def splash_done_tick(logo: Logo = TILEX_LOGO) -> int:
    return SPLASH_ROWS + (len(logo.letters) - 1) * SPLASH_GAP


def splash_frame(tick: int, logo: Logo = TILEX_LOGO, centered: bool = False) -> Text:
    """Une image de l'animation : chaque lettre arrive du ciel en diagonale (45°) et se
    pose à sa place ; le mot fini est bien droit, sur une seule ligne.
    `centered` : l'image fait exactement la largeur du mot (pour le centrer à l'écran) ;
    les lettres de la moitié gauche arrivent alors par la gauche, les autres par la droite."""
    target = SPLASH_ROWS - 5
    width = logo.width if centered else logo.width + (target + 5) * SPLASH_SLIDE
    grid: list[list[tuple[str, str]]] = [[(" ", WHITE)] * width for _ in range(SPLASH_ROWS)]
    for i, glyph in enumerate(logo.letters):
        y, dx = splash_letter_pos(i, tick)
        if centered and i < len(logo.letters) / 2:
            dx = -dx
        landed = y >= target
        just = landed and (-5 + tick - i * SPLASH_GAP) - target < 3     # éclat à l'atterrissage
        final = WHITE if i < logo.white else NEON_ORANGE
        color = (NEON_YELLOW if just else final) if landed else NEON_CYCLE[(tick + i) % len(NEON_CYCLE)]
        for g, line in enumerate(glyph):
            if 0 <= y + g < SPLASH_ROWS:
                for c, cell in enumerate(line):
                    if cell != " " and 0 <= dx + c < width:
                        grid[y + g][dx + c] = (cell, color)
    out = Text()
    for r, row in enumerate(grid):
        for cell, color in row:
            out.append(cell, style=f"bold {color}")
        if r < SPLASH_ROWS - 1:
            out.append("\n")
    return out


class IntroScreen(Screen[None]):
    """Entrée dans un outil : son nom tombe du ciel, reste au centre de l'écran
    INTRO_HOLD secondes, puis l'outil s'ouvre. N'importe quelle touche passe."""

    def __init__(self, logo: Logo, subtitle: str, animated: bool = True) -> None:
        super().__init__()
        self.logo, self.subtitle, self.animated = logo, subtitle, animated
        self._tick = 0
        self._timer = None
        self._closed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="intro"):
            yield Static("", id="intro-logo")
            yield Static(Text(self.subtitle, style=GREY), id="intro-sub")

    def on_mount(self) -> None:
        if not self.animated:
            self._landed()
            return
        self.query_one("#intro-logo", Static).update(splash_frame(0, self.logo, True))
        self._timer = self.set_interval(SPLASH_STEP, self._fall)

    def _fall(self) -> None:
        self._tick += 1
        self.query_one("#intro-logo", Static).update(splash_frame(self._tick, self.logo, True))
        if self._tick >= splash_done_tick(self.logo) + 3:
            self._landed()

    def _landed(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.query_one("#intro-logo", Static).update(
            splash_frame(splash_done_tick(self.logo) + 10, self.logo, True))
        self._timer = self.set_timer(INTRO_HOLD, self._close)

    def _close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._timer is not None:
                self._timer.stop()
            self.dismiss(None)

    def on_key(self, event) -> None:
        event.stop()
        self._close()


class SplashScreen(Screen[str]):
    """Accueil : « TI-LEX » tombe du ciel, puis les choix du menu arrivent un par un."""

    BINDINGS = [("escape", "skip", "Passer")]

    def __init__(self, animated: bool = True) -> None:
        super().__init__()
        self.animated = animated
        self._tick = 0
        self._shown = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="splash"):
            yield Static("", id="splash-logo")
            yield Static(Text("LexOS Pro — ton terminal IA", style=GREY), id="splash-sub")
            yield OptionList(id="splash-menu")
            yield Static(Text("↑↓ puis Entrée · chiffres 1-9 · Échap passe l'animation",
                              style=GREY), id="splash-hint")

    def on_mount(self) -> None:
        if not self.animated:
            self._finish()
            return
        self.query_one("#splash-logo", Static).update(splash_frame(0))
        self._timer = self.set_interval(SPLASH_STEP, self._fall)

    def _fall(self) -> None:
        self._tick += 1
        self.query_one("#splash-logo", Static).update(splash_frame(self._tick))
        if self._tick >= splash_done_tick() + 3:
            self._timer.stop()
            self._timer = self.set_interval(MENU_STEP, self._reveal)

    def _reveal(self) -> None:
        if self._shown >= len(MENU_CHOICES):
            self._timer.stop()
            return
        self._add_choice(self._shown)
        self._shown += 1

    def _add_choice(self, i: int) -> None:
        key, label, desc = MENU_CHOICES[i]
        line = Text.assemble((f" {i + 1}  ", f"bold {NEON_ORANGE}"), (f"{label:<26}", f"bold {WHITE}"),
                             (desc, "#b8c0cc"))
        menu = self.query_one("#splash-menu", OptionList)
        menu.add_option(Option(line, id=key))
        if i == 0:
            menu.highlighted = 0
            menu.focus()

    def _finish(self) -> None:
        """Saute à la fin : mot posé, tous les choix visibles."""
        if self._timer is not None:
            self._timer.stop()
        self.query_one("#splash-logo", Static).update(splash_frame(splash_done_tick() + 10))
        while self._shown < len(MENU_CHOICES):
            self._add_choice(self._shown)
            self._shown += 1

    def action_skip(self) -> None:
        self._finish()

    def on_key(self, event) -> None:
        if event.key.isdigit() and 1 <= int(event.key) <= len(MENU_CHOICES):
            event.stop()
            self.dismiss(MENU_CHOICES[int(event.key) - 1][0])

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)


# ----------------------------------------------------------------------------- données
@dataclass
class Entry:
    kind: str                         # user | ai | tool | info | error
    text: str = ""
    label: str = ""
    detail: str = ""
    widget: Static | None = field(default=None, repr=False)


@dataclass
class Mode:
    key: str
    label: str
    primary: str
    fallback: str
    system: str
    tools: bool
    config: Config
    client: Any
    options: dict
    transcript: list[Entry] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    agent: Agent | None = None

    @property
    def model(self) -> str:
        return self.config.model


class _Stopped(Exception):
    """L'utilisateur a demandé d'arrêter pendant que REA travaillait."""


SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache",
             ".mypy_cache", ".idea", ".vscode"}
MAX_VIEW_BYTES = 300_000

AIDE = """\
Modes        Ctrl+T (suivant) · /rea · /codex · /chat · /terminalcodex · /programme · clic
Panneaux     Ctrl+B fichiers · Ctrl+O aperçu · /fichiers · /apercu · clic sur ✕
Moteur       Ctrl+P ou /model (liste) · /model <nom>
Fichiers     clic sur un fichier = ouvre l'aperçu · /ouvrir <chemin>
Conversation Ctrl+N ou /reset · Échap arrête la réponse · /retenir <texte>
Outils créés F2 ou /outils (liste) · /outil <nom> (lancer)
             /ajouter-outil <nom> = <commande> · /retirer-outil <nom>
Projets      /cloner <proprio/depot ou adresse> [dossier] · /nouveau <nom>
             /sudo : tape ton mot de passe UNE fois (pour installer des outils) · /sudo off
TerminalCodex /auto : lance les commandes sans demander (sauf les dangereuses) · /auto = on/off
Accueil      /accueil (menu de départ)
Réglages     /params · /temp <valeur> · /param <nom> <valeur>
Quitter      Ctrl+Q ou /quit
Astuce       Shift + souris pour copier du texte dans le terminal"""


# --------------------------------------------------------------------------- fenêtres
class ConfirmScreen(ModalScreen[bool]):
    """Demande de confirmation (écraser un fichier, lancer une commande)."""

    BINDINGS = [("o", "yes", "Oui"), ("y", "yes", "Oui"), ("n", "no", "Non"),
                ("escape", "no", "Non")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text("⚠  " + self.question, style=f"bold {NEON_YELLOW}"), id="dialog-q")
            with Horizontal(id="dialog-btns"):
                yield Button("Oui (o)", id="yes")
                yield Button("Non (n)", id="no")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class ModelPicker(ModalScreen[str | None]):
    """Choix du moteur : les modèles présents dans Ollama."""

    BINDINGS = [("escape", "cancel", "Annuler")]

    def __init__(self, names: list[str], current: str, title: str) -> None:
        super().__init__()
        self.names, self.current, self.title_text = names, current, title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self.title_text, style=f"bold {SKY}"), id="dialog-q")
            yield OptionList(*[Option(n, id=n) for n in self.names], id="models")

    def on_mount(self) -> None:
        lst = self.query_one(OptionList)
        for i, n in enumerate(self.names):
            if n == self.current or _has_model([n], self.current):
                lst.highlighted = i
                break
        lst.focus()

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ToolPicker(ModalScreen[str | None]):
    """Bibliothèque « Outils créés » : choisis un outil pour le lancer."""

    BINDINGS = [("escape", "cancel", "Annuler")]

    def __init__(self, tools: list[dict]) -> None:
        super().__init__()
        self.tools = tools

    def compose(self) -> ComposeResult:
        width = max(len(t["nom"]) for t in self.tools)
        with Vertical(id="dialog"):
            yield Static(Text("🧰 Outils créés — Entrée pour lancer", style=f"bold {SKY}"),
                         id="dialog-q")
            yield OptionList(*[
                Option(Text.assemble((f"{t['nom']:<{width}}  ", f"bold {WHITE}"),
                                     (t.get("description") or t["commande"], GREY)),
                       id=t["nom"])
                for t in self.tools], id="tools")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class WorkspaceTree(DirectoryTree):
    def filter_paths(self, paths):
        return [p for p in paths if p.name not in SKIP_DIRS]


# ------------------------------------------------------------------------- application
class LexosApp(App):
    TITLE = "LexOS Pro"
    ENABLE_COMMAND_PALETTE = False

    CSS = f"""
    Screen {{ background: {BLACK}; color: {WHITE}; }}
    #top {{ height: 2; background: {BLACK}; }}
    #brand {{ width: 14; height: 2; padding: 0 2; color: {WHITE}; text-style: bold; }}
    Tabs {{ width: 1fr; background: {BLACK}; }}
    Tab {{ color: {GREY}; background: {BLACK}; }}
    Tab.-active {{ color: {SKY}; text-style: bold; background: {BLACK}; }}
    Tab:hover {{ color: {NEON_CYAN}; }}
    Underline > .underline--bar {{ color: {NEON_CYAN}; background: #0b1a22; }}
    #body {{ height: 1fr; background: {BLACK}; }}
    #files {{ width: 28; background: {BLACK}; border-right: tall #0b2a3a; }}
    #viewer {{ width: 46%; background: {BLACK}; border-left: tall #0b2a3a; display: none; }}
    #main {{ width: 1fr; min-width: 40; background: {BLACK}; }}
    .panel-head {{ height: 1; background: #06141c; }}
    .panel-title {{ width: 1fr; padding: 0 1; color: {SKY}; text-style: bold; }}
    Button.close {{ min-width: 3; width: 3; height: 1; border: none; padding: 0;
                    background: #06141c; color: {RED}; }}
    Button.close:hover {{ background: {RED}; color: {BLACK}; }}
    WorkspaceTree {{ background: {BLACK}; color: {WHITE}; }}
    WorkspaceTree > .directory-tree--folder {{ color: {SKY}; text-style: bold; }}
    WorkspaceTree > .directory-tree--file {{ color: {WHITE}; }}
    WorkspaceTree > .directory-tree--extension {{ color: {GREY}; }}
    WorkspaceTree:focus > .tree--cursor {{ background: #0b2a3a; color: {WHITE}; }}
    #viewer-scroll {{ background: {BLACK}; }}
    #viewer-body {{ background: {BLACK}; width: auto; min-width: 100%; }}
    #convo {{ height: 1fr; padding: 1 2 0 2; background: {BLACK}; }}
    .entry {{ margin: 0 0 1 0; width: 100%; background: {BLACK}; }}
    #status {{ height: 1; padding: 0 2; color: {GREY}; background: {BLACK}; }}
    #prompt {{ background: {BLACK}; color: {WHITE}; border: tall {SKY}; margin: 0 1; }}
    #prompt:focus {{ border: tall {NEON_CYAN}; }}
    #prompt > .input--placeholder {{ color: #4d5b6b; }}
    Footer {{ background: {BLACK}; }}
    FooterKey {{ background: {BLACK}; }}
    FooterKey .footer-key--key {{ color: {NEON_CYAN}; background: {BLACK}; text-style: bold; }}
    FooterKey .footer-key--description {{ color: {GREY}; background: {BLACK}; }}
    ConfirmScreen, ModelPicker, ToolPicker {{ align: center middle; background: #000000aa; }}
    SplashScreen {{ align: center middle; background: {BLACK}; }}
    IntroScreen {{ align: center middle; background: {BLACK}; }}
    #intro {{ width: auto; height: auto; background: {BLACK}; }}
    #intro-logo {{ width: auto; height: auto; background: {BLACK}; }}
    #intro-sub {{ width: 100%; margin-top: 1; text-align: center; background: {BLACK}; }}
    #splash {{ width: auto; height: auto; background: {BLACK}; }}
    #splash-logo {{ width: auto; height: auto; background: {BLACK}; }}
    #splash-sub {{ margin: 1 0; background: {BLACK}; }}
    #splash-menu {{ width: 84; max-width: 100%; height: 7; max-height: 7; background: {BLACK}; }}
    #splash-menu:focus {{ background: {BLACK}; }}
    #splash-menu > .option-list--option-highlighted {{ background: #6b3300; color: {WHITE}; text-style: bold; }}
    #splash-menu:focus > .option-list--option-highlighted {{ background: #6b3300; color: {WHITE}; }}
    #splash-hint {{ margin-top: 1; background: {BLACK}; }}
    #dialog {{ width: 70; max-width: 90%; height: auto; max-height: 80%; padding: 1 2;
               background: {BLACK}; border: heavy {NEON_CYAN}; }}
    #dialog-q {{ margin-bottom: 1; }}
    #dialog-btns {{ height: 3; align: center middle; }}
    #dialog-btns Button {{ margin: 0 2; }}
    OptionList {{ background: {BLACK}; height: auto; max-height: 20; border: none; }}
    """

    BINDINGS = [
        Binding("ctrl+t", "next_mode", "Mode", priority=True),
        Binding("ctrl+b", "toggle_files", "Fichiers", priority=True),
        Binding("ctrl+o", "toggle_viewer", "Aperçu", priority=True),
        Binding("ctrl+p", "pick_model", "Moteur", priority=True),
        Binding("ctrl+n", "new_chat", "Nouveau", priority=True),
        Binding("f2", "pick_tool", "Outils", priority=True),
        Binding("escape", "stop", "Arrêter"),
        Binding("ctrl+q", "quit", "Quitter", priority=True),
    ]

    def __init__(self, config: Config | None = None, client_factory=OllamaClient,
                 resolve_models: bool = True, splash: bool = False) -> None:
        super().__init__()
        self.splash = splash
        self.base_config = config or Config()
        self.client_factory = client_factory
        self.resolve_models = resolve_models
        self.modes: dict[str, Mode] = {}
        self.current: Mode
        self.busy = False
        self._quitting = False
        self._stop = threading.Event()
        self._activity = ""
        self._tick = 0
        self._busy_since = 0.0
        # TILEX_SANS_ANIMATION=1 coupe les animations (écran lent, SSH, etc.)
        self._animated = not os.environ.get("TILEX_SANS_ANIMATION")
        self._intro_seen: set[str] = set()   # outils dont l'animation d'entrée a déjà joué
        self._sudo_timer = None         # garde la session sudo ouverte tant que l'interface tourne
        self._build_modes()
        self.current = self.modes["rea"]

    # ------------------------------------------------------------------ construction
    def _build_modes(self) -> None:
        base = self.base_config
        specs = [
            ("rea", "REA", _env_model("TILEX_REA_MODEL", "heretic:latest"),
             _env_model("TILEX_REA_FALLBACK", FALLBACK_REA), "", True),
            ("codex", "Codex", _env_model("TILEX_CODEX_MODEL", "qwen2.5-coder:7b"),
             _env_model("TILEX_CODEX_FALLBACK", FALLBACK_CODEX), CODEX_SYSTEM, False),
            ("chat", "Chat", _env_model("TILEX_CHAT_MODEL", "qwen3-vl:4b"),
             _env_model("TILEX_CHAT_FALLBACK", FALLBACK_CHAT), CHAT_SYSTEM, False),
            # TerminalCodex : l'IA locale choisit et lance les commandes (avec ta confirmation).
            ("terminalcodex", "TerminalCodex", _env_model("TILEX_TERMINAL_MODEL", "qwen3:8b"),
             _env_model("TILEX_TERMINAL_FALLBACK", FALLBACK_REA), terminal_system_prompt(), True),
            # Programme IA outils : l'IA écrit, teste et range des outils dans la bibliothèque.
            ("programmeur", "Programme IA", _env_model("TILEX_PROGRAMMEUR_MODEL", "qwen3:8b"),
             _env_model("TILEX_PROGRAMMEUR_FALLBACK", FALLBACK_CODEX),
             programmeur_system_prompt(), True),
        ]
        for key, label, primary, fallback, system, tools in specs:
            cfg = Config(ollama_host=base.ollama_host, model=primary,
                         vision_model=base.vision_model, workspace=base.workspace)
            client = self.client_factory(cfg)
            mode = Mode(key, label, primary, fallback, system, tools, cfg, client,
                        dict(DEFAULTS))
            if tools:
                schemas = {"terminalcodex": TERMINAL_TOOL_SCHEMAS,
                           "programmeur": PROGRAMMEUR_TOOL_SCHEMAS}.get(key)
                mode.agent = Agent(cfg, client=client, confirm=self._confirm,
                                   options=mode.options,
                                   system_prompt=system or None,
                                   tool_schemas=schemas)
                self._wrap_tools(mode)
            else:
                mode.messages = [{"role": "system", "content": with_memory(system, cfg)}]
            mode.transcript.append(self._welcome(mode))
            self.modes[key] = mode

    @staticmethod
    def _welcome(mode: Mode) -> Entry:
        what = {
            "rea": "agent complet : web, vision, fichiers et commandes",
            "codex": "assistant de programmation",
            "chat": "conversation générale",
            "terminalcodex": ("écris ce que tu veux faire, l'IA locale trouve et lance les "
                              "commandes\n(chaque commande te demande confirmation ; /auto pour "
                              "ne plus demander)"),
            "programmeur": ("décris l'outil que tu veux : l'IA locale l'écrit dans outils/, le "
                            "teste, puis l'ajoute à ta bibliothèque\n(ex : « un outil qui "
                            "sauvegarde mon dossier Documents dans une archive datée »)"),
        }[mode.key]
        where = str(mode.config.workspace)
        home = str(Path.home())
        if where.startswith(home):
            where = "~" + where[len(home):]
        extra = f"\nDossier de travail : {where}" if mode.tools else ""
        return Entry("info", f"{mode.label} — {what}{extra}\n"
                             f"Écris ta demande en bas. /aide pour voir les commandes.")

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static(brand_text(2 * len(BRAND), False), id="brand")   # au repos, sans éclat
            yield Tabs(Tab("REA", id="rea"), Tab("Codex", id="codex"),
                       Tab("Chat", id="chat"), Tab("TerminalCodex", id="terminalcodex"),
                       Tab("Programme IA", id="programmeur"), id="tabs")
        with Horizontal(id="body"):
            with Vertical(id="files"):
                with Horizontal(classes="panel-head"):
                    yield Static("📁 Fichiers", classes="panel-title")
                    yield Button("✕", id="close-files", classes="close")
                yield WorkspaceTree(str(self.base_config.workspace), id="tree")
            with Vertical(id="main"):
                yield VerticalScroll(id="convo")
                yield Static("", id="status")
                yield Input(placeholder="Écris ta demande…  (/aide)", id="prompt")
            with Vertical(id="viewer"):
                with Horizontal(classes="panel-head"):
                    yield Static("📄 Aperçu", id="viewer-title", classes="panel-title")
                    yield Button("✕", id="close-viewer", classes="close")
                with ScrollableContainer(id="viewer-scroll"):
                    yield Static(Text("Clique sur un fichier à gauche pour le voir ici.\n/ouvrir <chemin> marche aussi.", style=GREY), id="viewer-body")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(NOIR)
        self.theme = "lexos-noir"
        try:
            self.chat.anchor()
        except Exception:
            pass
        self._render_transcript()
        self._refresh_status()
        self.query_one("#prompt", Input).focus()
        if self._animated:
            self.set_interval(ANIM_STEP, self._anim_frame)
        if self.resolve_models:
            self._startup()
        if self.splash:
            self.action_home()

    # ------------------------------------------------------------------ accueil
    def action_home(self) -> None:
        """Ouvre le menu de départ (animation TI-LEX puis les choix)."""
        self.push_screen(SplashScreen(animated=self._animated), self._home_choice)

    def _home_choice(self, choice: str | None) -> None:
        prompt = self.query_one("#prompt", Input)
        if choice in self.modes:
            self._go_mode(choice)
        elif choice == "outils":
            self.action_pick_tool()
        elif choice == "cloner":
            prompt.value = "/cloner "
        elif choice == "nouveau":
            prompt.value = "/nouveau "
        elif choice == "quitter":
            self.action_quit()
            return
        prompt.focus()
        prompt.cursor_position = len(prompt.value)

    # ------------------------------------------------------------------ outils créés / projets
    def action_pick_tool(self) -> None:
        try:
            tools = outils.load(self.base_config)
        except outils.OutilError as e:
            self._info(str(e), "error")
            return
        if not tools:
            self._info(outils.describe(self.base_config))
            return

        def chosen(nom: str | None) -> None:
            if nom:
                self._launch_tool(nom)
        self.push_screen(ToolPicker(tools), chosen)

    def _launch_tool(self, nom: str) -> None:
        tool = outils.find(self.base_config, nom)
        if tool is None:
            self._info(f"Aucun outil nommé « {nom} ». /outils pour voir la liste.", "error")
            return
        cmd = tool["commande"]
        try:
            # On rend le terminal à l'outil (il peut être interactif), puis on revient.
            with self.suspend():
                print(f"\n▶ {tool['nom']}  ({cmd})\n", flush=True)
                code = os.system(f"cd {str(self.base_config.workspace)!r} && {cmd}")
                input(f"\n[code {code >> 8 if code > 255 else code}] Entrée pour revenir à LexOS… ")
        except SuspendNotSupported:
            self._run_tool_captured(self.current, tool)
            return
        self._info(f"Outil « {tool['nom']} » terminé.")
        self._reload_tree()

    @work(thread=True, group="outil")
    def _run_tool_captured(self, mode: Mode, tool: dict) -> None:
        entry = self._ui(self._add_entry, mode, Entry("tool", f"{tool['nom']} — {tool['commande']}"))
        code, out = outils.run_captured(self.base_config, tool["commande"])
        if entry is not None:
            self._ui(self._paint, entry, None,
                     summarize_result(out or "(aucune sortie)", max_lines=30) + f"\n[code {code}]")
        self._ui(self._reload_tree)

    @work(thread=True, group="projet")
    def _clone_project(self, mode: Mode, url: str, nom: str) -> None:
        entry = self._ui(self._add_entry, mode, Entry("tool", f"git clone {url}", detail="en cours…"))
        try:
            target = outils.clone(self.base_config, url, nom)
        except outils.OutilError as e:
            if entry is not None:
                self._ui(self._paint, entry, None, "échec")
            self._ui(self._add_entry, mode, Entry("error", str(e)))
            return
        if entry is not None:
            self._ui(self._paint, entry, None, f"cloné dans {target.name}/")
        self._ui(self._project_ready, mode, target, "cloné")

    def _project_ready(self, mode: Mode, target: Path, verb: str) -> None:
        self._add_entry(mode, Entry("info", f"Projet « {target.name} » {verb} dans le dossier de "
                                            f"travail. Demande à REA de travailler dedans "
                                            f"(ex : « regarde le projet {target.name} »)."))
        self._reload_tree()
        for name in ("README.md", "readme.md", "README"):
            if (target / name).is_file():
                self._open_file(target / name)
                break

    # ------------------------------------------------------------------ sudo (une seule fois)
    def _sudo_start(self) -> None:
        """Demande le mot de passe sudo UNE fois, dans le vrai terminal (l'interface se met
        de côté : ni elle ni l'IA ne voient le mot de passe, il n'est écrit nulle part).
        Ensuite la session reste ouverte tant que l'interface tourne."""
        if shutil.which("sudo") is None:
            self._info("sudo n'est pas installé sur ce système.", "error")
            return
        try:
            with self.suspend():
                print("\nMot de passe sudo (une seule fois ; il n'est pas enregistré) :", flush=True)
                ok = subprocess.call(["sudo", "-v"]) == 0
        except SuspendNotSupported:
            self._info("Impossible ici : lance « sudo -v » dans ton terminal avant d'ouvrir ti-lex.",
                       "error")
            return
        if not ok:
            self._info("sudo a refusé (mauvais mot de passe ?). Réessaie avec /sudo.", "error")
            return
        if self._sudo_timer is None:
            self._sudo_timer = self.set_interval(120, self._sudo_keepalive)
        self._info("Session sudo ouverte : TerminalCodex peut installer des outils sans redemander "
                   "le mot de passe (chaque commande sudo te demande quand même de confirmer). "
                   "/sudo off pour la fermer ; elle se ferme aussi quand tu quittes.")

    @work(thread=True, group="sudo")
    def _sudo_keepalive(self) -> None:
        subprocess.run(["sudo", "-n", "-v"], capture_output=True, stdin=subprocess.DEVNULL)

    def _sudo_stop(self) -> None:
        if self._sudo_timer is not None:
            self._sudo_timer.stop()
            self._sudo_timer = None
            subprocess.run(["sudo", "-k"], capture_output=True, stdin=subprocess.DEVNULL)

    # ------------------------------------------------------------------ raccourcis
    @property
    def chat(self) -> VerticalScroll:
        return self.query_one("#convo", VerticalScroll)

    def _ui(self, fn, *args):
        """Appelle `fn` dans le fil de l'interface depuis un fil de travail."""
        if self._quitting:
            return None
        try:
            return self.call_from_thread(fn, *args)
        except Exception:
            return None

    # ------------------------------------------------------------------ transcription
    def _render_entry(self, entry: Entry) -> RenderableType:
        if entry.kind == "user":
            return Text.assemble(("▍ ", f"bold {WHITE}"), (entry.text, WHITE))
        if entry.kind == "ai":
            return render_ai(entry.label, entry.text)
        if entry.kind == "tool":
            parts: list[RenderableType] = [Text.assemble(
                ("🔧 ", GOLD), (entry.text, f"bold {GOLD}"))]
            if entry.detail:
                parts.append(Text(entry.detail, style=GREY))
            return Group(*parts)
        if entry.kind == "error":
            return Text("⚠ " + entry.text, style=f"bold {RED}")
        return Text(entry.text, style=GREY)

    def _mount_entry(self, entry: Entry) -> None:
        widget = Static(self._render_entry(entry), classes="entry")
        entry.widget = widget
        self.chat.mount(widget)

    def _render_transcript(self) -> None:
        for e in self.current.transcript:
            e.widget = None
        self.chat.remove_children()
        for e in self.current.transcript:
            self._mount_entry(e)
        self.chat.scroll_end(animate=False)

    def _add_entry(self, mode: Mode, entry: Entry) -> Entry:
        mode.transcript.append(entry)
        if mode is self.current:
            self._mount_entry(entry)
            self.chat.scroll_end(animate=False)
        return entry

    def _paint(self, entry: Entry, text: str | None = None, detail: str | None = None) -> None:
        if text is not None:
            entry.text = text
        if detail is not None:
            entry.detail = detail
        w = entry.widget
        if w is not None and w.is_attached:
            w.update(self._render_entry(entry))

    def _info(self, text: str, kind: str = "info") -> None:
        self._add_entry(self.current, Entry(kind, text))

    # ------------------------------------------------------------------ état / statut
    def _status_text(self) -> Text:
        m = self.current
        auto = " · AUTO" if (m.agent and m.agent.tools.auto_approve) else ""
        if not self.busy:
            return Text(f"● {m.label} · {m.model}{auto}", style=GREY)
        secs = int(time.monotonic() - self._busy_since)
        color = NEON_CYCLE[(self._tick // 3) % len(NEON_CYCLE)]
        t = Text(f"● {m.label} · {m.model}   ", style=SKY)
        t.append(spinner_frame(self._tick) + " ", style=f"bold {color}")
        t.append(f"{self._activity or 'je réfléchis…'}  {secs} s  (Échap = arrêter)", style=SKY)
        return t

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self._status_text())

    def _anim_frame(self) -> None:
        """Une image d'animation : logo qui brille + indicateur qui tourne."""
        if self._quitting:
            return
        self._tick += 1
        if not self.busy and self._tick % 2:
            return                      # au repos : une image sur deux suffit
        try:
            self.query_one("#brand", Static).update(brand_text(self._tick, self.busy))
            if self.busy:
                self._refresh_status()
        except Exception:
            pass                        # écran en train de changer : on réessaie plus tard

    def _set_activity(self, text: str) -> None:
        self._activity = text
        self._refresh_status()

    # ------------------------------------------------------------------ modes
    @on(Tabs.TabActivated)
    def _tab_changed(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id
        if tab_id and tab_id in self.modes and self.modes[tab_id] is not self.current:
            self.current = self.modes[tab_id]
            self._render_transcript()
            self._refresh_status()
            self.query_one("#prompt", Input).focus()
            if tab_id in INTROS and self.splash and tab_id not in self._intro_seen:
                self._intro_seen.add(tab_id)
                logo, subtitle = INTROS[tab_id]
                self.push_screen(
                    IntroScreen(logo, subtitle, animated=self._animated),
                    lambda _=None: self.query_one("#prompt", Input).focus())

    def _go_mode(self, key: str) -> None:
        self.query_one(Tabs).active = key

    def action_next_mode(self) -> None:
        keys = list(self.modes)
        self._go_mode(keys[(keys.index(self.current.key) + 1) % len(keys)])

    # ------------------------------------------------------------------ panneaux
    def action_toggle_files(self) -> None:
        panel = self.query_one("#files")
        panel.display = not panel.display
        self.query_one("#prompt", Input).focus()

    def action_toggle_viewer(self) -> None:
        panel = self.query_one("#viewer")
        panel.display = not panel.display
        self.query_one("#prompt", Input).focus()

    @on(Button.Pressed, "#close-files")
    def _close_files(self) -> None:
        self.query_one("#files").display = False
        self.query_one("#prompt", Input).focus()

    @on(Button.Pressed, "#close-viewer")
    def _close_viewer(self) -> None:
        self.query_one("#viewer").display = False
        self.query_one("#prompt", Input).focus()

    @on(DirectoryTree.FileSelected)
    def _file_clicked(self, event: DirectoryTree.FileSelected) -> None:
        self._open_file(Path(event.path))

    def _open_file(self, path: Path) -> None:
        root = self.base_config.workspace.resolve()
        try:
            rel = str(path.resolve().relative_to(root))
        except ValueError:
            rel = path.name
        title = self.query_one("#viewer-title", Static)
        body = self.query_one("#viewer-body", Static)
        title.update(Text(f"📄 {rel}", style=f"bold {SKY}"))
        content: RenderableType
        try:
            data = path.read_bytes()[:MAX_VIEW_BYTES + 1]
        except OSError as e:
            content = Text(f"Impossible de lire ce fichier : {e}", style=RED)
        else:
            if b"\0" in data[:4000]:
                content = Text("(fichier binaire — pas d'aperçu)", style=GREY)
            else:
                code = data[:MAX_VIEW_BYTES].decode("utf-8", errors="replace")
                lexer = Syntax.guess_lexer(str(path), code)
                content = Syntax(code, lexer, theme=NEON_THEME, line_numbers=True,
                                 background_color=BLACK, word_wrap=False)
                if len(data) > MAX_VIEW_BYTES:
                    content = Group(content, Text("… (fichier tronqué)", style=GREY))
        body.update(content)
        self.query_one("#viewer").display = True
        self.query_one("#viewer-scroll", ScrollableContainer).scroll_home(animate=False)

    def _reload_tree(self) -> None:
        self.query_one(WorkspaceTree).reload()

    # ------------------------------------------------------------------ moteur (modèle)
    def action_pick_model(self) -> None:
        self._load_models_for_picker()

    @work(thread=True, group="models")
    def _load_models_for_picker(self) -> None:
        mode = self.current
        try:
            names = mode.client.list_models()
        except OllamaError as e:
            self._ui(self._info, str(e), "error")
            return
        if not names:
            self._ui(self._info, "Aucun modèle dans Ollama (ollama pull <nom>).", "error")
            return
        self._ui(self._show_picker, mode, names)

    def _show_picker(self, mode: Mode, names: list[str]) -> None:
        def chosen(name: str | None) -> None:
            if name:
                self._set_model(mode, name)
        self.push_screen(ModelPicker(names, mode.model, f"Moteur pour {mode.label}"), chosen)

    def _set_model(self, mode: Mode, name: str) -> None:
        mode.config.model = name
        self._info(f"Moteur de {mode.label} : {name}")
        self._refresh_status()

    @work(thread=True, group="startup")
    def _startup(self) -> None:
        """Vérifie que les modèles demandés existent ; sinon prend un modèle de repli."""
        try:
            available = self.modes["rea"].client.list_models()
        except OllamaError as e:
            self._ui(self._info, f"{e}\nLance Ollama (ollama serve) puis relance, "
                                 f"ou tape /model pour réessayer.", "error")
            return
        for mode in self.modes.values():
            name, note = pick_model(available, mode.primary, mode.fallback)
            if name != mode.model:
                self._ui(self._swap_model, mode, name)
            if note:
                self._ui(self._add_entry, mode, Entry("info", note))
        self._ui(self._refresh_status)

    def _swap_model(self, mode: Mode, name: str) -> None:
        mode.config.model = name
        self._refresh_status()

    # ------------------------------------------------------------------ confirmation
    def _confirm(self, question: str) -> bool:
        """Appelée depuis le fil de REA : affiche une fenêtre et attend la réponse."""
        done = threading.Event()
        box: list[bool] = []

        def answer(value: bool | None) -> None:
            box.append(bool(value))
            done.set()

        self._ui(self.push_screen, ConfirmScreen(question), answer)
        while not done.wait(0.2):
            if self._quitting:
                return False
        return box[0] if box else False

    # ------------------------------------------------------------------ outils de REA
    def _wrap_tools(self, mode: Mode) -> None:
        toolbox = mode.agent.tools  # type: ignore[union-attr]
        original = toolbox.call

        def call(name: str, arguments: dict) -> str:
            if self._stop.is_set():
                raise _Stopped()
            entry = self._ui(self._add_entry, mode, Entry("tool", fmt_call(name, arguments)))
            self._ui(self._set_activity, f"🔧 {name}…")
            result = original(name, arguments)
            if entry is not None:
                self._ui(self._finish_tool, mode, entry, name, arguments, result)
            return result

        toolbox.call = call  # type: ignore[method-assign]

    def _finish_tool(self, mode: Mode, entry: Entry, name: str, args: dict, result: str) -> None:
        self._paint(entry, detail=summarize_result(result))
        if name in {"write_file", "run_command", "run_shell", "run_library_tool", "save_tool"}:
            self._reload_tree()
        if name in {"write_file", "read_file"} and not result.startswith("Erreur"):
            try:
                target = resolve_workspace_path(mode.config, str(args.get("path", "")))
            except ToolError:
                return
            if target.is_file():
                self._open_file(target)

    # ------------------------------------------------------------------ saisie
    @on(Input.Submitted, "#prompt")
    def _submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/") and self._command(text):
            return
        if self.busy:
            self._info("Une réponse est en cours — attends la fin (ou Échap pour l'arrêter).",
                       "error")
            return
        mode = self.current
        self._add_entry(mode, Entry("user", text))
        self.busy = True
        self._busy_since = time.monotonic()
        self._stop.clear()
        self._activity = ""
        self._refresh_status()
        self._run_turn(mode, text)

    def action_stop(self) -> None:
        if self.busy:
            self._stop.set()
            self._set_activity("arrêt demandé…")

    def action_new_chat(self) -> None:
        if self.busy:
            self._info("Impossible pendant une réponse — Échap pour l'arrêter d'abord.", "error")
            return
        self._reset(self.current)

    def _reset(self, mode: Mode) -> None:
        if mode.agent:
            mode.agent.reset()
        else:
            mode.messages = [{"role": "system", "content": with_memory(mode.system, mode.config)}]
        mode.transcript = [self._welcome(mode), Entry("info", "Conversation effacée.")]
        if mode is self.current:
            self._render_transcript()

    def _command(self, text: str) -> bool:
        """Commandes tapées. Retourne True si la ligne était une commande."""
        word, _, arg = text.partition(" ")
        arg = arg.strip()
        mode = self.current
        if word in {"/rea", "/codex", "/chat", "/terminalcodex"}:
            self._go_mode(word[1:])
        elif word in {"/programme", "/programmeur"}:
            self._go_mode("programmeur")
        elif word == "/aide":
            self._info(AIDE)
        elif word in {"/quit", "/exit", "/menu"}:
            self.exit()
        elif word == "/reset":
            self.action_new_chat()
        elif word == "/fichiers":
            self.action_toggle_files()
        elif word == "/apercu":
            self.action_toggle_viewer()
        elif word == "/ouvrir":
            if not arg:
                self._info("Usage : /ouvrir <chemin dans le dossier de travail>", "error")
            else:
                try:
                    target = resolve_workspace_path(mode.config, arg)
                except ToolError as e:
                    self._info(str(e), "error")
                else:
                    if target.is_file():
                        self._open_file(target)
                    else:
                        self._info(f"Fichier introuvable : {arg}", "error")
        elif word == "/auto":
            key = mode.key if mode.key in {"terminalcodex", "programmeur"} else "terminalcodex"
            tc = self.modes[key]
            box = tc.agent.tools  # type: ignore[union-attr]
            box.auto_approve = not box.auto_approve
            self._info(f"{tc.label} : mode AUTO activé — les commandes partent sans demander "
                       "(sauf les commandes dangereuses : sudo, rm -rf /, formatage…). "
                       "/auto pour l'arrêter." if box.auto_approve
                       else f"{tc.label} : mode AUTO arrêté — chaque commande redemande confirmation.")
            self._refresh_status()
        elif word == "/sudo":
            if arg in {"off", "stop", "fin"}:
                self._sudo_stop()
                self._info("Session sudo fermée : le mot de passe sera redemandé (/sudo).")
            else:
                self._sudo_start()
        elif word == "/accueil":
            self.action_home()
        elif word == "/outils":
            if arg:
                self._launch_tool(arg)
            else:
                self.action_pick_tool()
        elif word == "/outil":
            if arg:
                self._launch_tool(arg)
            else:
                self._info(outils.describe(self.base_config))
        elif word == "/ajouter-outil":
            nom, sep, cmd = arg.partition("=")
            try:
                if not sep:
                    raise outils.OutilError("Usage : /ajouter-outil <nom> = <commande>")
                self._info(outils.add(self.base_config, nom, cmd))
            except outils.OutilError as e:
                self._info(str(e), "error")
        elif word == "/retirer-outil":
            try:
                self._info(outils.remove(self.base_config, arg))
            except outils.OutilError as e:
                self._info(str(e), "error")
        elif word == "/cloner":
            parts = arg.split()
            if not 1 <= len(parts) <= 2:
                self._info("Usage : /cloner <proprio/depot ou adresse> [dossier]", "error")
            else:
                self._clone_project(mode, parts[0], parts[1] if len(parts) == 2 else "")
        elif word == "/nouveau":
            try:
                self._project_ready(mode, outils.new_project(self.base_config, arg), "créé")
            except outils.OutilError as e:
                self._info(str(e), "error")
        elif word == "/retenir":
            self._info(remember(mode.config, arg))
        elif word == "/model":
            if arg:
                self._set_model(mode, arg)
            else:
                self.action_pick_model()
        elif word == "/params":
            self._info(describe(mode.options))
        elif word in {"/temp", "/param"}:
            parts = (["temperature", arg] if word == "/temp" else arg.split(maxsplit=1))
            if len(parts) != 2:
                self._info("Usage : /param <nom> <valeur>  (ex : /temp 0.9)", "error")
            else:
                try:
                    self._info(set_param(mode.options, parts[0], parts[1]))
                except ValueError as e:
                    self._info(str(e), "error")
        else:
            return False
        return True

    # ------------------------------------------------------------------ un tour de parole
    @work(thread=True, group="gen")
    def _run_turn(self, mode: Mode, text: str) -> None:
        try:
            if mode.agent:
                self._turn_agent(mode, text)
            else:
                self._turn_chat(mode, text)
        except _Stopped:
            self._ui(self._info, "Arrêté.")
        except OllamaError as e:
            self._ui(self._add_entry, mode, Entry("error", str(e)))
        except Exception as e:  # on ne plante jamais l'interface à cause d'un tour
            self._ui(self._add_entry, mode,
                     Entry("error", f"Erreur inattendue ({type(e).__name__}) : {e}"))
        finally:
            self._ui(self._turn_done)

    def _turn_done(self) -> None:
        self.busy = False
        self._activity = ""
        self._refresh_status()

    def _turn_chat(self, mode: Mode, text: str) -> None:
        mode.messages.append({"role": "user", "content": text})
        entry = self._ui(self._add_entry, mode, Entry("ai", "", label=mode.label))
        self._ui(self._set_activity, "réponse en cours…")
        buf, last, interrupted = "", 0.0, False
        try:
            for chunk in mode.client.chat_stream(mode.messages, options=mode.options):
                buf += chunk
                now = time.monotonic()
                if entry is not None and now - last > 0.06:
                    self._ui(self._paint, entry, buf)
                    last = now
                if self._stop.is_set():
                    interrupted = True
                    break
        except OllamaError:
            mode.messages.pop()
            if entry is not None:
                self._ui(self._drop_entry, mode, entry)
            raise
        visible, _ = split_think(buf)
        visible = visible.strip()
        shown = buf if buf.strip() else "(réponse vide)"
        if interrupted:
            shown += "\n\n*(interrompu)*"
        if entry is not None:
            self._ui(self._paint, entry, shown)
        mode.messages.append({"role": "assistant", "content": visible})

    def _drop_entry(self, mode: Mode, entry: Entry) -> None:
        if entry in mode.transcript:
            mode.transcript.remove(entry)
        if entry.widget is not None:
            entry.widget.remove()

    def _turn_agent(self, mode: Mode, text: str) -> None:
        agent = mode.agent
        assert agent is not None
        snapshot = list(agent.messages)
        self._ui(self._set_activity, "je réfléchis…")
        try:
            answer = agent.run(text)
        except _Stopped:
            agent.messages[:] = snapshot  # pas d'appel d'outil laissé en suspens
            raise
        self._type_out(mode, answer or "(réponse vide)")

    def _type_out(self, mode: Mode, text: str) -> None:
        """Écriture fluide : la réponse apparaît progressivement, comme si l'IA l'écrivait.
        (Échap l'affiche d'un coup ; TILEX_SANS_ANIMATION=1 coupe l'effet.)"""
        entry = self._ui(self._add_entry, mode, Entry("ai", "", label=mode.label))
        if entry is None:
            return
        if self._animated and len(text) > 1:
            step = max(2, len(text) // int(TYPE_SECONDS / 0.03))
            for end in range(step, len(text), step):
                if self._stop.is_set() or self._quitting:
                    break
                self._ui(self._paint, entry, text[:end])
                time.sleep(0.03)
        self._ui(self._paint, entry, text)

    # ------------------------------------------------------------------ fermeture
    def action_quit(self) -> None:
        self._sudo_stop()
        self._quitting = True
        self._stop.set()
        self.exit()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lexos-tui",
                                description="Interface LexOS : REA, Codex et Chat (terminal).")
    p.add_argument("--workspace", help="Dossier de travail (défaut : ./workspace)")
    args = p.parse_args(argv)
    config = Config()
    if args.workspace:
        config.workspace = Path(args.workspace).expanduser().resolve()
        config.workspace.mkdir(parents=True, exist_ok=True)
    LexosApp(config, splash=True).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
