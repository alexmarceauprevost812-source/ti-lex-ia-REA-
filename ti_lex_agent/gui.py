"""Interface graphique LexOS Pro : une vraie fenêtre d'application.

Écran d'accueil avec les 4 modes AU CENTRE (Chat, Codex, REA, Heretic), puis
un écran de conversation par mode. REA est le vrai agent complet (web, vision,
fichiers, commandes) ; Heretic peut aussi décensurer un modèle via l'outil
officiel Heretic. Thème orange/noir LexOS.

Choix de Tkinter : il fait partie de la bibliothèque standard de Python, donc
rien de lourd à installer sur la clé USB (aucun lien symbolique, contrairement
à un gros paquet), et ça marche pareil sur Linux et Windows. La seule exigence
sur Linux est le paquet système « python3-tk » (souvent déjà présent).

Les appels au modèle tournent dans un fil séparé pour que la fenêtre ne gèle
jamais ; les réponses reviennent à l'interface par une file.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from .agent import Agent
from .config import Config
from .launcher import (
    CHAT_SYSTEM,
    CODEX_SYSTEM,
    FALLBACK_CHAT,
    FALLBACK_CODEX,
    FALLBACK_REA,
    HERETIC_SYSTEM,
    _env_model,
    _has_model,
)
from .memory import load_memory, memory_path, remember, with_memory
from .modelops import (
    ModelOpsError,
    copy_model,
    create_variant,
    delete_model,
    import_to_ollama,
    pull_model,
    run_heretic,
    show_model,
)
from .ollama_client import OllamaClient, OllamaError
from .params import DEFAULTS, PARAMS, set_param
from .tools import IMAGE_EXTENSIONS, Toolbox

# Couleurs du thème LexOS.
BG = "#0b0b0d"
PANEL = "#15151b"
EDGE = "#2a2a33"
FG = "#e7e7ea"
MUTED = "#8a8a93"
ORANGE = "#ff8a1e"
ORANGE_DK = "#1a1205"
GREEN = "#4bd07a"
BLUE = "#5fb0ff"
RED = "#ff5f56"

CODEX_TERM_SYSTEM = (
    "Tu es Codex-Terminal, l'assistant shell de Ti-Lex. Tu aides à écrire et à "
    "lancer des commandes et des fonctions dans le terminal, dans le dossier de "
    "travail. Utilise l'outil run_command pour exécuter, et list_files/read_file/"
    "write_file pour les fichiers. Avant une commande qui modifie ou supprime, "
    "explique en une ligne ce qu'elle fait. Montre la commande exacte, lance-la, "
    "puis résume le résultat. Ne prétends jamais avoir exécuté quelque chose que "
    "tu n'as pas lancé. Préfère des commandes simples et sûres."
)

# L'agent complet sert à REA et à Codex-Terminal (tous deux utilisent des outils).
AGENT_MODES = {"rea", "codexterm"}

# (clé, titre, sous-titre, prompt système, (env, défaut principal), (env, repli))
MODES = {
    "chat": ("Chat", "conversation générale", CHAT_SYSTEM,
             ("TILEX_CHAT_MODEL", "qwen3:8b"), ("TILEX_CHAT_FALLBACK", FALLBACK_CHAT)),
    "codex": ("Codex", "assistant de code", CODEX_SYSTEM,
              ("TILEX_CODEX_MODEL", "qwen2.5-coder:7b"), ("TILEX_CODEX_FALLBACK", FALLBACK_CODEX)),
    "codexterm": ("Codex-Terminal", "aide et lance des commandes shell", CODEX_TERM_SYSTEM,
                  ("TILEX_CODEX_MODEL", "qwen2.5-coder:7b"), ("TILEX_CODEX_FALLBACK", FALLBACK_CODEX)),
    "rea": ("REA", "agent complet — web, vision, fichiers", None,
            ("TILEX_REA_MODEL", "heretic:latest"), ("TILEX_REA_FALLBACK", FALLBACK_REA)),
    "heretic": ("Heretic", "chat direct, sans filtre", HERETIC_SYSTEM,
                ("TILEX_HERETIC_MODEL", "heretic:latest"), ("TILEX_CHAT_FALLBACK", FALLBACK_CHAT)),
}


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Dessine un rectangle à coins arrondis sur un Canvas (polygone lissé)."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class RoundButton:
    """Un bouton à coins arrondis dessiné sur un Canvas (Tkinter n'arrondit pas
    les vrais boutons). Gère le survol, l'activation/désactivation et le texte."""

    def __init__(self, tk, parent, text, command, w, h, fill, fg, font, active, radius=14):
        self.cv = tk.Canvas(parent, width=w, height=h, bg=parent["bg"],
                            highlightthickness=0, cursor="hand2")
        self.fill, self.active, self.fg = fill, active, fg
        self.command = command
        self.enabled = True
        self.rect = round_rect(self.cv, 1, 1, w - 1, h - 1, radius, fill=fill, outline=fill)
        self.label = self.cv.create_text(w // 2, h // 2, text=text, fill=fg, font=font)
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<Enter>", lambda _e: self.enabled and self.cv.itemconfig(
            self.rect, fill=self.active, outline=self.active))
        self.cv.bind("<Leave>", lambda _e: self.cv.itemconfig(
            self.rect, fill=self.fill if self.enabled else "#333", outline=self.fill if self.enabled else "#333"))

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_text(self, text):
        self.cv.itemconfig(self.label, text=text)

    def set_enabled(self, on):
        self.enabled = on
        c = self.fill if on else "#333"
        self.cv.itemconfig(self.rect, fill=c, outline=c)

    def pack(self, **kw):
        self.cv.pack(**kw)
        return self


