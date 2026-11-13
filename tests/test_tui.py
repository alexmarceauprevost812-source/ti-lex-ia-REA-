"""Tests de l'interface plein écran (lexos-tui), sans Ollama : faux client."""

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static, Tabs  # noqa: E402

from ti_lex_agent import tui  # noqa: E402
from ti_lex_agent.config import Config  # noqa: E402
from ti_lex_agent.ollama_client import OllamaError  # noqa: E402
from ti_lex_agent.tui import ConfirmScreen, LexosApp, WorkspaceTree  # noqa: E402

CODE_REPLY = "Voici :\n\n```python\nprint('allo')\n```\n\nVoilà."


class FakeClient:
    """Remplace OllamaClient : réponses écrites d'avance, rien ne sort du PC."""

    script: list[dict] = []          # réponses de chat() pour REA, dans l'ordre
    stream_chunks: list[str] = [CODE_REPLY]
    fail_stream = False
    models = ["marceau-ia:latest", "qwen2.5-coder:7b", "qwen3-vl:4b"]

    def __init__(self, config):
        self.config = config
        self.seen_models: list[str] = []

    def list_models(self):
        return list(self.models)

    def chat_stream(self, messages, model=None, options=None):
        self.seen_models.append(model or self.config.model)
        if self.fail_stream:
            raise OllamaError("Impossible de joindre Ollama (test).")
        yield from self.stream_chunks

    def chat(self, messages, tools=None, model=None, options=None):
        self.seen_models.append(model or self.config.model)
        return FakeClient.script.pop(0)

    def describe_image(self, path, question):
        return "une image"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("TILEX_REA_MODEL", "marceau-ia")
    monkeypatch.setenv("TILEX_CODEX_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("TILEX_CHAT_MODEL", "qwen3-vl:4b")
    FakeClient.script = []
    FakeClient.stream_chunks = [CODE_REPLY]
    FakeClient.fail_stream = False
    yield


def make_app(tmp_path, **kw):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return LexosApp(Config(workspace=ws), client_factory=FakeClient, **kw), ws


def run(coro):
    return asyncio.run(coro)


async def type_and_send(pilot, text):
    await pilot.click("#prompt")
    await pilot.press(*list(text))
    await pilot.press("enter")


async def wait_idle(app, pilot, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        await pilot.pause(0.05)
        if not app.busy:
            return
    raise AssertionError("la réponse n'a jamais fini")


def entry_kinds(app, key=None):
    mode = app.modes[key] if key else app.current
    return [e.kind for e in mode.transcript]


# --------------------------------------------------------------------------- helpers
def test_split_blocks_separates_code_from_text():
    blocks = tui.split_blocks("Avant\n```python\nx = 1\n```\nAprès")
    assert [b[0] for b in blocks] == ["text", "code", "text"]
    assert blocks[1] == ("code", "x = 1", "python")


def test_split_blocks_unclosed_fence_is_code_while_streaming():
    blocks = tui.split_blocks("Voici\n```js\nlet a = 1;")
    assert blocks[-1] == ("code", "let a = 1;", "js")


def test_split_think_hides_reasoning():
    assert tui.split_think("<think>hum</think>Bonjour") == ("Bonjour", False)
    assert tui.split_think("<think>je réfléchis")[1] is True
    assert tui.split_think("raisonnement</think>Réponse") == ("Réponse", False)


def test_pick_model_uses_fallback_then_any():
    assert tui.pick_model(["a:latest"], "a", "b") == ("a", None)
    name, note = tui.pick_model(["b:1b"], "a", "b")
    assert name == "b" and note
    name, note = tui.pick_model(["zzz"], "a", "b")
    assert name == "zzz" and "seul" in note


def test_fmt_call_and_summary():
    assert "scan.py" in tui.fmt_call("write_file", {"path": "scan.py", "content": "abc"})
    assert tui.fmt_call("run_command", {"command": "pytest"}) == "run_command  pytest"
    out = tui.summarize_result("\n".join(f"ligne {i}" for i in range(20)))
    assert out.endswith("(+14 lignes)")


def test_code_theme_is_neon_on_black():
    assert tui.NeonStyle.background_color == "#000000"
    assert tui.SKY == "#87ceeb" and tui.WHITE == "#ffffff"


# ----------------------------------------------------------------------- l'application
def test_starts_black_in_rea_with_three_tabs(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            assert app.current.key == "rea"
            assert [t.id for t in app.query("Tab")] == ["rea", "codex", "chat"]
            assert app.theme == "lexos-noir"
            assert app.screen.styles.background.hex.lower() == "#000000"
            assert app.focused.id == "prompt"
    run(scenario())


def test_modes_share_the_screen_but_keep_their_own_conversation(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("ctrl+t")            # REA -> Codex
            await pilot.pause(0.1)
            assert app.current.key == "codex"
            await type_and_send(pilot, "bonjour")
            await wait_idle(app, pilot)
            assert entry_kinds(app, "codex")[-2:] == ["user", "ai"]
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.2)
            assert app.current.key == "chat"
            assert "user" not in entry_kinds(app, "chat")      # Chat n'a rien reçu
            assert "user" in entry_kinds(app, "codex")         # Codex a gardé le sien
            await type_and_send(pilot, "/codex")
            await pilot.pause(0.2)
            shown = list(app.query(".entry"))                  # l'historique est réaffiché
            assert len(shown) == len(app.current.transcript)
            assert all(e.widget in shown for e in app.current.transcript)
    run(scenario())


def test_chat_modes_stream_and_keep_history(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.2)
            await type_and_send(pilot, "allo")
            await wait_idle(app, pilot)
            chat = app.modes["chat"]
            roles = [m["role"] for m in chat.messages]
            assert roles == ["system", "user", "assistant"]
            assert chat.messages[-1]["content"].startswith("Voici")
    run(scenario())


def test_engine_changes_per_mode(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.1)
            await type_and_send(pilot, "/model asselin")
            await pilot.pause(0.1)
            assert app.modes["chat"].model == "asselin"
            assert app.modes["rea"].model == "marceau-ia:latest" or app.modes["rea"].model == "marceau-ia"
            await type_and_send(pilot, "salut")
            await wait_idle(app, pilot)
            assert app.modes["chat"].client.seen_models[-1] == "asselin"
    run(scenario())


def test_rea_uses_tools_and_opens_the_file(tmp_path):
    FakeClient.script = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "write_file", "arguments": {"path": "scan.py", "content": "print(80)\n"}}}]},
        {"role": "assistant", "content": "Fait : `scan.py` est écrit."},
    ]

    async def scenario():
        app, ws = make_app(tmp_path)
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "écris scan.py")
            await wait_idle(app, pilot)
            assert (ws / "scan.py").read_text() == "print(80)\n"
            assert entry_kinds(app)[-3:] == ["user", "tool", "ai"]
            assert app.query_one("#viewer").display is True          # l'aperçu s'ouvre seul
            assert "scan.py" in str(app.query_one("#viewer-title", Static).render())
    run(scenario())


