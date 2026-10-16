from ti_lex_agent.launcher import _env_model


def test_env_model_default(monkeypatch):
    monkeypatch.delenv("TILEX_CHAT_MODEL", raising=False)
    assert _env_model("TILEX_CHAT_MODEL", "qwen3-vl:4b") == "qwen3-vl:4b"


def test_env_model_override(monkeypatch):
    monkeypatch.setenv("TILEX_CHAT_MODEL", "autre-modele:latest")
    assert _env_model("TILEX_CHAT_MODEL", "qwen3-vl:4b") == "autre-modele:latest"
