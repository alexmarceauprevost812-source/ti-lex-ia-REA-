from ti_lex_agent.config import Config
from ti_lex_agent.memory import load_memory, memory_path, remember, remember_error, with_memory


def make_config(tmp_path):
    return Config(workspace=tmp_path / "workspace")


def test_memory_lives_next_to_workspace_by_default(tmp_path):
    config = make_config(tmp_path)
    assert memory_path(config) == tmp_path / "memoire-ia.md"


def test_memory_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "ailleurs" / "m.md"
    monkeypatch.setenv("TILEX_MEMORY", str(custom))
    assert memory_path(make_config(tmp_path)) == custom


def test_remember_then_load(tmp_path):
    config = make_config(tmp_path)
    assert load_memory(config) == ""
    msg = remember(config, "aime le café noir")
    assert "aime le café noir" in msg
    assert "aime le café noir" in load_memory(config)


def test_remember_empty_text_is_a_no_op(tmp_path):
    config = make_config(tmp_path)
    remember(config, "   ")
    assert not memory_path(config).exists()


def test_with_memory_injects_existing_facts(tmp_path):
    config = make_config(tmp_path)
    remember(config, "utilise LexOS Pro")
    combined = with_memory("Tu es un assistant.", config)
    assert "Tu es un assistant." in combined
    assert "utilise LexOS Pro" in combined


def test_with_memory_unchanged_when_nothing_stored(tmp_path):
    config = make_config(tmp_path)
    assert with_memory("Tu es un assistant.", config) == "Tu es un assistant."


def test_remember_error_is_recorded(tmp_path):
    config = make_config(tmp_path)
    remember_error(config, "write_file(path='/etc/passwd')", "Erreur : en dehors du dossier")
    assert "en dehors du dossier" in load_memory(config)


def test_remember_error_does_not_duplicate(tmp_path):
    config = make_config(tmp_path)
    remember_error(config, "ctx", "même erreur")
    remember_error(config, "ctx", "même erreur")
    assert load_memory(config).count("même erreur") == 1


def test_remember_error_never_raises_when_text_empty(tmp_path):
    config = make_config(tmp_path)
    remember_error(config, "ctx", "   ")  # ne doit pas planter
    assert load_memory(config) == ""
