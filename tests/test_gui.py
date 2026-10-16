"""Tests de la logique de l'interface graphique (sans ouvrir de fenêtre).

On ne teste que ce qui ne dépend pas de Tkinter : le choix du modèle. La
construction de la fenêtre elle-même exige un écran et python3-tk, donc elle
n'est pas testée ici."""

from ti_lex_agent.gui import MODES, choose_model


def test_choose_primary_when_present():
    assert choose_model(["heretic:latest", "qwen3:8b"], "heretic:latest", "x") == ("heretic:latest", "")


def test_choose_fallback_when_primary_absent():
    model, note = choose_model(["llama3.2:1b"], "qwen3-vl:4b", "llama3.2:1b")
    assert model == "llama3.2:1b"
    assert "repli" in note


def test_choose_any_as_last_resort():
    model, note = choose_model(["qwen3:8b"], "qwen3-vl:4b", "llama3.2:1b")
    assert model == "qwen3:8b"
    assert "qwen3:8b" in note


def test_choose_none_when_empty():
    model, note = choose_model([], "a", "b")
    assert model is None
    assert "Aucun" in note


def test_modes_cover_the_four_choices():
    assert set(MODES) == {"chat", "codex", "rea", "heretic"}
    # REA n'a pas de prompt système fixe (il utilise celui de l'agent).
    assert MODES["rea"][2] is None
    assert MODES["heretic"][3] == ("TILEX_HERETIC_MODEL", "heretic:latest")
