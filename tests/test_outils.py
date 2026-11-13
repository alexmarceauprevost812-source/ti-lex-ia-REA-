"""Tests de la bibliothèque « Outils créés », du clonage et des nouveaux projets."""

import subprocess

import pytest

from ti_lex_agent import outils
from ti_lex_agent.config import Config


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("TILEX_OUTILS", raising=False)
    return Config(workspace=tmp_path / "workspace")


def test_bibliotheque_vide_explique_comment_ajouter(config):
    assert outils.load(config) == []
    assert "/ajouter-outil" in outils.describe(config)


def test_ajouter_trouver_retirer(config):
    assert "ajouté" in outils.add(config, "Salut", "echo allo")
    assert outils.find(config, "salut")["commande"] == "echo allo"
    assert "mis à jour" in outils.add(config, "salut", "echo bonjour")
    assert len(outils.load(config)) == 1
    assert "Salut" not in outils.describe(config) and "echo bonjour" in outils.describe(config)
    assert "retiré" in outils.remove(config, "SALUT")
    with pytest.raises(outils.OutilError):
        outils.remove(config, "salut")


def test_ajouter_refuse_nom_ou_commande_vide(config):
    with pytest.raises(outils.OutilError):
        outils.add(config, "", "echo x")
    with pytest.raises(outils.OutilError):
        outils.add(config, "x", "  ")


def test_fichier_abime(config):
    outils.outils_path(config).write_text("{pas du json", encoding="utf-8")
    with pytest.raises(outils.OutilError, match="abîmé"):
        outils.load(config)


def test_run_captured_dans_le_dossier_de_travail(config):
    code, out = outils.run_captured(config, "pwd && echo fini")
    assert code == 0 and out.splitlines() == [str(config.workspace), "fini"]


@pytest.mark.parametrize("url,attendu", [
    ("proprio/depot", "https://github.com/proprio/depot"),
    ("https://github.com/a/b.git", "https://github.com/a/b.git"),
    ("git@github.com:a/b.git", "git@github.com:a/b.git"),
])
def test_adresses_acceptees(url, attendu):
    assert outils.normalize_repo_url(url) == attendu


@pytest.mark.parametrize("url", ["", "../x", "--upload-pack=x", "file:///etc/passwd",
                                 "http://exemple.com/a/b", "ext::sh -c id", "a b/c"])
def test_adresses_refusees(url):
    with pytest.raises(outils.OutilError):
        outils.normalize_repo_url(url)


def test_nouveau_projet(config):
    target = outils.new_project(config, "mon-site")
    assert target == config.workspace / "mon-site"
    assert (target / "README.md").read_text(encoding="utf-8").startswith("# mon-site")
    assert (target / ".git").is_dir()
    with pytest.raises(outils.OutilError, match="existe déjà"):
        outils.new_project(config, "mon-site")


@pytest.mark.parametrize("nom", ["", "../dehors", "a/b", "-rf", "nom avec espace"])
def test_nouveau_projet_refuse_les_noms_dangereux(config, nom):
    with pytest.raises(outils.OutilError):
        outils.new_project(config, nom)
    assert list(config.workspace.iterdir()) == []


def test_cloner_un_depot_local(config, tmp_path, monkeypatch):
    """Clone réel, sans internet : on fait passer un dépôt local pour l'adresse."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "README.md").write_text("# source\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(src), *cmd], check=True, capture_output=True)
    monkeypatch.setattr(outils, "normalize_repo_url", lambda url: str(src))
    target = outils.clone(config, "proprio/source")
    assert target == config.workspace / "source"
    assert (target / "README.md").is_file()
    with pytest.raises(outils.OutilError, match="existe déjà"):
        outils.clone(config, "proprio/source")


def test_cloner_echec_ne_laisse_rien(config, tmp_path, monkeypatch):
    monkeypatch.setattr(outils, "normalize_repo_url", lambda url: str(tmp_path / "nexiste-pas"))
    with pytest.raises(outils.OutilError, match="Clonage impossible"):
        outils.clone(config, "proprio/rien", "rien")
    assert not (config.workspace / "rien").exists()
