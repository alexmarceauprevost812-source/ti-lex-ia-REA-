#!/usr/bin/env bash
# Point d'entrée unique : trouve sa propre clé (peu importe le point de
# montage), puis lance le menu LexOS Pro avec les modèles de la clé.
# Double-clic depuis le gestionnaire de fichiers, ou :  bash LANCER-LEXOS-PRO.sh
set -euo pipefail

# $BASH_SOURCE pointe sur ce fichier lui-même : son dossier EST la racine de
# la clé, peu importe où elle est montée (/media/..., /run/media/..., etc.)
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$RACINE/ti-lex-ia-REA-" ]; then
    echo "Erreur : le dossier ti-lex-ia-REA- n'est pas à côté de ce fichier ($RACINE)."
    echo "Vérifie que le projet a bien été copié sur la clé (voir le README)."
    read -r -p "Appuie sur Entrée pour fermer..."
    exit 1
fi

bash "$RACINE/ti-lex-ia-REA-/scripts/demarrer-lexos-usb.sh" "$RACINE"
echo
read -r -p "Appuie sur Entrée pour fermer..."
