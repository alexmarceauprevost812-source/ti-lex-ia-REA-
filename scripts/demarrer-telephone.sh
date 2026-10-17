#!/usr/bin/env bash
# Lancer LexOS Pro depuis un TÉLÉPHONE Android (dans Termux), connecté à l'IA
# qui tourne sur ton PC par le WiFi.
#
# Le téléphone ne fait PAS tourner les modèles (trop gros pour un téléphone) :
# il envoie tes messages au PC et affiche la réponse. Sur Android c'est le
# MENU TEXTE qui s'ouvre (la fenêtre graphique a besoin d'un écran de bureau).
#
# Prérequis, une seule fois, dans Termux :
#   pkg install python git
#   (le code du projet : copié depuis la clé, ou  git clone <ton dépôt>)
#
# Côté PC, lance d'abord l'IA en la partageant sur le WiFi :
#   LEXOS_OLLAMA_BIND=0.0.0.0 bash scripts/demarrer-lexos-usb.sh /media/marceau/LEXOS
# puis trouve l'IP du PC avec :  ip a   (ex : 192.168.0.42)
#
# Usage sur le téléphone :
#   bash scripts/demarrer-telephone.sh <IP-du-PC> [port]
#   ex :  bash scripts/demarrer-telephone.sh 192.168.0.42
set -euo pipefail

IP="${1:-}"
PORT="${2:-11435}"
if [ -z "$IP" ]; then
    echo "Usage : bash scripts/demarrer-telephone.sh <IP-du-PC> [port]"
    echo "Trouve l'IP du PC avec « ip a » sur le PC (ex : 192.168.0.42)."
    echo "Et assure-toi d'avoir lancé le PC avec LEXOS_OLLAMA_BIND=0.0.0.0."
    exit 1
fi

export OLLAMA_HOST="http://$IP:$PORT"

# Les dépendances du téléphone (ARM) sont séparées de celles de la clé (PC/x86).
# On les installe ici si besoin — c'est léger (pas de modèle à télécharger).
if ! python -c "import requests, ddgs" >/dev/null 2>&1; then
    echo "Installation des dépendances du téléphone (une seule fois)..."
    pip install requests ddgs
fi

# Se place à la racine du projet (ce script est dans scripts/).
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Vérifie qu'on joint bien le PC avant d'ouvrir le menu.
if ! curl -s -o /dev/null "$OLLAMA_HOST/api/tags" 2>/dev/null; then
    echo "Attention : impossible de joindre $OLLAMA_HOST."
    echo "Vérifie que : le PC et le téléphone sont sur le MÊME WiFi,"
    echo "le PC tourne avec LEXOS_OLLAMA_BIND=0.0.0.0, et que l'IP est la bonne."
fi

echo "Connexion à l'IA du PC : $OLLAMA_HOST"
exec python -m ti_lex_agent.launcher
