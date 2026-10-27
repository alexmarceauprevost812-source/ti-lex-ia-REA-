"""Moteur de schémas : l'IA écrit un diagramme en Mermaid, on en fait une image.

Les modèles locaux ne savent pas dessiner, mais ils savent très bien écrire du
texte. Mermaid est un petit langage texte pour les diagrammes :

    flowchart TD
        A[Idée] --> B[Code] --> C[Test]

Ce moteur marche sur TOUS les ordinateurs (niveau léger compris), parce que
c'est le navigateur qui dessine, pas la carte graphique.

Ce qu'il produit, à partir d'un nom comme « plan » :
- plan.mmd  : le texte du diagramme (modifiable à la main)
- plan.html : une page qui affiche le schéma — s'ouvre dans n'importe quel navigateur
- plan.png  : une vraie image, seulement si mermaid-cli (mmdc) est installé

Pour que la page marche SANS internet, copie mermaid.min.js dans
moteurs/mermaid/mermaid.min.js sur la clé. Sinon, la page le charge depuis
internet (cdn.jsdelivr.net) quand on l'ouvre.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
from pathlib import Path

CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

# Premiers mots acceptés par Mermaid (le type de diagramme).
TYPES = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "gantt", "pie", "mindmap", "timeline",
    "journey", "gitGraph", "quadrantChart", "requirementDiagram", "block-beta",
    "sankey-beta", "xychart-beta", "kanban", "architecture-beta",
)

_PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column;
         align-items: center; background: #101418; color: #d7e0e6;
         font-family: system-ui, sans-serif; }}
  h1 {{ font-size: 1.1rem; font-weight: 600; margin: 24px 16px 8px; color: #7ee787; }}
  .carte {{ background: #161b22; border: 1px solid #2d333b; border-radius: 12px;
           padding: 24px; margin: 16px; max-width: calc(100vw - 32px); overflow: auto; }}
  .note {{ font-size: .8rem; color: #8b949e; margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>{titre}</h1>
<div class="carte"><pre class="mermaid">{code}</pre></div>
<div class="note">Schéma généré par Ti-Lex · source : {fichier_mmd}</div>
{script}
<script>mermaid.initialize({{ startOnLoad: true, theme: "dark", securityLevel: "strict" }});</script>
</body>
</html>
"""


class SchemaError(Exception):
    """Diagramme invalide : le message explique au modèle comment corriger."""


def nettoyer(code: str) -> str:
    """Enlève les ```mermaid ... ``` que les modèles ajoutent souvent."""
    code = code.strip()
    bloc = re.match(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", code, re.DOTALL)
    if bloc:
        code = bloc.group(1).strip()
    if not code:
        raise SchemaError("Le diagramme est vide.")
    premier = code.split()[0]
    if premier.startswith("%%"):   # directive ou commentaire au début : on accepte
        return code
    if premier not in TYPES:
        raise SchemaError(
            f"« {premier} » n'est pas un type de diagramme Mermaid. Commence par un de ceux-ci : "
            "flowchart TD, sequenceDiagram, classDiagram, erDiagram, gantt, pie, mindmap, timeline."
        )
    return code


def nom_sur(nom: str) -> str:
    """Un nom de fichier simple : lettres, chiffres, - et _ seulement."""
    nom = re.sub(r"[^\w\-]+", "-", nom.strip(), flags=re.UNICODE).strip("-_")
    return nom[:60] or "schema"


def _script(moteurs: Path) -> str:
    local = moteurs / "mermaid" / "mermaid.min.js"
    if local.is_file():
        js = local.read_text(encoding="utf-8", errors="replace")
        return "<script>" + js.replace("</script", "<\\/script") + "</script>"
    return f'<script src="{CDN}"></script>'


def trouver_mmdc(moteurs: Path) -> str | None:
    """mermaid-cli : sur la clé (moteurs/mermaid-cli) ou installé sur l'ordi."""
    for candidat in ("mmdc.cmd", "mmdc"):
        for dossier in (moteurs / "mermaid-cli" / "node_modules" / ".bin", moteurs / "mermaid-cli"):
            chemin = dossier / candidat
            if chemin.is_file():
                return str(chemin)
    return shutil.which("mmdc")


def dessiner(code: str, base: Path, moteurs: Path, titre: str | None = None) -> list[Path]:
    """Écrit base.mmd + base.html (+ base.png si possible). Retourne les fichiers créés."""
    code = nettoyer(code)
    base.parent.mkdir(parents=True, exist_ok=True)
    mmd = base.with_suffix(".mmd")
    page = base.with_suffix(".html")
    mmd.write_text(code + "\n", encoding="utf-8")
    page.write_text(_PAGE.format(
        titre=html.escape(titre or base.name), code=html.escape(code),
        fichier_mmd=html.escape(mmd.name), script=_script(moteurs),
    ), encoding="utf-8")
    crees = [mmd, page]

    mmdc = trouver_mmdc(moteurs)
    if mmdc:
        png = base.with_suffix(".png")
        try:
            fait = subprocess.run([mmdc, "-i", str(mmd), "-o", str(png), "-b", "white", "-q"],
                                  capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired):
            fait = None
        if fait is not None and fait.returncode == 0 and png.is_file():
            crees.append(png)
        elif fait is not None and fait.returncode != 0:
            erreur = (fait.stderr or fait.stdout).strip().splitlines()
            raise SchemaError("Mermaid a refusé le diagramme : "
                              + (erreur[-1] if erreur else "erreur inconnue")
                              + f". La page {page.name} a quand même été écrite.")
    return crees
