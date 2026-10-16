import pytest

from ti_lex_agent.config import Config
from ti_lex_agent.modelops import (
    ModelOpsError, copy_model, create_variant, delete_model,
    import_to_ollama, pull_model, run_heretic,
)


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


# --- nouvelles opérations de gestion de modèles -------------------------------

def test_copy_rejects_bad_dest_name():
    with pytest.raises(ModelOpsError, match="invalide"):
        copy_model("qwen3:8b", "Pas Valide!", confirm=lambda _q: True)


def test_copy_cancelled():
    with pytest.raises(ModelOpsError, match="Annulé"):
        copy_model("qwen3:8b", "qwen3-copie", confirm=lambda _q: False)


def test_delete_cancelled():
    with pytest.raises(ModelOpsError, match="Annulé"):
        delete_model("qwen3:8b", confirm=lambda _q: False)


def test_pull_rejects_bad_name():
    with pytest.raises(ModelOpsError, match="invalide"):
        pull_model("-- rm", confirm=lambda _q: True)


def test_pull_cancelled():
    with pytest.raises(ModelOpsError, match="Annulé"):
        pull_model("llama3.2:1b", confirm=lambda _q: False)


def test_variant_rejects_bad_name(tmp_path):
    with pytest.raises(ModelOpsError, match="invalide"):
        create_variant("qwen3:8b", "Mauvais Nom", "sois bref", 0.7,
                       Config(workspace=tmp_path), confirm=lambda _q: True)


def test_variant_rejects_bad_temperature(tmp_path):
    with pytest.raises(ModelOpsError, match="[Tt]emp"):
        create_variant("qwen3:8b", "qwen3-chaud", "", 9.0,
                       Config(workspace=tmp_path), confirm=lambda _q: True)


def test_variant_needs_a_change(tmp_path):
    with pytest.raises(ModelOpsError, match="Rien à changer"):
        create_variant("qwen3:8b", "qwen3-vide", "", None,
                       Config(workspace=tmp_path), confirm=lambda _q: True)


def test_variant_cancelled(tmp_path):
    with pytest.raises(ModelOpsError, match="Annulé"):
        create_variant("qwen3:8b", "qwen3-quebec", "Réponds en québécois.", 0.7,
                       Config(workspace=tmp_path), confirm=lambda _q: False)
