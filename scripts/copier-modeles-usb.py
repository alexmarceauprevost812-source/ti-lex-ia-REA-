#!/usr/bin/env python3
"""Copie SEULEMENT les modèles Ollama choisis vers la clé USB-C.

Au lieu de copier tout le dossier de modèles (souvent des dizaines de Go),
cet outil lit le manifeste de chaque modèle demandé, puis copie uniquement
ce manifeste et les blobs qu'il référence. Pratique quand on ne veut garder
sur la clé que les modèles vraiment utilisés par le menu LexOS Pro.

Les manifestes d'Ollama sont parfois des liens symboliques vers un blob, et
exFAT (le format des clés USB) ne sait pas stocker de lien symbolique : on
copie donc toujours le CONTENU réel en fichier normal.

Usage :
    sudo python3 scripts/copier-modeles-usb.py <dossier-modeles-clé> <modèle> [<modèle> ...]

Exemple :
    sudo python3 scripts/copier-modeles-usb.py \\
        /media/marceau/LEXOS/ollama-models \\
        heretic:latest qwen3:8b qwen2.5vl:7b

Option :
    --source <dossier>   dossier des modèles sur le PC
                         (défaut : /usr/share/ollama/.ollama/models)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_SOURCE = "/usr/share/ollama/.ollama/models"

# Emplacements possibles d'un manifeste selon la version d'Ollama.
# {repo} = nom du modèle (ex: heretic), {tag} = étiquette (ex: latest, 8b).
MANIFEST_LAYOUTS = [
    "manifests-v2/ollama.com/library/{repo}/{tag}",
    "manifests/registry.ollama.ai/library/{repo}/{tag}",
]


def digest_to_blob(digest: str) -> str:
    """'sha256:abc...' -> 'sha256-abc...' (nom du fichier blob sur le disque)."""
    return digest.replace(":", "-")


def find_manifest(source: Path, repo: str, tag: str) -> Path | None:
    for layout in MANIFEST_LAYOUTS:
        candidate = source / layout.format(repo=repo, tag=tag)
        if candidate.exists():  # .exists() suit les liens symboliques
            return candidate
    return None


def blob_digests(manifest_data: dict) -> list[str]:
    """Tous les digests référencés par un manifeste : la config + les couches."""
    digests = []
    config = manifest_data.get("config") or {}
    if config.get("digest"):
        digests.append(config["digest"])
    for layer in manifest_data.get("layers") or []:
        if layer.get("digest"):
            digests.append(layer["digest"])
    return digests


def copy_as_regular_file(src: Path, dst: Path) -> int:
    """Copie le CONTENU de src (en suivant les liens) vers dst. Renvoie la taille."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # shutil.copyfile suit les liens symboliques (follow_symlinks=True par défaut)
    # et écrit un fichier normal — exactement ce qu'exFAT accepte.
    shutil.copyfile(src, dst)
    return dst.stat().st_size


def copy_model(source: Path, dest: Path, name: str, copied_blobs: set[str]) -> bool:
    repo, _, tag = name.partition(":")
    tag = tag or "latest"
    manifest_path = find_manifest(source, repo, tag)
    if manifest_path is None:
        print(f"  ✗ {name} : manifeste introuvable dans {source}")
        return False

    try:
        manifest_data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ✗ {name} : manifeste illisible ({exc})")
        return False

    # 1. Copier le manifeste lui-même, à la même place relative, en fichier normal.
    rel_manifest = manifest_path.relative_to(source)
    copy_as_regular_file(manifest_path, dest / rel_manifest)

    # 2. Copier chaque blob référencé (en sautant ceux déjà copiés pour un autre modèle).
    total = 0
    blobs_dir_src = source / "blobs"
    for digest in blob_digests(manifest_data):
        blob_name = digest_to_blob(digest)
        if blob_name in copied_blobs:
            continue
        blob_src = blobs_dir_src / blob_name
        if not blob_src.exists():
            print(f"  ! {name} : blob manquant sur le PC : {blob_name}")
            continue
        total += copy_as_regular_file(blob_src, dest / "blobs" / blob_name)
        copied_blobs.add(blob_name)

    print(f"  ✓ {name}  (+{total / 1e9:.1f} Go de nouveaux blobs)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copie seulement les modèles Ollama choisis vers une clé USB.")
    parser.add_argument("dest", help="dossier ollama-models sur la clé (ex: /media/marceau/LEXOS/ollama-models)")
    parser.add_argument("models", nargs="+", help="modèles à copier (ex: heretic:latest qwen3:8b)")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help=f"dossier des modèles sur le PC (défaut: {DEFAULT_SOURCE})")
    args = parser.parse_args(argv)

    source = Path(args.source)
    dest = Path(args.dest)
    if not (source / "blobs").is_dir():
        print(f"Erreur : {source} ne ressemble pas à un dossier de modèles Ollama (pas de blobs/).")
        return 1
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Source : {source}")
    print(f"Clé    : {dest}\n")
    copied_blobs: set[str] = set()
    ok = 0
    for name in args.models:
        if copy_model(source, dest, name, copied_blobs):
            ok += 1

    print(f"\n{ok}/{len(args.models)} modèle(s) copié(s). Blobs uniques : {len(copied_blobs)}.")
    if ok == 0:
        print("Aucun modèle copié — vérifie les noms avec « ollama list ».")
        return 1
    print("Vérifie ensuite :")
    print(f"  find {dest}/manifests {dest}/manifests-v2 -type f | wc -l   # doit être > 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
