"""Résolution de configuration partagée (clé API, dossiers de cours).

Centralise la logique de clé API pour qu'app.py ET les scripts hors-Streamlit
(test batch) la résolvent de la même façon, sans dépendre du runtime Streamlit.
"""

import os
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
COURS_DIR = _ROOT / "cours"


def resolve_api_key() -> str:
    """Résout OPENROUTER_API_KEY : variable d'env, puis .streamlit/secrets.toml.

    Hors Streamlit on ne peut pas utiliser st.secrets ; on lit le fichier
    directement (parsing minimal, sans dépendance toml).
    """
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    secrets = _ROOT / ".streamlit" / "secrets.toml"
    if secrets.exists():
        for line in secrets.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*OPENROUTER_API_KEY\s*=\s*"([^"]*)"', line)
            if m:
                return m.group(1)
    return ""


def liste_cours() -> list[str]:
    """Slugs des cours disponibles (sous-dossiers de cours/ contenant cours.txt)."""
    if not COURS_DIR.exists():
        return []
    return sorted(
        d.name for d in COURS_DIR.iterdir()
        if d.is_dir() and (d / "cours.txt").exists()
    )


def charge_cours(slug: str) -> tuple[str, str | None]:
    """Retourne (texte_du_cours_brut, chemin_verif_ou_None) pour un slug donné.

    Le texte est renvoyé BRUT (non nettoyé) : l'appelant applique nettoie_latex,
    comme pour un cours uploadé.
    """
    dossier = COURS_DIR / slug
    texte = (dossier / "cours.txt").read_text(encoding="utf-8")
    verif = dossier / "verif.py"
    return texte, (str(verif) if verif.exists() else None)