def test_rea_asks_before_overwriting(tmp_path):
    FakeClient.script = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "write_file", "arguments": {"path": "a.txt", "content": "nouveau"}}}]},
        {"role": "assistant", "content": "ok"},
    ]

    async def scenario():
        app, ws = make_app(tmp_path)
        (ws / "a.txt").write_text("ancien")
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "remplace a.txt")
            for _ in range(60):
                await pilot.pause(0.05)
                if isinstance(app.screen, ConfirmScreen):
                    break
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("n")                                    # refus
            await wait_idle(app, pilot)
            assert (ws / "a.txt").read_text() == "ancien"
    run(scenario())


def test_confirm_yes_lets_rea_write(tmp_path):
    FakeClient.script = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "write_file", "arguments": {"path": "a.txt", "content": "nouveau"}}}]},
        {"role": "assistant", "content": "ok"},
    ]

    async def scenario():
        app, ws = make_app(tmp_path)
        (ws / "a.txt").write_text("ancien")
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "remplace a.txt")
            for _ in range(60):
                await pilot.pause(0.05)
                if isinstance(app.screen, ConfirmScreen):
                    break
            await pilot.press("o")
            await wait_idle(app, pilot)
            assert (ws / "a.txt").read_text() == "nouveau"
    run(scenario())


