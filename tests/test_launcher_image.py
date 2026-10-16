from pathlib import Path

from ti_lex_agent.config import Config
from ti_lex_agent.launcher import _handle_image


class FakeVisionClient:
    def __init__(self, description="une capture d'écran d'un menu orange et noir"):
        self.description = description
        self.calls = []

    def describe_image(self, path, question):
        self.calls.append((path, question))
        return self.description


def make_config(tmp_path):
    return Config(workspace=tmp_path / "workspace")


def test_image_description_is_added_to_conversation(tmp_path, capsys):
    config = make_config(tmp_path)
    (config.workspace / "ecran.png").write_bytes(b"\x89PNG")
    client = FakeVisionClient()
    messages = []
    _handle_image(config, client, messages, "/image ecran.png")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "ecran.png" in messages[0]["content"]
    assert "menu orange et noir" in messages[0]["content"]


def test_image_custom_question_is_passed_to_vision_model(tmp_path):
    config = make_config(tmp_path)
    (config.workspace / "ecran.png").write_bytes(b"\x89PNG")
    client = FakeVisionClient()
    _handle_image(config, client, [], "/image ecran.png combien de boutons ?")
    assert client.calls[0][1] == "combien de boutons ?"


def test_image_rejects_path_escape(tmp_path, capsys):
    config = make_config(tmp_path)
    client = FakeVisionClient()
    messages = []
    _handle_image(config, client, messages, "/image ../dehors.png")
    assert messages == []
    assert "Erreur" in capsys.readouterr().out
    assert client.calls == []


def test_image_rejects_bad_extension(tmp_path, capsys):
    config = make_config(tmp_path)
    (config.workspace / "notes.txt").write_text("x")
    client = FakeVisionClient()
    messages = []
    _handle_image(config, client, messages, "/image notes.txt")
    assert messages == []
    assert "non supporté" in capsys.readouterr().out


def test_image_rejects_missing_file(tmp_path, capsys):
    config = make_config(tmp_path)
    config.workspace.mkdir(parents=True, exist_ok=True)
    client = FakeVisionClient()
    messages = []
    _handle_image(config, client, messages, "/image absente.png")
    assert messages == []
    assert "introuvable" in capsys.readouterr().out


def test_image_without_path_shows_usage(tmp_path, capsys):
    config = make_config(tmp_path)
    _handle_image(config, FakeVisionClient(), [], "/image ")
    assert "Usage" in capsys.readouterr().out
