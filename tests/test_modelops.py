import pytest

from ti_lex_agent.config import Config
from ti_lex_agent.modelops import ModelOpsError, import_to_ollama, run_heretic


def test_run_heretic_rejects_bad_model_name():
    with pytest.raises(ModelOpsError, match="invalide"):
        run_heretic("--rm -rf /", confirm=lambda _q: True)


def test_run_heretic_cancelled_by_user():
    with pytest.raises(ModelOpsError, match="Annulé"):
        run_heretic("Qwen/Qwen3-4B-Instruct-2507", confirm=lambda _q: False)


def test_import_rejects_bad_name(tmp_path):
    with pytest.raises(ModelOpsError, match="invalide"):
        import_to_ollama(str(tmp_path), "Pas Valide!", Config(workspace=tmp_path),
                         confirm=lambda _q: True)


def test_import_rejects_missing_folder(tmp_path):
    with pytest.raises(ModelOpsError, match="Introuvable"):
        import_to_ollama(str(tmp_path / "absent"), "mon-modele", Config(workspace=tmp_path),
                         confirm=lambda _q: True)


def test_import_rejects_folder_without_model_files(tmp_path):
    empty = tmp_path / "pas_un_modele"
    empty.mkdir()
    with pytest.raises(ModelOpsError, match="modèle"):
        import_to_ollama(str(empty), "mon-modele", Config(workspace=tmp_path),
                         confirm=lambda _q: True)


def test_import_cancelled_by_user(tmp_path):
    folder = tmp_path / "modele"
    folder.mkdir()
    (folder / "config.json").write_text("{}")
    with pytest.raises(ModelOpsError, match="Annulé"):
        import_to_ollama(str(folder), "mon-modele", Config(workspace=tmp_path),
                         confirm=lambda _q: False)
