"""Tests sans Ollama ni internet : on remplace le modèle par un faux client."""

import pytest

from ti_lex_agent.agent import Agent
from ti_lex_agent.config import Config
from ti_lex_agent.tools import ToolError, Toolbox, check_public_url, html_to_text


class FakeClient:
    """Rejoue des réponses prévues d'avance, dans l'ordre."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, tools=None, model=None, options=None):
        self.seen.append(list(messages))
        return self.replies.pop(0)

    def describe_image(self, path, question):
        return f"image {path.name}: {question}"


@pytest.fixture
def config(tmp_path):
    return Config(workspace=tmp_path / "ws")


def make_tools(config, answer=True):
    return Toolbox(config, FakeClient([]), confirm=lambda _q: answer)


def test_path_escape_is_blocked(config):
    t = make_tools(config)
    assert "en dehors" in t.call("read_file", {"path": "../secret.txt"})
    assert "en dehors" in t.call("write_file", {"path": "/etc/passwd", "content": "x"})


def test_write_then_read_and_list(config):
    t = make_tools(config)
    assert "Écrit" in t.call("write_file", {"path": "src/a.py", "content": "print(1)"})
    assert t.call("read_file", {"path": "src/a.py"}) == "print(1)"
    assert "src/a.py" in t.call("list_files", {"path": "src"})


def test_overwrite_needs_confirmation(config):
    make_tools(config).call("write_file", {"path": "a.txt", "content": "v1"})
    refused = make_tools(config, answer=False)
    assert "refusé" in refused.call("write_file", {"path": "a.txt", "content": "v2"})
    assert refused.call("read_file", {"path": "a.txt"}) == "v1"


def test_command_needs_confirmation(config):
    assert "refusé" in make_tools(config, answer=False).call("run_command", {"command": "echo hi"})
    out = make_tools(config, answer=True).call("run_command", {"command": "echo hi"})
    assert "hi" in out and "code de sortie : 0" in out


def test_unknown_tool_and_bad_arguments(config):
    t = make_tools(config)
    assert "inconnu" in t.call("rm_rf", {})
    assert "invalides" in t.call("read_file", {"mauvais": 1})


def test_real_errors_are_remembered_but_refusals_are_not(config):
    from ti_lex_agent.memory import load_memory

    t = make_tools(config)
    t.call("read_file", {"path": "introuvable.txt"})
    assert "introuvable.txt" in load_memory(config) or "introuvable" in load_memory(config)

    before = load_memory(config)
    make_tools(config, answer=False).call("run_command", {"command": "echo hi"})
    assert load_memory(config) == before  # un refus volontaire n'est pas une erreur à retenir


def test_describe_image_validates_input(config):
    t = make_tools(config)
    (config.workspace / "photo.png").write_bytes(b"\x89PNG")
    (config.workspace / "note.txt").write_text("x")
    assert "photo.png" in t.call("describe_image", {"path": "photo.png"})
    assert "Format non supporté" in t.call("describe_image", {"path": "note.txt"})
    assert "introuvable" in t.call("describe_image", {"path": "absent.png"})


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/", "http://localhost/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "ftp://example.com/",
])
def test_private_and_non_http_urls_rejected(url):
    with pytest.raises(ToolError):
        check_public_url(url)


def test_html_to_text_drops_scripts():
    html = "<html><head><title>x</title></head><body><script>evil()</script><h1>Salut</h1><p>le monde</p></body></html>"
    text = html_to_text(html)
    assert "Salut" in text and "le monde" in text and "evil" not in text


def test_agent_loop_calls_tool_then_answers(config):
    client = FakeClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file",
                          "arguments": {"path": "hello.py", "content": "print('salut')"}}}]},
        {"role": "assistant", "content": "Fichier créé."},
    ])
    events = []
    agent = Agent(config, client=client, confirm=lambda _q: True, on_event=events.append)
    assert agent.run("Crée hello.py") == "Fichier créé."
    assert (config.workspace / "hello.py").read_text() == "print('salut')"
    assert any("write_file" in e for e in events)
    # le résultat de l'outil a bien été renvoyé au modèle au 2e tour
    assert client.seen[1][-1]["role"] == "tool"


def test_agent_stops_after_max_steps(config):
    config.max_steps = 3
    loop_reply = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "list_files", "arguments": {}}}]}
    agent = Agent(config, client=FakeClient([loop_reply] * 3), confirm=lambda _q: True)
    assert "limite" in agent.run("boucle")
