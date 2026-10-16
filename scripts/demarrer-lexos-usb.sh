#!/usr/bin/env bash
# Démarre Ollama en pointant SEULEMENT sur les modèles de la clé USB-C
# (rien sur le disque interne), puis lance le menu LexOS Pro.
#
# Usage : bash scripts/demarrer-lexos-usb.sh [chemin-de-la-cle]
# Par défaut, cherche la clé montée sous un nom contenant "LEXOS".
set -euo pipefail

CLE="${1:-}"
if [ -z "$CLE" ]; then
    CLE=$(find /media/*/ /run/media/*/*/ -maxdepth 0 -iname "*LEXOS*" 2>/dev/null | head -n1 || true)
fi
if [ -z "$CLE" ] || [ ! -d "$CLE" ]; then
    echo "Clé USB introuvable. Branche-la et monte-la, ou donne le chemin en argument :"
    echo "  bash $0 /media/marceau/LEXOS"
    exit 1
fi

MODELS="$CLE/ollama-models"
if [ ! -d "$MODELS/manifests" ]; then
    echo "Erreur : $MODELS ne contient pas de modèles Ollama (pas de dossier manifests/)."
    echo "As-tu bien copié /usr/share/ollama/.ollama/models/ vers $MODELS ?"
    exit 1
fi

echo "== Modèles utilisés : $MODELS (PAS le disque interne) =="

# Arrête le service système s'il tourne, pour éviter un conflit de port et pour
# qu'il ne reparte pas tout seul avec l'ancien dossier du disque interne.
if systemctl is-active --quiet ollama 2>/dev/null; then
    echo "Arrêt du service ollama système..."
    sudo systemctl stop ollama
fi

# Relance Ollama en arrière-plan, pointé uniquement sur la clé.
export OLLAMA_MODELS="$MODELS"
if ! curl -s -o /dev/null http://localhost:11434/api/tags; then
    echo "Démarrage d'Ollama sur les modèles de la clé..."
    nohup ollama serve >"$CLE/ollama.log" 2>&1 &
    sleep 2
fi

echo "== Modèles disponibles =="
curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' || true

echo
echo "== Lancement du menu LexOS Pro =="
cd "$CLE/ti-lex-ia-REA-"
source .venv/bin/activate
exec lexos-ia
