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

# On repart toujours d'un Ollama propre, pointé sur la clé. Si une instance
# tourne déjà (service système OU "ollama serve" resté en mémoire d'un essai
# précédent), elle répond sur le port 11434 mais avec SON dossier de modèles
# à elle, pas forcément celui de la clé — d'où une liste de modèles vide ou
# fausse. On l'arrête donc systématiquement avant de relancer.
if systemctl is-active --quiet ollama 2>/dev/null; then
    echo "Arrêt du service ollama système..."
    sudo systemctl stop ollama
fi
if pgrep -f "ollama serve" >/dev/null 2>&1; then
    echo "Arrêt d'une instance ollama déjà en mémoire..."
    pkill -f "ollama serve" || true
fi
# Attend que le port se libère avant de relancer (jusqu'à 10s).
for _ in $(seq 1 10); do
    curl -s -o /dev/null http://localhost:11434/api/tags || break
    sleep 1
done

# Relance Ollama en arrière-plan, pointé uniquement sur la clé.
export OLLAMA_MODELS="$MODELS"
echo "Démarrage d'Ollama sur les modèles de la clé..."
nohup ollama serve >"$CLE/ollama.log" 2>&1 &
# Une clé USB est plus lente qu'un disque interne : on attend qu'Ollama
# réponde vraiment au lieu d'un délai fixe (sinon la liste des modèles
# peut apparaître vide alors qu'Ollama démarre encore).
for _ in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:11434/api/tags; then
        break
    fi
    sleep 1
done

echo "== Modèles disponibles =="
REPONSE=$(curl -s http://localhost:11434/api/tags)
echo "$REPONSE" | grep -o '"name":"[^"]*"' || true
if ! echo "$REPONSE" | grep -q '"name":"'; then
    echo "(aucun modèle trouvé — regarde $CLE/ollama.log si ça persiste)"
fi

echo
echo "== Lancement du menu LexOS Pro =="
cd "$CLE/ti-lex-ia-REA-"

# Pas de .venv sur la clé : exFAT ne supporte pas les liens symboliques que
# "python3 -m venv" essaie toujours de créer (même avec --copies, sur
# Debian/LexOS Pro). On utilise plutôt "pip install --target", qui installe
# le projet et ses dépendances comme de simples fichiers (aucun lien
# symbolique, aucun script avec un chemin codé en dur) dans un dossier
# "deps/" juste à côté. Voir le README, section "Vider le PC".
if [ ! -d "deps/ti_lex_agent" ]; then
    echo "Erreur : deps/ n'existe pas ou est incomplet."
    echo "Lance d'abord, une seule fois, depuis cette clé :"
    echo "  cd $CLE/ti-lex-ia-REA-"
    echo "  python3 -m pip install --target=deps --upgrade ."
    exit 1
fi
export PYTHONPATH="$CLE/ti-lex-ia-REA-/deps${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m ti_lex_agent.launcher