def choose_model(available: list[str], primary: str, fallback: str) -> tuple[str | None, str]:
    """Comme resolve_model du menu texte, mais retourne (modèle, note) au lieu
    d'imprimer — pratique pour afficher la note dans la fenêtre."""
    if not available:
        return None, "Aucun modèle installé dans Ollama."
    if _has_model(available, primary):
        return primary, ""
    if _has_model(available, fallback):
        return fallback, f"« {primary} » absent — repli sur « {fallback} »."
    chosen = available[0]
    return chosen, f"« {primary} » et « {fallback} » absents — utilisation de « {chosen} »."


class LexOSApp:
    def __init__(self, config: Config | None = None):
        import tkinter as tk
        from tkinter import filedialog, font, messagebox, simpledialog

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.config = config or Config()
        self.client = OllamaClient(self.config)
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.mode_key = "chat"
        self.model: str | None = None
        self.messages: list[dict] = []
        self.agent: Agent | None = None
        # Réglages de génération (température, etc.), partagés par tous les modes.
        self.options: dict = dict(DEFAULTS)

        self.root = tk.Tk()
        self.root.title("LexOS Pro — IA locale")
        self.root.minsize(680, 500)
        self.root.configure(bg=BG)
        # Ouvre la fenêtre CENTRÉE sur l'écran (au lieu du coin haut-gauche).
        win_w, win_h = 960, 660
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (screen_h - win_h) // 2)
        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

        fam = font.nametofont("TkFixedFont").actual("family")
        self.f_body = font.Font(family=fam, size=11)
        self.f_bold = font.Font(family=fam, size=11, weight="bold")
        self.f_small = font.Font(family=fam, size=9)
        self.f_logo = font.Font(family=fam, size=34, weight="bold")
        self.f_mode = font.Font(family=fam, size=16, weight="bold")
        self.f_rain = font.Font(family=fam, size=13)
        self._rain_cols: list[int] = []
        self._rain_chars = "01010110ABCDEF0123456789ﾊﾐｦｯ"

        self.home = tk.Frame(self.root, bg=BG)
        self.chat = tk.Frame(self.root, bg=BG)
        self._build_home()
        self._build_chat()
        self._show_home()
        self.root.after(100, self._drain_queue)
        self.root.after(300, self._matrix_tick)

    # ---- écran d'accueil (choix au centre) ------------------------------
    def _build_home(self) -> None:
        tk = self.tk
        # Fond « pluie matrix » : une toile qui remplit l'accueil, DERRIÈRE le
        # menu (créée avant « center », donc dessous dans l'ordre d'empilement).
        self.rain = tk.Canvas(self.home, bg=BG, highlightthickness=0)
        self.rain.place(x=0, y=0, relwidth=1, relheight=1)

        # Un conteneur centré verticalement et horizontalement, par-dessus la toile.
        center = tk.Frame(self.home, bg=BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        # Mascotte TI-LEX (personnage à capuche). Encodée dans _assets.py pour
        # voyager avec la clé ; si le Tk est trop vieux pour le PNG, on l'ignore.
        self.capuche_img = None
        try:
            from . import _assets
            self.capuche_img = tk.PhotoImage(data=_assets.CAPUCHE_PNG_B64)
            tk.Label(center, image=self.capuche_img, bg=BG).pack(pady=(0, 10))
        except Exception:
            self.capuche_img = None

        tk.Label(center, text="LexOS Pro", bg=BG, fg=ORANGE, font=self.f_logo).pack()
        tk.Label(center, text="I A   L O C A L E   ·   O P E N   S O U R C E",
                 bg=BG, fg=MUTED, font=self.f_small).pack(pady=(2, 26))

        cardw, cardh, rad = 384, 56, 16
        for key, (title, sub, *_r) in MODES.items():
            cv = tk.Canvas(center, width=cardw, height=cardh, bg=BG,
                           highlightthickness=0, cursor="hand2")
            cv.pack(pady=4)
            rect = round_rect(cv, 2, 2, cardw - 2, cardh - 2, rad, fill=PANEL, outline=EDGE, width=1)
            cv.create_text(20, 21, text=title, anchor="w", fill=ORANGE, font=self.f_mode)
            cv.create_text(20, 40, text=sub, anchor="w", fill=MUTED, font=self.f_small)
            cv.bind("<Button-1>", lambda _e, k=key: self._open_mode(k))
            cv.bind("<Enter>", lambda _e, c=cv, r=rect: c.itemconfig(r, outline=ORANGE, width=2))
            cv.bind("<Leave>", lambda _e, c=cv, r=rect: c.itemconfig(r, outline=EDGE, width=1))

        tk.Button(center, text="⚙ Gérer les modèles (décensurer, créer, importer…)", bg=BG, fg=BLUE,
                  activebackground=BG, activeforeground=BLUE, bd=0, font=self.f_small,
                  cursor="hand2", command=self._models_manager).pack(pady=(20, 2))
        tk.Button(center, text="Quitter", bg=BG, fg=MUTED, activebackground=BG,
                  activeforeground=RED, bd=0, font=self.f_small, cursor="hand2",
                  command=self.root.destroy).pack()

    # ---- écran de conversation ------------------------------------------
    def _build_chat(self) -> None:
        tk = self.tk
        top = tk.Frame(self.chat, bg=PANEL)
        top.pack(fill="x")
        tk.Button(top, text="‹ Menu", bg=PANEL, fg=ORANGE, activebackground=EDGE,
                  activeforeground=ORANGE, bd=0, font=self.f_bold, cursor="hand2",
                  command=self._show_home).pack(side="left", padx=12, pady=8)
        self.header = tk.Label(top, text="", bg=PANEL, fg=FG, font=self.f_bold)
        self.header.pack(side="left", pady=8)
        tk.Button(top, text="Image", bg=PANEL, fg=BLUE, activebackground=EDGE,
                  activeforeground=BLUE, bd=0, font=self.f_body, cursor="hand2",
                  command=self._attach_image).pack(side="right", padx=8)
        tk.Button(top, text="Écran", bg=PANEL, fg=BLUE, activebackground=EDGE,
                  activeforeground=BLUE, bd=0, font=self.f_body, cursor="hand2",
                  command=self._capture_screen).pack(side="right", padx=8)
        # Accès web dans TOUS les modes (Chat, Codex, Heretic aussi), pas que REA.
        tk.Button(top, text="🌐 Web", bg=PANEL, fg=BLUE, activebackground=EDGE,
                  activeforeground=BLUE, bd=0, font=self.f_body, cursor="hand2",
                  command=self._web_search).pack(side="right", padx=8)
        tk.Button(top, text="Effacer", bg=PANEL, fg=MUTED, activebackground=EDGE,
                  activeforeground=FG, bd=0, font=self.f_body, cursor="hand2",
                  command=lambda: self._reset_conversation(True)).pack(side="right", padx=8)
        # Le « cerveau » partagé : faits mémorisés (/retenir) + erreurs apprises.
        tk.Button(top, text="🧠 Cerveau", bg=PANEL, fg=BLUE, activebackground=EDGE,
                  activeforeground=BLUE, bd=0, font=self.f_body, cursor="hand2",
                  command=self._show_brain).pack(side="right", padx=8)
        # Réglages de génération (température, top_p, …) pour des réponses + directes.
        tk.Button(top, text="🎚 Réglages", bg=PANEL, fg=ORANGE, activebackground=EDGE,
                  activeforeground=ORANGE, bd=0, font=self.f_body, cursor="hand2",
                  command=self._params_panel).pack(side="right", padx=8)
        # Gestionnaire de modèles — visible seulement en mode Heretic.
        self.models_btn = tk.Button(top, text="⚙ Modèles", bg=PANEL, fg=ORANGE,
                                     activebackground=EDGE, activeforeground=ORANGE, bd=0,
                                     font=self.f_bold, cursor="hand2", command=self._models_manager)
        # Choix du dossier de projet — visible pour REA et Codex-Terminal, pour
        # que l'agent travaille sur de VRAIS fichiers de projet.
        self.project_btn = tk.Button(top, text="📁 Projet", bg=PANEL, fg=GREEN,
                                     activebackground=EDGE, activeforeground=GREEN, bd=0,
                                     font=self.f_body, cursor="hand2", command=self._choose_project)

        self.view = tk.Text(self.chat, bg=BG, fg=FG, wrap="word", bd=0, padx=16, pady=10,
                            font=self.f_body, insertbackground=FG, state="disabled",
                            spacing1=2, spacing3=6)
        self.view.pack(fill="both", expand=True)
        self.view.tag_configure("you", foreground=GREEN, font=self.f_bold)
        self.view.tag_configure("ai", foreground=ORANGE, font=self.f_bold)
        self.view.tag_configure("body", foreground=FG)
        self.view.tag_configure("tool", foreground=MUTED, font=self.f_small)
        self.view.tag_configure("err", foreground=RED)

        bottom = tk.Frame(self.chat, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        self.entry = tk.Text(bottom, bg=PANEL, fg=FG, height=2, wrap="word", bd=0,
                             insertbackground=ORANGE, font=self.f_body, padx=10, pady=8)
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry.bind("<Return>", self._on_return)
        self.send_btn = RoundButton(tk, bottom, "Envoyer", self._send, 104, 46,
                                    ORANGE, ORANGE_DK, self.f_bold, GREEN, radius=14)
        self.send_btn.pack(side="right", padx=(8, 0))

        self.status = tk.Label(self.chat, text="", bg=PANEL, fg=MUTED, anchor="w",
                               font=self.f_small, padx=12, pady=4)
        self.status.pack(fill="x", side="bottom")

    def _matrix_tick(self) -> None:
        """Dessine une image de la pluie matrix en fond de l'accueil, puis se
        reprogramme. On ne dessine que quand l'accueil est visible, pour ne pas
        consommer de CPU pendant une conversation."""
        import random
        try:
            visible = self.home.winfo_ismapped()
        except Exception:
            return
        if visible:
            c = self.rain
            w = max(c.winfo_width(), 1)
            h = max(c.winfo_height(), 1)
            cw, rh = 16, 18
            ncols = max(1, w // cw)
            rows = max(1, h // rh)
            if len(self._rain_cols) != ncols:
                self._rain_cols = [random.randint(-rows, 0) for _ in range(ncols)]
            # Dégradé de verts : tête claire, traîne qui s'assombrit.
            colors = ["#eafff0", "#8affaf", "#5fe08c", "#3faf68", "#2b7d4a", "#1f5e38", "#164326"]
            trail = len(colors)
            c.delete("rain")
            for i in range(ncols):
                head = self._rain_cols[i]
                for k in range(trail):
                    ry = head - k
                    if 0 <= ry <= rows:
                        c.create_text(i * cw + cw // 2, ry * rh + rh // 2,
                                      text=random.choice(self._rain_chars),
                                      fill=colors[k], font=self.f_rain, tags="rain")
                self._rain_cols[i] = head + 1
                if head - trail > rows and random.random() < 0.5:
                    self._rain_cols[i] = random.randint(-rows // 2, 0)
        self.root.after(120, self._matrix_tick)

    def _show_home(self) -> None:
        if self.busy:
            return
        self.chat.pack_forget()
        self.home.pack(fill="both", expand=True)

    def _open_mode(self, key: str) -> None:
        self.home.pack_forget()
        self.chat.pack(fill="both", expand=True)
        self._select_mode(key)

    # ---- affichage ------------------------------------------------------
    def _write(self, text: str, tag: str) -> None:
        self.view.configure(state="normal")
        self.view.insert("end", text, tag)
        self.view.configure(state="disabled")
        self.view.see("end")

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ---- modes ----------------------------------------------------------
    def _select_mode(self, key: str) -> None:
        self.mode_key = key
        title = MODES[key][0]
        try:
            available = self.client.list_models()
        except OllamaError as e:
            self.model = None
            self.header.configure(text=title)
            self._set_status(str(e))
            self._reset_conversation(announce=False)
            return
        primary = _env_model(*MODES[key][3])
        fallback = _env_model(*MODES[key][4])
        self.model, note = choose_model(available, primary, fallback)
        self._reset_conversation(announce=True)
        self.header.configure(text=f"{title}   ·   {self.model or 'aucun modèle'}")
        # Le gestionnaire de modèles n'apparaît que dans Heretic ; le choix du
        # dossier de projet, que pour les modes agent (REA, Codex-Terminal).
        self.models_btn.pack_forget()
        self.project_btn.pack_forget()
        if key == "heretic":
            self.models_btn.pack(side="right", padx=8)
        if key in AGENT_MODES:
            self.project_btn.pack(side="right", padx=8)
        extra = ""
        if key == "heretic" and self.model and self.model != "heretic:latest":
            extra = "  ⚠ modèle de repli NON décensuré."
        self._set_status((note + extra).strip() or f"Prêt — modèle {self.model}.")

    def _reset_conversation(self, announce: bool = True) -> None:
        if self.busy:
            return
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        self.view.configure(state="disabled")
        key = self.mode_key
        system = MODES[key][2]
        if key in AGENT_MODES:
            # Agent complet avec outils (web/vision/fichiers/commandes) et une
            # vraie confirmation à l'écran. REA utilise le prompt par défaut ;
            # Codex-Terminal utilise son prompt shell (MODES[key][2]).
            self.agent = Agent(self.config, self.client, confirm=self._gui_confirm,
                               on_event=lambda m: self.queue.put(("tool", m + "\n")),
                               system_prompt=system, options=self.options)
            self.messages = []
        else:
            self.agent = None
            self.messages = [{"role": "system", "content": with_memory(system, self.config)}]
        if announce:
            self._write(f"— {MODES[key][0]} —\n", "ai")

    # ---- confirmation thread-safe pour REA ------------------------------
    def _gui_confirm(self, question: str) -> bool:
        """Appelé depuis le fil de l'agent : ouvre une boîte oui/non sur le fil
        principal et attend la réponse."""
        event = threading.Event()
        box = {"ok": False}

        def ask():
            box["ok"] = self.messagebox.askyesno("REA — confirmation", question)
            event.set()

        self.root.after(0, ask)
        event.wait()
        return box["ok"]

    # ---- envoi ----------------------------------------------------------
    def _on_return(self, event):
        if event.state & 0x0001:  # Shift : saut de ligne
            return
        self._send()
        return "break"

    def _send(self) -> None:
        if self.busy:
            return
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")

        if text.startswith("/retenir "):
            msg = remember(self.config, text[len("/retenir "):].strip())
            self._write(f"🧠 {msg}\n", "tool")
            return
        if self.model is None:
            self._write("Aucun modèle disponible — vérifie qu'Ollama tourne.\n", "err")
            return

        self._write("toi ❯ ", "you")
        self._write(f"{text}\n", "body")
        self._set_busy(True)
        self._write(f"{MODES[self.mode_key][0]} ❯ ", "ai")
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text: str) -> None:
        try:
            if self.agent is not None:
                answer = self.agent.run(text)
                self.queue.put(("answer", answer + "\n"))
            else:
                # Modes simples : flux mot par mot pour qu'on voie la réponse
                # arriver (le 1er chargement du modèle peut prendre un moment).
                self.messages.append({"role": "user", "content": text})
                full = ""
                for chunk in self.client.chat_stream(self.messages, model=self.model,
                                                     options=self.options or None):
                    full += chunk
                    self.queue.put(("chunk", chunk))
                self.messages.append({"role": "assistant", "content": full.strip()})
                self.queue.put(("chunk", "\n"))
        except OllamaError as e:
            self.queue.put(("error", f"\n{e}\n"))
        except Exception as e:  # pragma: no cover - garde-fou UI
            self.queue.put(("error", f"\nErreur inattendue : {e}\n"))
        finally:
            self.queue.put(("done", ""))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "answer":
                    self._write(payload, "body")
                elif kind == "chunk":
                    self._write(payload, "body")
                elif kind == "tool":
                    self._write(payload, "tool")
                elif kind == "error":
                    self._write(payload, "err")
                elif kind == "done":
                    self._set_busy(False)
                elif kind == "status":
                    self._set_status(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_btn.set_enabled(not busy)
        self.send_btn.set_text("…" if busy else "Envoyer")

    # ---- image ----------------------------------------------------------
    def _attach_image(self) -> None:
        if self.busy or self.model is None:
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
        path = self.filedialog.askopenfilename(
            title="Choisir une image",
            filetypes=[("Images", exts), ("Tous les fichiers", "*.*")])
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in IMAGE_EXTENSIONS:
            self._write(f"Format d'image non supporté : {p.name}\n", "err")
            return
        self._write(f"🖼  {p.name} — analyse…\n", "tool")
        self._set_busy(True)
        threading.Thread(target=self._image_worker, args=(p,), daemon=True).start()

    def _image_worker(self, path: Path) -> None:
        try:
            description = self.client.describe_image(path, "Décris cette image en détail.")
            target = self.agent.messages if self.agent is not None else self.messages
            target.append({"role": "user", "content": f"[Image jointe : {path.name}]\n{description}"})
            self.queue.put(("answer", f"[{path.name}] {description}\n"))
        except OllamaError as e:
            self.queue.put(("error", f"{e}\n"))
        finally:
            self.queue.put(("done", ""))

    # ---- réglages de génération (température, etc.) ----------------------
    def _params_panel(self) -> None:
        """Fenêtre pour régler température, top_p, top_k, etc. — appliqués en
        direct à tous les modes (réponses plus ou moins directes/créatives)."""
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("Réglages du modèle")
        win.configure(bg=BG)
        win.geometry("520x420")
        win.transient(self.root)
        tk.Label(win, text="🎚 Réglages de génération", bg=BG, fg=ORANGE,
                 font=self.f_bold).pack(anchor="w", padx=14, pady=(14, 2))
        tk.Label(win, text="Vide = valeur par défaut du modèle. Température haute = réponses "
                 "plus directes/variées ; basse = plus stables.", bg=BG, fg=MUTED,
                 font=self.f_small, wraplength=480, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        entries: dict[str, object] = {}
        form = tk.Frame(win, bg=BG)
        form.pack(fill="x", padx=14)
        for i, (key, (_kind, low, high, text)) in enumerate(PARAMS.items()):
            tk.Label(form, text=key, bg=BG, fg=ORANGE, font=self.f_bold, anchor="w",
                     width=14).grid(row=i, column=0, sticky="w", pady=3)
            e = tk.Entry(form, bg=PANEL, fg=FG, insertbackground=ORANGE, bd=0, font=self.f_body, width=10)
            if key in self.options:
                e.insert(0, str(self.options[key]))
            e.grid(row=i, column=1, sticky="w", padx=6)
            tk.Label(form, text=f"[{low:g}–{high:g}] {text}", bg=BG, fg=MUTED,
                     font=self.f_small, anchor="w", wraplength=300, justify="left").grid(row=i, column=2, sticky="w")
            entries[key] = e
        form.columnconfigure(2, weight=1)

        msg = tk.Label(win, text="", bg=BG, fg=GREEN, font=self.f_small, anchor="w",
                       wraplength=480, justify="left")
        msg.pack(fill="x", padx=14, pady=(8, 2))

        def apply():
            errs = []
            for key, e in entries.items():
                raw = e.get().strip()
                if not raw:
                    self.options.pop(key, None)  # vide = défaut du modèle
                    continue
                try:
                    set_param(self.options, key, raw)
                except ValueError as ex:
                    errs.append(str(ex))
            if errs:
                msg.configure(fg=RED, text=" / ".join(errs))
            else:
                applied = ", ".join(f"{k}={v}" for k, v in self.options.items()) or "(défauts du modèle)"
                msg.configure(fg=GREEN, text=f"Appliqué : {applied}")

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=14, pady=10)
        tk.Button(btns, text="Appliquer", bg=ORANGE, fg=ORANGE_DK, activebackground=GREEN,
                  bd=0, font=self.f_bold, cursor="hand2", padx=14, command=apply).pack(side="left")
        tk.Button(btns, text="Fermer", bg=BG, fg=MUTED, activebackground=BG,
                  activeforeground=FG, bd=0, font=self.f_small, cursor="hand2",
                  command=win.destroy).pack(side="right")

    # ---- dossier de projet (pour REA / Codex-Terminal) ------------------
    def _choose_project(self) -> None:
        if self.busy:
            return
        folder = self.filedialog.askdirectory(
            title="Dossier du projet où l'agent va travailler")
        if not folder:
            return
        from pathlib import Path as _P
        self.config.workspace = _P(folder).resolve()
        self.config.workspace.mkdir(parents=True, exist_ok=True)
        # Reconstruit l'agent pour qu'il lise/écrive dans ce dossier.
        self._reset_conversation(announce=True)
        self._write(f"📁 Dossier de projet : {self.config.workspace}\n", "tool")
        self._set_status(f"Projet : {self.config.workspace}")

    # ---- le « cerveau » : mémoire partagée (faits + erreurs apprises) ----
    def _show_brain(self) -> None:
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("Cerveau — mémoire partagée")
        win.configure(bg=BG)
        win.geometry("560x460")
        win.transient(self.root)
        tk.Label(win, text="🧠 Ce que l'IA a retenu (partagé par tous les modes)",
                 bg=BG, fg=ORANGE, font=self.f_bold).pack(anchor="w", padx=14, pady=(14, 2))
        tk.Label(win, text=f"Fichier : {memory_path(self.config)}", bg=BG, fg=MUTED,
                 font=self.f_small, wraplength=520, justify="left").pack(anchor="w", padx=14)
        txt = tk.Text(win, bg=PANEL, fg=FG, wrap="word", bd=0, padx=10, pady=8,
                      font=self.f_small, insertbackground=FG)
        txt.pack(fill="both", expand=True, padx=14, pady=8)
        content = load_memory(self.config).strip()
        txt.insert("1.0", content or
                   "(Vide pour l'instant.)\n\nL'IA ajoute ici :\n"
                   "• les faits que tu mémorises avec /retenir\n"
                   "• les erreurs d'outils rencontrées, pour ne pas les refaire.")
        txt.configure(state="disabled")
        tk.Button(win, text="Fermer", bg=BG, fg=MUTED, activebackground=BG,
                  activeforeground=FG, bd=0, font=self.f_small, cursor="hand2",
                  command=win.destroy).pack(pady=(0, 10))

    # ---- recherche web (dans tous les modes) ----------------------------
    def _web_search(self) -> None:
        if self.busy or self.model is None:
            return
        query = self.simpledialog.askstring("Recherche web", "Que chercher sur le web ?", parent=self.root)
        if not query:
            return
        self._write(f"🌐 Recherche web : {query}\n", "tool")
        self._set_busy(True)
        threading.Thread(target=self._web_worker, args=(query,), daemon=True).start()

    def _web_worker(self, query: str) -> None:
        try:
            # On réutilise les outils web de l'agent (web_search), même en mode
            # Chat/Codex/Heretic qui n'ont pas d'outils par eux-mêmes.
            box = Toolbox(self.config, self.client)
            results = box.tool_web_search(query)
            target = self.agent.messages if self.agent is not None else self.messages
            target.append({"role": "user",
                           "content": f"[Résultats web pour « {query} »]\n{results}\n"
                                      "Réponds à ma question en t'appuyant là-dessus."})
            self.queue.put(("answer", f"{results}\n\n(Résultats ajoutés — pose ta question dessus.)\n"))
        except Exception as e:  # pragma: no cover
            self.queue.put(("error", f"Erreur de recherche web : {e}\n"))
        finally:
            self.queue.put(("done", ""))

    # ---- capture d'écran ------------------------------------------------
    def _capture_screen(self) -> None:
        if self.busy or self.model is None:
            return
        self._write("📸 Capture d'écran — analyse…\n", "tool")
        self._set_busy(True)
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self) -> None:
        import time
        from .screenshot import ScreenshotError, take_screenshot
        try:
            dest = self.config.workspace / f"capture-{int(time.time())}.png"
            take_screenshot(dest)
            description = self.client.describe_image(dest, "Décris ce qui est affiché à l'écran.")
            target = self.agent.messages if self.agent is not None else self.messages
            target.append({"role": "user", "content": f"[Capture d'écran]\n{description}"})
            self.queue.put(("answer", f"[écran] {description}\n"))
        except ScreenshotError as e:
            self.queue.put(("error", f"{e}\n"))
        except OllamaError as e:
            self.queue.put(("error", f"{e}\n"))
        except Exception as e:  # pragma: no cover
            self.queue.put(("error", f"Erreur : {e}\n"))
        finally:
            self.queue.put(("done", ""))

    # ---- gestionnaire de modèles ----------------------------------------
    def _goto_chat(self, header: str) -> None:
        self.home.pack_forget()
        self.chat.pack(fill="both", expand=True)
        self.header.configure(text=header)
        self.models_btn.pack_forget()
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        self.view.configure(state="disabled")

    def _run_modelop(self, header: str, startline: str, fn) -> None:
        """Lance une opération de modèle (fn renvoie un texte) dans un fil, et
        montre le résultat dans la zone de conversation."""
        self._goto_chat(header)
        self._write(startline + "\n", "ai")
        self._set_busy(True)

        def work():
            try:
                self.queue.put(("answer", fn() + "\n"))
            except ModelOpsError as e:
                self.queue.put(("error", f"{e}\n"))
            except Exception as e:  # pragma: no cover
                self.queue.put(("error", f"Erreur : {e}\n"))
            finally:
                self.queue.put(("done", ""))

        threading.Thread(target=work, daemon=True).start()

    def _models_manager(self) -> None:
        """Fenêtre listant les modèles installés + toutes les opérations."""
        if self.busy:
            return
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("Gérer les modèles")
        win.configure(bg=BG)
        win.geometry("480x460")
        win.transient(self.root)

        tk.Label(win, text="Modèles installés", bg=BG, fg=ORANGE,
                 font=self.f_bold).pack(anchor="w", padx=14, pady=(14, 4))
        lb = tk.Listbox(win, bg=PANEL, fg=FG, selectbackground=ORANGE,
                        selectforeground=ORANGE_DK, bd=0, highlightthickness=0,
                        font=self.f_body, height=8, activestyle="none")
        lb.pack(fill="both", expand=True, padx=14)

        def refresh():
            lb.delete(0, "end")
            try:
                for m in self.client.list_models():
                    lb.insert("end", m)
            except OllamaError as e:
                lb.insert("end", f"(Ollama injoignable : {e})")

        def selected() -> str | None:
            sel = lb.curselection()
            if not sel:
                return None
            val = lb.get(sel[0])
            return None if val.startswith("(") else val

        refresh()
        info = tk.Label(win, text="Sélectionne un modèle pour Variante / Renommer / Supprimer / Détails.",
                        bg=BG, fg=MUTED, font=self.f_small, wraplength=450, justify="left")
        info.pack(anchor="w", padx=14, pady=(6, 2))

        grid = tk.Frame(win, bg=BG)
        grid.pack(fill="x", padx=12, pady=(4, 12))

        def need_selection():
            self.messagebox.showinfo("Sélection", "Choisis d'abord un modèle dans la liste.", parent=win)

        # --- opérations ---
        def op_variant():
            base = selected()
            if not base:
                return need_selection()
            name = self.simpledialog.askstring("Variante", "Nom de la variante (ex : qwen3-quebec) :", parent=win)
            if not name:
                return
            system = self.simpledialog.askstring("Variante", "Prompt système à fixer (laisse vide pour aucun) :", parent=win) or ""
            temp = self.simpledialog.askstring("Variante", "Température 0.0–2.0 (laisse vide pour défaut) :", parent=win)
            win.destroy()
            self._run_modelop("Modèles — variante", f"Création de « {name} » depuis « {base} »…",
                              lambda: create_variant(base, name, system, temp, self.config, self._gui_confirm))

        def op_rename():
            src = selected()
            if not src:
                return need_selection()
            dst = self.simpledialog.askstring("Renommer / copier", f"Nouveau nom pour « {src} » :", parent=win)
            if not dst:
                return
            win.destroy()
            self._run_modelop("Modèles — copie", f"Copie de « {src} » vers « {dst} »…",
                              lambda: copy_model(src, dst, self._gui_confirm))

        def op_delete():
            name = selected()
            if not name:
                return need_selection()
            win.destroy()
            self._run_modelop("Modèles — suppression", f"Suppression de « {name} »…",
                              lambda: delete_model(name, self._gui_confirm))

        def op_details():
            name = selected()
            if not name:
                return need_selection()
            win.destroy()
            self._run_modelop("Modèles — détails", f"Détails de « {name} » :",
                              lambda: show_model(name))

        def op_decensor():
            model = self.simpledialog.askstring(
                "Décensurer (Heretic)",
                "Modèle Hugging Face à décensurer\n(ex : Qwen/Qwen3-4B-Instruct-2507) :", parent=win)
            if not model:
                return
            win.destroy()
            self._run_modelop("Heretic — décensuration",
                              f"Lancement de Heretic sur « {model} » — suis ses questions dans le terminal…",
                              lambda: run_heretic(model, self._gui_confirm))

        def op_import():
            folder = self.filedialog.askdirectory(title="Dossier du modèle (safetensors ou .gguf)", parent=win)
            if not folder:
                return
            name = self.simpledialog.askstring("Importer", "Nom du nouveau modèle Ollama (ex : qwen3-libre) :", parent=win)
            if not name:
                return
            win.destroy()
            self._run_modelop("Modèles — import", f"Import de « {name} » depuis {folder}…",
                              lambda: import_to_ollama(folder, name, self.config, self._gui_confirm))

        def op_pull():
            name = self.simpledialog.askstring("Télécharger", "Modèle à télécharger (ex : llama3.2:1b) :", parent=win)
            if not name:
                return
            win.destroy()
            self._run_modelop("Modèles — téléchargement", f"Téléchargement de « {name} »…",
                              lambda: pull_model(name, self._gui_confirm))

        buttons = [
            ("Variante (prompt/temp)", op_variant),
            ("Renommer / copier", op_rename),
            ("Supprimer", op_delete),
            ("Détails", op_details),
            ("Décensurer (Heretic)", op_decensor),
            ("Importer un dossier", op_import),
            ("Télécharger", op_pull),
            ("Rafraîchir", refresh),
        ]
        for i, (label, cmd) in enumerate(buttons):
            tk.Button(grid, text=label, bg=PANEL, fg=FG, activebackground=ORANGE,
                      activeforeground=ORANGE_DK, bd=0, font=self.f_body, cursor="hand2",
                      command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        tk.Button(win, text="Fermer", bg=BG, fg=MUTED, activebackground=BG,
                  activeforeground=FG, bd=0, font=self.f_small, cursor="hand2",
                  command=win.destroy).pack(pady=(0, 10))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except Exception:
        print("Tkinter n'est pas disponible. Sur Linux : sudo apt install python3-tk")
        print("Sinon, utilise le menu texte : python3 -m ti_lex_agent.launcher")
        return 1
    try:
        LexOSApp().run()
    except Exception as e:  # pragma: no cover - dépend de l'affichage
        print(f"Impossible d'ouvrir la fenêtre ({e}).")
        print("Pas d'écran graphique ? Utilise le menu texte : python3 -m ti_lex_agent.launcher")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
