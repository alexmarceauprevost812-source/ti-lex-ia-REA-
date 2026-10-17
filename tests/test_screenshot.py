"""Tests du module de capture d'écran (logique de sélection d'outil)."""

import pytest

from ti_lex_agent import screenshot
from ti_lex_agent.screenshot import ScreenshotError, available_tool, take_screenshot


def test_available_tool_none_when_nothing(monkeypatch):
    monkeypatch.setattr(screenshot.shutil, "which", lambda _n: None)
    # Simule aussi l'absence de mss.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "mss":
            raise ImportError("pas de mss")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert available_tool() is None


def test_take_screenshot_raises_without_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(screenshot.shutil, "which", lambda _n: None)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "mss":
            raise ImportError("pas de mss")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ScreenshotError, match="Aucun outil"):
        take_screenshot(tmp_path / "ecran.png")
