"""Interface plein écran LexOS : REA, Codex et Chat dans la même fenêtre.

Même écran pour les trois modes ; seul le moteur change (modèle, outils,
consigne). Heretic reste dans le menu `lexos-ia`, inchangé.

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
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, DirectoryTree, Footer, Input, OptionList, Static, Tab, Tabs
from textual.widgets.option_list import Option

from .agent import Agent
from .config import Config
from .launcher import (CHAT_SYSTEM, CODEX_SYSTEM, FALLBACK_CHAT, FALLBACK_CODEX,
                       FALLBACK_REA, _env_model, _has_model)
from .memory import remember, with_memory
from .ollama_client import OllamaClient, OllamaError
from .params import DEFAULTS, describe, set_param
from .tools import ToolError, resolve_workspace_path

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
    """Le logo LEXOS. Au repos, un éclat néon glisse doucement d'une lettre à
    l'autre, puis fait une pause. Quand le modèle travaille, les lettres
    changent de couleur néon."""
    out = Text()
    glint = (tick // 2) % (len(BRAND) + 6)
    for i, ch in enumerate(BRAND):
        if busy:
            out.append(ch, style=f"bold {NEON_CYCLE[(tick + i) % len(NEON_CYCLE)]}")
        elif i == glint:
            out.append(ch, style=f"bold {NEON_CYAN}")
        elif i == glint - 1:
            out.append(ch, style=f"bold {SKY}")
        else:
            out.append(ch, style=f"bold {WHITE}")
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
    parts: list[RenderableType] = [Text(f"{label} ▸", style=f"bold {SKY}")]
    for kind, body, lang in split_blocks(visible):
        if kind == "text":
            parts.append(Markdown(body, style=SKY, inline_code_theme=NeonStyle))
        else:
            parts.append(code_panel(body, lang))
    if thinking:
        parts.append(Text("💭 réflexion…", style=f"italic {GREY}"))
    elif len(parts) == 1:
        parts.append(Text("…", style=GREY))
    return Group(*parts)


def fmt_call(name: str, args: dict) -> str:
    """Résumé lisible d'un appel d'outil."""
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
Modes        Ctrl+T (suivant) · /rea · /codex · /chat · clic sur l'onglet
Panneaux     Ctrl+B fichiers · Ctrl+O aperçu · /fichiers · /apercu · clic sur ✕
Moteur       Ctrl+P ou /model (liste) · /model <nom>
Fichiers     clic sur un fichier = ouvre l'aperçu · /ouvrir <chemin>
Conversation Ctrl+N ou /reset · Échap arrête la réponse · /retenir <texte>
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
    ConfirmScreen, ModelPicker {{ align: center middle; background: #000000aa; }}
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
        Binding("escape", "stop", "Arrêter"),
        Binding("ctrl+q", "quit", "Quitter", priority=True),
    ]

    def __init__(self, config: Config | None = None, client_factory=OllamaClient,
                 resolve_models: bool = True) -> None:
        super().__init__()
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
        ]
        for key, label, primary, fallback, system, tools in specs:
            cfg = Config(ollama_host=base.ollama_host, model=primary,
                         vision_model=base.vision_model, workspace=base.workspace)
            client = self.client_factory(cfg)
            mode = Mode(key, label, primary, fallback, system, tools, cfg, client,
                        dict(DEFAULTS))
            if tools:
                mode.agent = Agent(cfg, client=client, confirm=self._confirm,
                                   options=mode.options)
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
            yield Static(Text("LEXOS", style=f"bold {WHITE}"), id="brand")
            yield Tabs(Tab("REA", id="rea"), Tab("Codex", id="codex"),
                       Tab("Chat", id="chat"), id="tabs")
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
                ("🔧 ", NEON_YELLOW), (entry.text, f"bold {NEON_YELLOW}"))]
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
        if not self.busy:
            return Text(f"● {m.label} · {m.model}", style=GREY)
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
        if name in {"write_file", "run_command"}:
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
        if word in {"/rea", "/codex", "/chat"}:
            self._go_mode(word[1:])
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
        self._ui(self._add_entry, mode,
                 Entry("ai", answer or "(réponse vide)", label=mode.label))

    # ------------------------------------------------------------------ fermeture
    def action_quit(self) -> None:
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
    LexosApp(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
