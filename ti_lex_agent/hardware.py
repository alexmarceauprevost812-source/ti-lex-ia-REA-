"""Détecte la puissance de l'ordinateur pour choisir les bons moteurs.

Tout le monde n'a pas une RTX 5060 : l'agent regarde la carte graphique et
la mémoire au démarrage, puis classe la machine en trois niveaux.

- fort   : carte graphique NVIDIA avec 8 Go de mémoire vidéo ou plus
- moyen  : carte NVIDIA de 4 à 8 Go, ou Mac Apple Silicon (M1, M2…)
- leger  : pas de carte graphique utilisable — tout roule sur le processeur

Chaque moteur (schémas, images, voix, vidéo) choisit sa version selon ce
niveau. On peut forcer un niveau avec la variable TILEX_NIVEAU (fort, moyen,
leger), par exemple pour tester le mode léger sur un PC puissant.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache

NIVEAUX = ("fort", "moyen", "leger")

_ETIQUETTES = {
    "fort": "fort (carte graphique puissante)",
    "moyen": "moyen (petite carte graphique)",
    "leger": "léger (processeur seulement)",
}


@dataclass(frozen=True)
class Machine:
    niveau: str              # "fort", "moyen" ou "leger"
    gpu: str | None          # nom de la carte graphique, si trouvée
    vram_go: float           # mémoire vidéo en Go (0 si aucune)
    ram_go: float            # mémoire vive en Go (0 si inconnue)
    coeurs: int              # nombre de cœurs du processeur
    systeme: str             # Windows, Linux, Darwin…
    force: bool = False      # niveau imposé par TILEX_NIVEAU

    def resume(self) -> str:
        """Une ligne lisible, affichée au démarrage."""
        carte = f"{self.gpu} ({self.vram_go:g} Go)" if self.gpu else "aucune carte graphique détectée"
        ram = f"{self.ram_go:g} Go de RAM" if self.ram_go else "RAM inconnue"
        texte = f"Machine : niveau {_ETIQUETTES[self.niveau]} — {carte}, {ram}, {self.coeurs} cœurs"
        if self.force:
            texte += " (niveau forcé par TILEX_NIVEAU)"
        return texte


def _nvidia() -> tuple[str | None, float]:
    """Nom et mémoire (Go) de la plus grosse carte NVIDIA, via nvidia-smi."""
    try:
        sortie = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, 0.0
    if sortie.returncode != 0:
        return None, 0.0
    meilleur: tuple[str | None, float] = (None, 0.0)
    for ligne in sortie.stdout.strip().splitlines():
        nom, _, mio = ligne.rpartition(",")
        try:
            go = round(float(mio.strip()) / 1024, 1)
        except ValueError:
            continue
        if go > meilleur[1]:
            meilleur = (nom.strip() or "Carte NVIDIA", go)
    return meilleur


def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _ram_go() -> float:
    """Mémoire vive totale, sans dépendance externe (Linux, Windows, Mac)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                for ligne in f:
                    if ligne.startswith("MemTotal:"):
                        return round(int(ligne.split()[1]) / 1024 / 1024, 1)
        elif sys.platform == "win32":
            import ctypes

            class _Etat(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            etat = _Etat()
            etat.dwLength = ctypes.sizeof(_Etat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):
                return round(etat.ullTotalPhys / 1024 ** 3, 1)
        elif sys.platform == "darwin":
            sortie = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                    text=True, timeout=5)
            return round(int(sortie.stdout.strip()) / 1024 ** 3, 1)
    except (OSError, ValueError, subprocess.TimeoutExpired, AttributeError):
        pass
    return 0.0


def classer(vram_go: float, apple: bool = False) -> str:
    """Règle de classement, séparée pour pouvoir la tester facilement."""
    if vram_go >= 8:
        return "fort"
    if vram_go >= 4 or apple:
        return "moyen"
    return "leger"


@lru_cache(maxsize=1)
def detecter() -> Machine:
    """Analyse la machine une seule fois par lancement (le résultat est gardé)."""
    gpu, vram = _nvidia()
    apple = _apple_silicon()
    if apple and not gpu:
        gpu = f"Apple {platform.processor() or 'Silicon'}"
    niveau = classer(vram, apple)
    force = False
    impose = os.environ.get("TILEX_NIVEAU", "").strip().lower().replace("é", "e")
    if impose in NIVEAUX:
        niveau, force = impose, True
    return Machine(niveau=niveau, gpu=gpu, vram_go=vram, ram_go=_ram_go(),
                   coeurs=os.cpu_count() or 1, systeme=platform.system(), force=force)
