"""Réglages de génération du modèle (température, etc.), modifiables en direct."""

from __future__ import annotations

# nom -> (type, minimum, maximum, explication)
PARAMS: dict[str, tuple[type, float, float, str]] = {
    "temperature": (float, 0.0, 2.0, "créativité : bas = précis et stable, haut = varié"),
    "top_p": (float, 0.0, 1.0, "garde seulement les mots les plus probables (0.9 typique)"),
    "top_k": (int, 0, 1000, "nombre de mots candidats à chaque étape (0 = pas de limite)"),
    "repeat_penalty": (float, 0.5, 2.0, "pénalité contre les répétitions (1.1 typique)"),
    "num_ctx": (int, 512, 131072, "taille de la mémoire de conversation, en tokens"),
    "seed": (int, 0, 2**31 - 1, "graine : même graine = mêmes réponses"),
}

DEFAULTS: dict[str, float | int] = {"temperature": 0.7}


def set_param(options: dict, key: str, raw: str) -> str:
    """Valide et applique un réglage. Retourne un message ; lève ValueError si invalide."""
    if key not in PARAMS:
        raise ValueError(f"Réglage inconnu « {key} ». Possibles : {', '.join(PARAMS)}.")
    kind, low, high, _ = PARAMS[key]
    try:
        value = kind(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"« {raw} » n'est pas un nombre valide pour {key}.") from None
    if not low <= value <= high:
        raise ValueError(f"{key} doit être entre {low:g} et {high:g}.")
    options[key] = value
    return f"{key} = {value}"


def describe(options: dict) -> str:
    lines = []
    for key, (_, low, high, text) in PARAMS.items():
        current = options.get(key, "(défaut du modèle)")
        lines.append(f"  {key:15} {current!s:20} [{low:g} à {high:g}]  {text}")
    return "\n".join(lines)
