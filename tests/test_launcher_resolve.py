from ti_lex_agent.launcher import resolve_model


class FakeClient:
    def __init__(self, models):
        self.models = models

    def list_models(self):
        return self.models


def test_resolve_returns_primary_when_installed():
    assert resolve_model(FakeClient(["heretic:latest"]), "heretic:latest",
                         "llama3.2:1b", "Heretic") == "heretic:latest"


def test_resolve_falls_back_when_primary_missing(capsys):
    result = resolve_model(FakeClient(["llama3.2:1b"]), "heretic:latest", "llama3.2:1b", "Heretic")
    assert result == "llama3.2:1b"
    out = capsys.readouterr().out
    assert "PAS décensuré" in out  # avertissement spécifique à Heretic


def test_resolve_matches_implicit_latest_tag():
    # Ollama peut lister "qwen3-vl:latest" alors qu'on cherche juste "qwen3-vl:4b"
    assert resolve_model(FakeClient(["qwen3-vl:4b"]), "qwen3-vl:4b",
                         "llama3.2:1b", "Chat") == "qwen3-vl:4b"


def test_resolve_returns_none_when_nothing_installed(capsys):
    result = resolve_model(FakeClient([]), "heretic:latest", "llama3.2:1b", "Heretic")
    assert result is None
    assert "ollama pull" in capsys.readouterr().out


def test_resolve_uses_any_model_as_last_resort(capsys):
    # Ni le principal ni le repli nommé ne sont là, mais un autre modèle existe :
    # on le prend au lieu de bloquer le menu.
    result = resolve_model(FakeClient(["qwen3:8b"]), "qwen3-vl:4b", "llama3.2:1b", "Chat")
    assert result == "qwen3:8b"
    assert "seul modèle disponible" in capsys.readouterr().out


def test_resolve_last_resort_warns_not_decensored_for_heretic(capsys):
    result = resolve_model(FakeClient(["qwen3:8b"]), "heretic:latest", "llama3.2:1b", "Heretic")
    assert result == "qwen3:8b"
    assert "PAS décensuré" in capsys.readouterr().out
