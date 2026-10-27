"""Tests du détecteur de machine et du moteur de schémas (sans Ollama ni internet)."""

import pytest

from ti_lex_agent import hardware, schema
from ti_lex_agent.config import Config
from ti_lex_agent.tools import Toolbox


class _Client:
    def chat(self, *a, **k):
        raise AssertionError("pas utilisé")


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "trouver_mmdc", lambda _m: None)  # pas de mmdc dans les tests
    return Config(workspace=tmp_path / "ws", moteurs=tmp_path / "moteurs")


def toolbox(config, answer=True):
    return Toolbox(config, _Client(), confirm=lambda _q: answer)


# ------------------------------------------------------------------ machine
@pytest.mark.parametrize("vram, apple, attendu", [
    (16, False, "fort"), (8, False, "fort"), (6, False, "moyen"),
    (0, True, "moyen"), (2, False, "leger"), (0, False, "leger"),
])
def test_classer(vram, apple, attendu):
    assert hardware.classer(vram, apple) == attendu


def test_detecter_sans_carte(monkeypatch):
    hardware.detecter.cache_clear()
    monkeypatch.setattr(hardware, "_nvidia", lambda: (None, 0.0))
    monkeypatch.setattr(hardware, "_apple_silicon", lambda: False)
    monkeypatch.delenv("TILEX_NIVEAU", raising=False)
    m = hardware.detecter()
    assert m.niveau == "leger" and "aucune carte" in m.resume()
    hardware.detecter.cache_clear()


def test_niveau_force(monkeypatch):
    hardware.detecter.cache_clear()
    monkeypatch.setattr(hardware, "_nvidia", lambda: ("NVIDIA GeForce RTX 5060", 8.0))
    monkeypatch.setenv("TILEX_NIVEAU", "léger")
    m = hardware.detecter()
    assert m.niveau == "leger" and m.force and "forcé" in m.resume()
    hardware.detecter.cache_clear()


# ------------------------------------------------------------------ schémas
def test_nettoyer_enleve_les_backticks():
    assert schema.nettoyer("```mermaid\nflowchart TD\n A-->B\n```") == "flowchart TD\n A-->B"


def test_nettoyer_refuse_un_mauvais_type():
    with pytest.raises(schema.SchemaError, match="flowchart"):
        schema.nettoyer("bonjour --> monde")


def test_nom_sur():
    assert schema.nom_sur("../../plan projet!") == "plan-projet"
    assert schema.nom_sur("???") == "schema"


def test_draw_diagram_cree_mmd_et_html(config):
    out = toolbox(config).call("draw_diagram", {
        "code": "flowchart TD\n A[Idée <b>] --> B[Code]", "name": "plan", "title": "Mon plan"})
    assert "schemas/plan.html" in out.replace("\\", "/")
    page = (config.workspace / "schemas" / "plan.html").read_text(encoding="utf-8")
    assert "Idée &lt;b&gt;" in page          # le code est échappé
    assert "Mon plan" in page
    assert schema.CDN in page                # pas de mermaid local -> CDN
    assert (config.workspace / "schemas" / "plan.mmd").is_file()


def test_draw_diagram_utilise_mermaid_local(config):
    js = config.moteurs / "mermaid" / "mermaid.min.js"
    js.parent.mkdir(parents=True)
    js.write_text("var mermaid={initialize(){}};'</script>'", encoding="utf-8")
    toolbox(config).call("draw_diagram", {"code": "pie\n \"a\": 1", "name": "hors-ligne"})
    page = (config.workspace / "schemas" / "hors-ligne.html").read_text(encoding="utf-8")
    assert schema.CDN not in page and "<\\/script>" in page


def test_draw_diagram_demande_avant_de_remplacer(config):
    t = toolbox(config, answer=False)
    t.call("draw_diagram", {"code": "flowchart TD\n A-->B", "name": "x"})
    assert "refusé" in t.call("draw_diagram", {"code": "flowchart TD\n A-->C", "name": "x"})


def test_draw_diagram_demande_si_seul_le_mmd_existe(config):
    dossier = config.workspace / "schemas"
    dossier.mkdir(parents=True)
    (dossier / "plan.mmd").write_text("source à la main", encoding="utf-8")
    out = toolbox(config, answer=False).call("draw_diagram", {"code": "flowchart TD\n A-->B", "name": "plan"})
    assert "refusé" in out
    assert (dossier / "plan.mmd").read_text(encoding="utf-8") == "source à la main"


def test_draw_diagram_refuse_un_lien_vers_l_exterieur(config, tmp_path):
    dehors = tmp_path / "dehors.txt"
    dehors.write_text("intact", encoding="utf-8")
    dossier = config.workspace / "schemas"
    dossier.mkdir(parents=True)
    try:
        (dossier / "fuite.mmd").symlink_to(dehors)
    except OSError:
        pytest.skip("liens symboliques non disponibles")
    out = toolbox(config).call("draw_diagram", {"code": "flowchart TD\n A-->B", "name": "fuite"})
    assert "en dehors" in out
    assert dehors.read_text(encoding="utf-8") == "intact"


def test_draw_diagram_refuse_une_base_en_lien(config, tmp_path):
    """schemas/plan -> autre/actual, et autre/actual.mmd -> fichier extérieur."""
    dehors = tmp_path / "dehors.txt"
    dehors.write_text("intact", encoding="utf-8")
    autre = config.workspace / "autre"
    autre.mkdir(parents=True)
    dossier = config.workspace / "schemas"
    dossier.mkdir()
    try:
        (autre / "actual.mmd").symlink_to(dehors)
        (dossier / "plan").symlink_to(autre / "actual")
    except OSError:
        pytest.skip("liens symboliques non disponibles")
    toolbox(config).call("draw_diagram", {"code": "flowchart TD\n A-->B", "name": "plan"})
    assert dehors.read_text(encoding="utf-8") == "intact"


def test_draw_diagram_refuse_un_dossier_schemas_en_lien(config, tmp_path):
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    config.workspace.mkdir(parents=True, exist_ok=True)
    try:
        (config.workspace / "schemas").symlink_to(dehors, target_is_directory=True)
    except OSError:
        pytest.skip("liens symboliques non disponibles")
    out = toolbox(config).call("draw_diagram", {"code": "flowchart TD\n A-->B", "name": "x"})
    assert "en dehors" in out and not any(dehors.iterdir())


def test_draw_diagram_erreur_lisible(config):
    assert "n'est pas un type" in toolbox(config).call("draw_diagram", {"code": "salut"})


def test_machine_info(config, monkeypatch):
    hardware.detecter.cache_clear()
    monkeypatch.setattr(hardware, "_nvidia", lambda: (None, 0.0))
    monkeypatch.setattr(hardware, "_apple_silicon", lambda: False)
    monkeypatch.delenv("TILEX_NIVEAU", raising=False)
    assert "léger" in toolbox(config).call("machine_info", {})
    hardware.detecter.cache_clear()
