"""Prendre une capture d'écran avec l'outil disponible sur le système.

On essaie plusieurs outils courants (scrot, xfce4-screenshooter, maim, etc.)
dans l'ordre, puis, en dernier recours, la bibliothèque Python « mss » si elle
est installée. Aucune dépendance n'est imposée : si rien n'est trouvé, on lève
une erreur claire qui dit quoi installer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ScreenshotError(Exception):
    pass


# (commande, fonction qui construit les arguments pour un fichier de sortie)
_TOOLS = [
    ("scrot", lambda out: ["scrot", "-o", out]),
    ("maim", lambda out: ["maim", out]),
    ("xfce4-screenshooter", lambda out: ["xfce4-screenshooter", "-f", "-s", out]),
    ("gnome-screenshot", lambda out: ["gnome-screenshot", "-f", out]),
    ("spectacle", lambda out: ["spectacle", "-b", "-n", "-o", out]),
    ("grim", lambda out: ["grim", out]),           # Wayland
    ("import", lambda out: ["import", "-window", "root", out]),  # ImageMagick
]


def available_tool() -> str | None:
    """Retourne le nom du premier outil de capture présent, ou None."""
    for name, _build in _TOOLS:
        if shutil.which(name):
            return name
    try:
        import mss  # noqa: F401
        return "mss"
    except Exception:
        return None


def take_screenshot(dest: Path) -> Path:
    """Capture tout l'écran vers `dest` (PNG). Lève ScreenshotError si impossible."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for name, build in _TOOLS:
        if not shutil.which(name):
            continue
        try:
            r = subprocess.run(build(str(dest)), capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return dest
    # Dernier recours : mss (si installé).
    try:
        import mss
        with mss.mss() as sct:
            sct.shot(output=str(dest))
        if dest.exists() and dest.stat().st_size > 0:
            return dest
    except Exception:
        pass
    raise ScreenshotError(
        "Aucun outil de capture trouvé. Installe-en un, par ex. : sudo apt install scrot"
    )
