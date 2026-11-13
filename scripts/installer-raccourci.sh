#!/usr/bin/env bash
# Crée la commande « ti-lex » : ouvre l'interface plein écran (REA / Codex / Chat)
# depuis n'importe quel terminal, sans rien activer à la main.
#
#   bash scripts/installer-raccourci.sh
#
# Les modèles par défaut se changent avec TILEX_REA_MODEL, TILEX_CODEX_MODEL et
# TILEX_CHAT_MODEL (par exemple en les mettant devant la commande).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${HOME}/.local/bin"

mkdir -p "$BIN"
cat > "$BIN/ti-lex" <<EOF
#!/usr/bin/env bash
# Raccourci LexOS : interface REA / Codex / Chat. (Ctrl+Q pour quitter.)
cd "$REPO" || exit 1
export TILEX_REA_MODEL="\${TILEX_REA_MODEL:-marceau-ia}"
export TILEX_CODEX_MODEL="\${TILEX_CODEX_MODEL:-marceau-ia}"
export TILEX_CHAT_MODEL="\${TILEX_CHAT_MODEL:-asselin}"
if [ ! -x "$REPO/.venv/bin/lexos-tui" ]; then
    echo "L'interface n'est pas installée. Lance :" >&2
    echo "  cd $REPO && source .venv/bin/activate && pip install -e ." >&2
    exit 1
fi
exec "$REPO/.venv/bin/lexos-tui" "\$@"
EOF
chmod +x "$BIN/ti-lex"

# Un ancien « alias ti-lex » (ex : de l'ancien petit menu terminal-lexos-pro) passe AVANT la
# commande installée ci-dessus : on le retire pour que « ti-lex » ouvre bien cette interface.
for RC in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.bash_aliases" "${HOME}/.profile"; do
    [ -f "$RC" ] || continue
    if grep -qE '^[[:space:]]*(alias (ti-lex|lexos)=|# >>> lexos \(ti-lex\) >>>)' "$RC"; then
        cp "$RC" "$RC.ti-lex.bak"
        sed -i -e '/# >>> lexos (ti-lex) >>>/,/# <<< lexos (ti-lex) <<</d' \
               -e '/^[[:space:]]*alias ti-lex=/d' -e '/^[[:space:]]*alias lexos=/d' "$RC"
        echo "(Ancien alias ti-lex retiré de $RC — sauvegarde : $RC.ti-lex.bak)"
    fi
done

case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        if ! grep -qs '\.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${HOME}/.bashrc"
        fi
        echo "(Le dossier ~/.local/bin a été ajouté au PATH : ouvre un nouveau terminal.)"
        ;;
esac

echo "Prêt : tape  ti-lex  dans n'importe quel terminal."
