import pytest

from ti_lex_agent.params import set_param


def test_set_valid_temperature():
    options = {}
    assert set_param(options, "temperature", "0.9") == "temperature = 0.9"
    assert options == {"temperature": 0.9}


def test_accepts_comma_decimal():
    options = {}
    set_param(options, "temperature", "1,2")
    assert options["temperature"] == 1.2


def test_integer_param():
    options = {}
    set_param(options, "num_ctx", "8192")
    assert options == {"num_ctx": 8192}


@pytest.mark.parametrize("key,value", [
    ("temperature", "3"),      # hors borne haute
    ("temperature", "-1"),     # hors borne basse
    ("temperature", "chaud"),  # pas un nombre
    ("inconnu", "1"),          # réglage inexistant
])
def test_rejects_invalid(key, value):
    with pytest.raises(ValueError):
        set_param({}, key, value)
