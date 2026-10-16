from ti_lex_agent.cli import run_conversation
from ti_lex_agent.config import Config
from ti_lex_agent.params import DEFAULTS


class FakeClient:
    def chat(self, messages, tools=None, model=None, options=None):
        return {"role": "assistant", "content": "ok"}

    def describe_image(self, path, question):
        return ""


def make_agent(config):
    from ti_lex_agent.agent import Agent
    return Agent(config, client=FakeClient(), confirm=lambda _q: True)


def run_inputs(monkeypatch, inputs, config, extra_quit=None):
    it = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))
    agent = make_agent(config)
    run_conversation(agent, config, dict(DEFAULTS), extra_quit=extra_quit)
    return config


def test_quit_stops_the_loop(monkeypatch, tmp_path, capsys):
    config = Config(workspace=tmp_path)
    run_inputs(monkeypatch, ["/quit"], config=config)
    assert "Écris ta demande" in capsys.readouterr().out


def test_extra_quit_word_also_stops(monkeypatch, tmp_path):
    config = Config(workspace=tmp_path)
    # Sans extra_quit, "/menu" ne serait pas reconnu et la boucle planterait
    # sur StopIteration au prochain input() — ce test confirme qu'il arrête bien.
    run_inputs(monkeypatch, ["/menu"], config=config, extra_quit={"/menu"})


def test_model_command_changes_config(monkeypatch, tmp_path, capsys):
    config = Config(workspace=tmp_path)
    run_inputs(monkeypatch, ["/model autre:latest", "/quit"], config=config)
    assert config.model == "autre:latest"
    assert "Modèle principal : autre:latest" in capsys.readouterr().out


def test_temp_command_updates_options(monkeypatch, tmp_path, capsys):
    config = Config(workspace=tmp_path)
    it = iter(["/temp 0.3", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))
    options = dict(DEFAULTS)
    agent = make_agent(config)
    run_conversation(agent, config, options)
    assert options["temperature"] == 0.3


def test_retenir_writes_to_shared_memory(monkeypatch, tmp_path, capsys):
    config = Config(workspace=tmp_path / "workspace")
    run_inputs(monkeypatch, ["/retenir ne jamais toucher le disque sda", "/quit"], config=config)
    assert "ne jamais toucher le disque sda" in (tmp_path / "memoire-ia.md").read_text()
    assert "Retenu" in capsys.readouterr().out