def test_panels_open_and_close(tmp_path):
    async def scenario():
        app, ws = make_app(tmp_path)
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.2)
            assert app.query_one("#files").display is True
            assert app.query_one("#viewer").display is False
            await pilot.press("ctrl+b")
            assert app.query_one("#files").display is False
            await pilot.press("ctrl+b")
            assert app.query_one("#files").display is True
            await pilot.press("ctrl+o")
            assert app.query_one("#viewer").display is True
            await pilot.click("#close-viewer")
            assert app.query_one("#viewer").display is False
            await pilot.click("#close-files")
            assert app.query_one("#files").display is False
    run(scenario())


def test_clicking_a_file_shows_it_colored(tmp_path):
    async def scenario():
        app, ws = make_app(tmp_path)
        (ws / "outil.py").write_text("def hello():\n    return 'allo'\n")
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.3)
            tree = app.query_one(WorkspaceTree)
            tree.focus()
            await pilot.press("down", "enter")        # outil.py est le premier enfant
            await pilot.pause(0.3)
            assert app.query_one("#viewer").display is True
            assert "outil.py" in str(app.query_one("#viewer-title", Static).render())
    run(scenario())


def test_open_command_refuses_paths_outside_workspace(tmp_path):
    async def scenario():
        app, ws = make_app(tmp_path)
        (tmp_path / "secret.txt").write_text("non")
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/ouvrir ../secret.txt")
            await pilot.pause(0.2)
            assert entry_kinds(app)[-1] == "error"
            assert app.query_one("#viewer").display is False
    run(scenario())


def test_ollama_error_is_shown_not_crashing(tmp_path):
    FakeClient.fail_stream = True

    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.1)
            await type_and_send(pilot, "allo")
            await wait_idle(app, pilot)
            assert entry_kinds(app)[-1] == "error"
            assert [m["role"] for m in app.modes["chat"].messages] == ["system"]
            assert app.busy is False
    run(scenario())


def test_escape_stops_a_streaming_answer(tmp_path):
    FakeClient.stream_chunks = ["mot " for _ in range(2000)]

    class Slow(FakeClient):
        def chat_stream(self, messages, model=None, options=None):
            import time
            for chunk in FakeClient.stream_chunks:
                time.sleep(0.002)
                yield chunk

    async def scenario():
        ws = tmp_path / "workspace"
        app = LexosApp(Config(workspace=ws), client_factory=Slow)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.1)
            await type_and_send(pilot, "long")
            await pilot.pause(0.3)
            assert app.busy
            await pilot.press("escape")
            await wait_idle(app, pilot)
            ai = [e for e in app.modes["chat"].transcript if e.kind == "ai"][-1]
            assert "interrompu" in ai.text
    run(scenario())


def test_retenir_writes_shared_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("TILEX_MEMORY", str(tmp_path / "memoire.md"))

    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/retenir coliss = câlisse")
            await pilot.pause(0.1)
    run(scenario())
    assert "coliss = câlisse" in (tmp_path / "memoire.md").read_text()


def test_reset_clears_conversation(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.1)
            await type_and_send(pilot, "allo")
            await wait_idle(app, pilot)
            await pilot.press("ctrl+n")
            await pilot.pause(0.1)
            assert [m["role"] for m in app.modes["chat"].messages] == ["system"]
            assert "user" not in entry_kinds(app)
    run(scenario())


