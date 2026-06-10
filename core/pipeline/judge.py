"""Couche 2 — Judge.

Évalue (sans jamais réécrire) la réponse v1 par rapport au cours intégral.
Modèle DIFFÉRENT du générateur (clé anti-complaisance). Sortie JSON imposée,
parsée de façon robuste. Règle dure : un verdict NOK n'est retenu que si le juge
cite un extrait RÉELLEMENT présent dans le cours — sinon on retombe sur OK
(biais conservateur, le code prime sur le LLM).
"""

import json
import re
import unicodedata
from dataclasses import dataclass

from core.llm import call_one, LLMError

# Layer 2 model — MUST differ from the generator (anti-sycophancy).
JUDGE_MODEL = "GPT-OSS 120B (défaut)"

# Failure criteria the judge may report (anything else → treated as null/OK).
CRITERES = {"ancrage", "cadrage", "style", "exactitude"}

JUDGE_SYSTEM_TEMPLATE = """\
Tu es un correcteur pédagogique strict. Tu NE réécris JAMAIS de réponse \
alternative : tu évalues uniquement.

Tu reçois le cours de référence, la question de l'élève et la réponse produite \
par un assistant. Avant de juger, tu CITES un extrait exact du cours qui sert de \
base à ton évaluation (recopié mot pour mot depuis le cours, ou 'AUCUN' si la \
réponse ne s'appuie sur aucun passage précis).

Critères d'évaluation :
- ancrage    : la réponse s'appuie sur le cours (pas d'invention, pas de savoir extérieur).
- cadrage    : le bon cas est appliqué (1 répondre / 2 clarifier / 3 refuser).
- style      : réponse directe, 1-2 phrases, sans préambule.
- exactitude : faits et définitions conformes au cours.

Biais conservateur OBLIGATOIRE : en cas de doute, le verdict est OK.
Ne mets NOK que si tu es certain d'un défaut ET que l'extrait cité le prouve.

Réponds EXCLUSIVEMENT par un objet JSON valide, sans texte avant ni après, \
avec EXACTEMENT ces clés dans cet ordre :
{{"extrait_du_cours": "<citation exacte OU AUCUN>", "verdict": "OK|NOK", \
"critere_echoue": "ancrage|cadrage|style|exactitude|null", "critique": "<courte explication>"}}

CONTENU DU COURS :
{cours_texte}
"""


@dataclass
class JudgeVerdict:
    valid: bool                 # True = OK (réponse conservée), False = NOK justifié
    critere: str | None         # critère échoué si NOK, sinon None
    critique: str               # explication courte du juge (ou raison technique)
    extrait: str                # citation du cours retenue (ou "AUCUN")
    cite_ok: bool               # la citation a-t-elle été trouvée dans le cours ?


def _normalise(txt: str) -> str:
    """Lowercase + strip accents + collapse whitespace (for citation matching)."""
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"\s+", " ", txt)
    return txt.lower().strip()


def _extract_json(raw: str) -> dict | None:
    """Extrait le premier objet JSON de la réponse brute (robuste au bruit)."""
    # First try: the whole string is clean JSON.
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: grab the first {...} block (free-tier models add prose/fences).
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _citation_presente(extrait: str, cours_texte: str) -> bool:
    """La citation est-elle réellement un passage du cours ? (containment normalisé)"""
    extrait_n = _normalise(extrait)
    if not extrait_n or extrait_n == "aucun":
        return False
    # A too-short fragment is not a meaningful citation.
    if len(extrait_n) < 8:
        return False
    return extrait_n in _normalise(cours_texte)


def juge(question: str, reponse_candidate: str, cours_texte: str,
         api_key: str, model_label: str = JUDGE_MODEL) -> JudgeVerdict:
    """Évalue `reponse_candidate`. `model_label` : modèle juge (défaut JUDGE_MODEL).
    Ne bloque JAMAIS l'élève sur une défaillance : erreur technique, JSON illisible
    ou NOK non cité → verdict valide (OK)."""
    system_prompt = JUDGE_SYSTEM_TEMPLATE.format(cours_texte=cours_texte)
    user_msg = (
        f"Question de l'élève : {question}\n\n"
        f"Réponse à évaluer : {reponse_candidate}"
    )

    try:
        raw = call_one(
            question=user_msg,
            system_prompt=system_prompt,
            api_key=api_key,
            model_label=model_label,
            max_tokens=400,
            add_consigne=False,   # judge is not a pedagogical call
        )
    except LLMError as e:
        return JudgeVerdict(True, None, f"Juge indisponible : {e}", "AUCUN", False)

    data = _extract_json(raw)
    if not data:
        return JudgeVerdict(True, None, "JSON du juge illisible — réponse conservée.", "AUCUN", False)

    verdict = str(data.get("verdict", "")).strip().upper()
    extrait = str(data.get("extrait_du_cours", "")).strip()
    critique = str(data.get("critique", "")).strip()
    critere = str(data.get("critere_echoue", "")).strip().lower()
    critere = critere if critere in CRITERES else None

    cite_ok = _citation_presente(extrait, cours_texte)

    # Hard rule: a NOK is kept ONLY if backed by a real course citation.
    if verdict == "NOK" and cite_ok:
        return JudgeVerdict(False, critere, critique or "Défaut signalé par le juge.", extrait, True)

    if verdict == "NOK" and not cite_ok:
        return JudgeVerdict(True, None, "NOK rejeté (citation absente du cours) — réponse conservée.", extrait, False)

    # OK, or unknown verdict → conservative bias.
    return JudgeVerdict(True, None, critique or "Réponse jugée conforme.", extrait, cite_ok)
