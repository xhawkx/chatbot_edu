"""Couche 3 — Refine.

Reformule la réponse v1 à partir d'une critique (calcul faux détecté par verif.py
OU verdict NOK justifié par le juge). Utilise le MÊME modèle que le générateur.
Ne repart pas de zéro : corrige uniquement le défaut signalé et conserve ce qui
est correct, le style et le cadrage 3 cas.
"""

from core.llm import call_one
from core.prompt import build_system_prompt
from core.pipeline.generator import GENERATOR_MODEL

# Layer 3 reuses the generator model (per spec).
REFINE_MODEL = GENERATOR_MODEL

REFINE_INSTRUCTION = """\
Une première réponse a été produite puis critiquée. Corrige UNIQUEMENT le défaut \
signalé ci-dessous, sans repartir de zéro : garde ce qui est correct, conserve le \
style (1-2 phrases, sans préambule) et la logique des 3 cas (réponse / clarification \
/ refus). N'ajoute rien qui ne soit pas demandé.

RÉPONSE À CORRIGER :
{reponse_v1}

CRITIQUE À PRENDRE EN COMPTE :
{critique}

Réécris maintenant la réponse corrigée, et UNIQUEMENT elle."""


def refine(question: str, reponse_v1: str, critique: str, cours_texte: str,
           api_key: str, historique: list | None = None,
           cadrage_slug: str | None = None,
           model_label: str = REFINE_MODEL) -> str:
    """Produit une réponse corrigée. `model_label` : modèle de reformulation
    (défaut REFINE_MODEL = générateur). Lève `LLMError` (géré par l'orchestrateur)."""
    system_prompt = build_system_prompt(cours_texte, cadrage_slug=cadrage_slug)
    user_msg = REFINE_INSTRUCTION.format(reponse_v1=reponse_v1, critique=critique)
    return call_one(
        question=user_msg,
        system_prompt=system_prompt,
        api_key=api_key,
        model_label=model_label,
        historique=historique,
        add_consigne=False,   # the refine instruction already carries the framing
    )
