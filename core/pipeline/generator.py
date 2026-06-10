"""Couche 1 — Generator.

Produit la réponse v1 à partir du cours intégral + cadrage 3 cas + historique.
Réutilise le system prompt et la consigne de brièveté existants (core/prompt.py)
ainsi que la couche d'appel mutualisée (core/llm.py : OpenRouter, retries 429).
"""

from core.llm import call_one
from core.prompt import build_system_prompt

# Layer 1 model — fixed per the 3-layer spec (free tier, deterministic).
GENERATOR_MODEL = "Gemma 4 31B"


def generate(question: str, cours_texte: str, api_key: str,
             historique: list | None = None,
             cadrage_slug: str | None = None,
             model_label: str = GENERATOR_MODEL) -> str:
    """Génère la réponse v1.

    `historique` : tours précédents [{"role", "content"}, ...] (déjà tronqué aux
    2 derniers tours par l'appelant). `model_label` : modèle à utiliser (défaut
    GENERATOR_MODEL). Lève `LLMError` en cas de souci technique (l'orchestrateur
    décide quoi en faire).
    """
    system_prompt = build_system_prompt(cours_texte, cadrage_slug=cadrage_slug)
    return call_one(
        question=question,
        system_prompt=system_prompt,
        api_key=api_key,
        model_label=model_label,
        historique=historique,
        add_consigne=True,   # pedagogical call → keep the brevity directive
    )
