#!/usr/bin/env bash
# Installe Heretic OFFICIEL (p-e-w/heretic) dans un environnement isolé.
# Usage : bash scripts/install_heretic.sh
set -euo pipefail

VENV="${HERETIC_VENV:-$HOME/venvs/heretic}"

echo "== Vérification de la carte graphique =="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "ATTENTION : nvidia-smi introuvable. Installe d'abord le pilote NVIDIA."
    echo "Heretic a besoin d'un GPU pour travailler sur de vrais modèles."
fi

echo "== Installation de uv (gestionnaire Python) =="
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "== Création de l'environnement dans $VENV =="
uv venv "$VENV" --python 3.12
uv pip install -p "$VENV/bin/python" -U heretic-llm

echo
echo "Terminé. Pour l'utiliser :"
echo "  source $VENV/bin/activate"
echo "  heretic Qwen/Qwen3-4B-Instruct-2507"
echo
echo "Ensuite, convertis le modèle obtenu en GGUF pour Ollama (voir README)."
