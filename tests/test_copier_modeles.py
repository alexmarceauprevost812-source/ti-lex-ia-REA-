"""Tests de l'outil de copie sélective de modèles Ollama vers la clé USB."""

import importlib.util
import json
import os
from pathlib import Path

# Le script n'est pas dans le package ti_lex_agent : on le charge par chemin.
_SPEC = importlib.util.spec_from_file_location(
    "copier_modeles_usb",
    Path(__file__).resolve().parent.parent / "scripts" / "copier-modeles-usb.py",
)
copier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(copier)


def _make_source(root: Path) -> Path:
    """Construit un faux dépôt Ollama : heretic via un lien symbolique (v2),
    qwen3 via un fichier normal (ancien style)."""
    blobs = root / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-cfgher").write_text("cfg-her")
    (blobs / "sha256-wher").write_bytes(b"\x00" * 2000)
    (blobs / "sha256-cfgqwen").write_text("cfg-qwen")
    (blobs / "sha256-wqwen").write_bytes(b"\x00" * 3000)
    # commun aux deux modèles, pour tester la déduplication
    (blobs / "sha256-commun").write_bytes(b"\x00" * 500)

    (blobs / "sha256-manifher").write_text(json.dumps(
        {"config": {"digest": "sha256:cfgher"},
         "layers": [{"digest": "sha256:wher"}, {"digest": "sha256:commun"}]}
    ))
    her_dir = root / "manifests-v2/ollama.com/library/heretic"
    her_dir.mkdir(parents=True)
    os.symlink("../../../../blobs/sha256-manifher", her_dir / "latest")

    qwen_dir = root / "manifests/registry.ollama.ai/library/qwen3"
    qwen_dir.mkdir(parents=True)
    (qwen_dir / "8b").write_text(json.dumps(
        {"config": {"digest": "sha256:cfgqwen"},
         "layers": [{"digest": "sha256:wqwen"}, {"digest": "sha256:commun"}]}
    ))
    return root


def test_copies_only_requested_model(tmp_path):
    source = _make_source(tmp_path / "src")
    dest = tmp_path / "usb"
    copied: set[str] = set()
    assert copier.copy_model(source, dest, "heretic:latest", copied) is True

    # Le manifeste est copié en FICHIER NORMAL (pas un lien), lisible tel quel.
    manifest = dest / "manifests-v2/ollama.com/library/heretic/latest"
    assert manifest.is_file() and not manifest.is_symlink()
    assert json.loads(manifest.read_text())["config"]["digest"] == "sha256:cfgher"
    # Seuls les blobs de heretic sont là, pas ceux de qwen.
    assert (dest / "blobs/sha256-cfgher").exists()
    assert (dest / "blobs/sha256-wher").exists()
    assert not (dest / "blobs/sha256-wqwen").exists()


def test_old_style_manifest_regular_file(tmp_path):
    source = _make_source(tmp_path / "src")
    dest = tmp_path / "usb"
    assert copier.copy_model(source, dest, "qwen3:8b", set()) is True
    assert (dest / "manifests/registry.ollama.ai/library/qwen3/8b").is_file()
    assert (dest / "blobs/sha256-wqwen").exists()


def test_shared_blob_copied_once(tmp_path):
    source = _make_source(tmp_path / "src")
    dest = tmp_path / "usb"
    copied: set[str] = set()
    copier.copy_model(source, dest, "heretic:latest", copied)
    copier.copy_model(source, dest, "qwen3:8b", copied)
    # Le blob commun n'est compté qu'une fois.
    assert "sha256-commun" in copied
    assert (dest / "blobs/sha256-commun").exists()


def test_missing_model_returns_false(tmp_path):
    source = _make_source(tmp_path / "src")
    assert copier.copy_model(source, tmp_path / "usb", "inexistant:latest", set()) is False


def test_main_rejects_non_ollama_source(tmp_path, capsys):
    rc = copier.main([str(tmp_path / "usb"), "heretic:latest", "--source", str(tmp_path / "vide")])
    assert rc == 1
    assert "blobs" in capsys.readouterr().out
