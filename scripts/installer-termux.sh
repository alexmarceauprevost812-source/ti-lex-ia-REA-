#!/usr/bin/env bash
# Installe « ti-lex » (l'interface REA / Codex / Chat / TerminalCodex) dans TERMUX,
# sur un téléphone Android. Relançable sans risque (sert aussi à mettre à jour).
#
#   bash scripts/installer-termux.sh                 # IA sur le téléphone (Ollama de Termux)
#   bash scripts/installer-termux.sh 192.168.0.42    # IA de ton PC, par le WiFi
#   bash scripts/installer-termux.sh 192.168.0.42 11434   # port précis
#
# Avec l'IP du PC, le téléphone n'exécute aucun modèle : il envoie tes messages au PC.
# Sur le PC, Ollama doit écouter le WiFi (OLLAMA_HOST=0.0.0.0, ou
# LEXOS_OLLAMA_BIND=0.0.0.0 avec scripts/demarrer-lexos-usb.sh).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="${TILEX_PKG:-pkg}"          # remplaçables pour les tests
PY="${TILEX_PYTHON:-python}"
IP="${1:-}"
PORT="${2:-}"

case "${PREFIX:-}" in
    *com.termux*) ;;
    *) echo "(Attention : ça ne ressemble pas à Termux ; je continue quand même.)" ;;
esac

echo "1/4  Paquets Termux (python, git, curl)…"
"$PKG" install -y python git curl >/dev/null

echo "2/4  Environnement Python du projet (.venv)…"
cd "$REPO"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
if [ -z "${TILEX_SKIP_PIP:-}" ]; then
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q requests "textual>=1.0"
    # --no-deps : « ddgs » (recherche web) ne se compile pas toujours sur un téléphone ;
    # on l'essaie à part, et tout le reste marche sans lui.
    .venv/bin/pip install -q --no-deps -e .
    if ! .venv/bin/pip install -q ddgs >/dev/null 2>&1; then
        echo "     (la recherche web de REA n'a pas pu s'installer ici : le reste marche sans elle)"
    fi
fi

echo "3/4  Où tourne l'IA…"
START="# >>> ti-lex termux >>>"; END="# <<< ti-lex termux <<<"
touch "$HOME/.bashrc"
sed -i "/$START/,/$END/d" "$HOME/.bashrc"
if [ -n "$IP" ]; then
    if [ -z "$PORT" ]; then              # le port qui répond : 11435 (clé USB) ou 11434 (normal)
        PORT=11435
        for p in 11435 11434; do
            if curl -s -m 3 -o /dev/null "http://$IP:$p/api/tags"; then PORT=$p; break; fi
        done
    fi
    HOST="http://$IP:$PORT"
    printf '%s\nexport OLLAMA_HOST="%s"\n%s\n' "$START" "$HOST" "$END" >> "$HOME/.bashrc"
    echo "     IA du PC : $HOST"
    if ! curl -s -m 3 -o /dev/null "$HOST/api/tags"; then
        echo "     Attention : le PC ne répond pas encore. Vérifie le même WiFi, l'IP,"
        echo "     et qu'Ollama écoute le réseau sur le PC (OLLAMA_HOST=0.0.0.0)."
    fi
else
    echo "     IA sur le téléphone. Si ce n'est pas déjà fait :"
    echo "       pkg install ollama        puis, dans une autre session Termux :  ollama serve"
    echo "       ollama pull qwen3:1.7b    (un petit modèle ; ti-lex le prend tout seul)"
fi

echo "4/4  Raccourci ti-lex…"
bash "$REPO/scripts/installer-raccourci.sh"
echo
echo "Fini. Ferme et rouvre Termux (ou tape : exec bash), puis tape  ti-lex"