def test_startup_falls_back_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TILEX_REA_MODEL", "pas-installe")
    monkeypatch.setenv("TILEX_REA_FALLBACK", "qwen3-vl:4b")

    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.5)
            assert app.modes["rea"].model == "qwen3-vl:4b"
            assert any("pas-installe" in e.text for e in app.modes["rea"].transcript)
    run(scenario())


def test_tabs_widget_matches_modes(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            tabs = app.query_one(Tabs)
            tabs.active = "chat"
            await pilot.pause(0.2)
            assert app.current.key == "chat"
    run(scenario())


def test_ctrl_q_closes_the_app(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("ctrl+q")
    run(asyncio.wait_for(scenario(), timeout=15))


# --------------------------------------------------------------------------- animations
def test_brand_glint_moves_and_the_name_never_changes():
    a, b = tui.brand_text(0, False), tui.brand_text(4, False)
    assert a.plain == b.plain == "LEXOS"
    assert [str(s.style) for s in a.spans] != [str(s.style) for s in b.spans]


def test_brand_cycles_neon_colors_when_busy():
    t = tui.brand_text(0, True)
    assert t.plain == "LEXOS"
    used = {str(s.style).split()[-1] for s in t.spans}
    assert len(used) > 1 and used <= set(tui.NEON_CYCLE)


def test_spinner_turns_while_the_model_works_then_stops(tmp_path):
    class Slow(FakeClient):
        def chat_stream(self, messages, model=None, options=None):
            import time
            for _ in range(20):
                time.sleep(0.05)
                yield "mot "

    async def scenario():
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        app = LexosApp(Config(workspace=ws), client_factory=Slow)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.2)
            await type_and_send(pilot, "/chat")
            await pilot.pause(0.1)
            await type_and_send(pilot, "salut")
            await pilot.pause(0.3)
            assert app.busy
            t1 = app._tick
            await pilot.pause(0.4)
            assert app._tick > t1
            txt = app._status_text().plain
            assert any(ch in txt for ch in tui.SPINNER)
            assert "(Échap = arrêter)" in txt
            await wait_idle(app, pilot)
            assert not any(ch in app._status_text().plain for ch in tui.SPINNER)
    run(scenario())


def test_animation_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("TILEX_SANS_ANIMATION", "1")

    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.5)
            assert app._tick == 0
    run(scenario())


def test_animation_runs_by_default(tmp_path):
    async def scenario():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(0.6)
            assert app._tick >= 2
    run(scenario())


# ------------------------------------------------------------------ accueil, outils, projets
def test_animation_les_lettres_arrivent_a_45_degres_et_le_mot_se_pose_bien_droit():
    assert not any(ch in tui.splash_frame(0).plain for ch in "/_|")      # tout est dans le ciel
    fin = tui.splash_frame(tui.splash_done_tick()).plain.splitlines()
    # mot posé : même style que la bannière KALI (police « slant »), droit, tout en bas
    assert [ligne.rstrip() for ligne in fin[-5:]] == [
        "  __________     __    _______  __",
        " /_  __/  _/    / /   / ____/ |/ /",
        "  / /  / /_____/ /   / __/  |   /",
        " / / _/ /_____/ /___/ /___ /   |",
        "/_/ /___/    /_____/_____//_/|_|",
    ]
    assert all(not ligne.strip() for ligne in fin[:-5])
    # en l'air, une lettre est décalée de SPLASH_SLIDE colonnes par ligne à descendre (45°)
    y1, dx1 = tui.splash_letter_pos(0, 6)
    y2, dx2 = tui.splash_letter_pos(0, 7)
    assert (y2 - y1, dx1 - dx2) == (1, tui.SPLASH_SLIDE)
    assert tui.splash_letter_pos(0, tui.splash_done_tick()) == (tui.SPLASH_ROWS - 5, 0)
    # les lettres arrivent l'une après l'autre : le T est toujours plus bas que le X
    assert tui.splash_letter_pos(0, 8)[0] > tui.splash_letter_pos(5, 8)[0]
    # couleurs une fois posé : « TI- » en blanc (à gauche), « LEX » en orange néon (à droite)
    pose = tui.splash_frame(tui.splash_done_tick() + 10)
    cellules = [(sp.start, str(sp.style)) for sp in pose.spans if pose.plain[sp.start:sp.end] not in " \n"]
    assert {c for _, c in cellules} == {f"bold {tui.WHITE}", f"bold {tui.NEON_ORANGE}"}
    assert cellules[0][1] == f"bold {tui.WHITE}"           # le T
    ligne = pose.plain.splitlines()
    colonne = ligne[-5].index("____", 17)                  # début du E
    x = [(sp.start, str(sp.style)) for sp in pose.spans if pose.plain[sp.start:sp.end] == "_"]
    assert any(st == f"bold {tui.NEON_ORANGE}" for _, st in x)


def test_accueil_les_choix_arrivent_un_par_un_puis_choix(tmp_path, monkeypatch):
    monkeypatch.setattr(tui, "SPLASH_STEP", 0.005)
    monkeypatch.setattr(tui, "MENU_STEP", 0.12)       # assez lent pour qu'on voie chaque étape

    async def go():
        app, _ = make_app(tmp_path, resolve_models=False, splash=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, tui.SplashScreen)
            menu = screen.query_one("#splash-menu")
            assert menu.option_count == 0                  # le mot tombe d'abord
            counts = set()
            for _ in range(600):
                await pilot.pause(0.01)
                counts.add(menu.option_count)
                if menu.option_count == len(tui.MENU_CHOICES):
                    break
            assert menu.option_count == len(tui.MENU_CHOICES)
            assert len(counts) > 2                         # apparus progressivement
            await pilot.press("2")                         # Codex
            await pilot.pause()
            assert not isinstance(app.screen, tui.SplashScreen)
            assert app.current.key == "codex"
    run(go())


def test_accueil_echap_passe_l_animation_et_cloner_prepare_la_commande(tmp_path):
    async def go():
        app, _ = make_app(tmp_path, resolve_models=False, splash=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen.query_one("#splash-menu").option_count == len(tui.MENU_CHOICES)
            await pilot.press("5")
            await pilot.pause()
            assert app.query_one("#prompt", Input).value == "/cloner "
    run(go())


def test_outils_ajouter_lancer_retirer(tmp_path):
    async def go():
        app, ws = make_app(tmp_path, resolve_models=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await type_and_send(pilot, "/ajouter-outil salut = echo allo-lexos > trace.txt")
            await type_and_send(pilot, "/outil salut")
            for _ in range(100):
                await pilot.pause(0.05)
                if (ws / "trace.txt").exists():
                    break
            assert (ws / "trace.txt").read_text().strip() == "allo-lexos"
            await pilot.press("f2")
            await pilot.pause()
            assert isinstance(app.screen, tui.ToolPicker)
            await pilot.press("escape")
            await type_and_send(pilot, "/retirer-outil salut")
            await type_and_send(pilot, "/outil salut")
            await pilot.pause()
            assert any(e.kind == "error" and "Aucun outil" in e.text
                       for e in app.current.transcript)
    run(go())


def test_nouveau_projet_et_refus(tmp_path):
    async def go():
        app, ws = make_app(tmp_path, resolve_models=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await type_and_send(pilot, "/nouveau demo")
            await pilot.pause()
            assert (ws / "demo" / "README.md").is_file()
            await type_and_send(pilot, "/nouveau ../dehors")
            await pilot.pause()
            assert not (tmp_path / "dehors").exists()
            assert app.current.transcript[-1].kind == "error"
    run(go())


def test_cloner_adresse_refusee(tmp_path):
    async def go():
        app, ws = make_app(tmp_path, resolve_models=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await type_and_send(pilot, "/cloner file:///etc")
            for _ in range(60):
                await pilot.pause(0.05)
                if any(e.kind == "error" for e in app.current.transcript):
                    break
            assert any(e.kind == "error" and "non reconnue" in e.text
                       for e in app.current.transcript)
            assert list(ws.iterdir()) == []
    run(go())
