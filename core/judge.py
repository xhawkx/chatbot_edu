import re
from dataclasses import dataclass
from core.llm import call_one, LLMError, MODELS, DEFAULT_MODEL

JUDGE_PROMPT_TEMPLATE = """\
Tu es un correcteur pédagogique strict. Tu reçois :
- le cours de référence
- la question posée par l'élève
- la réponse produite par un assistant

Ta mission : vérifier que la réponse est fidèle au cours et pédagogiquement correcte.

Critères d'évaluation :
1. Exactitude factuelle : la réponse s'appuie uniquement sur le contenu du cours,
   sans invention de données ni recours à des connaissances extérieures.
2. Cas appliqué : le bon cas a-t-il été choisi ?
   - CAS 1 (répondre) si l'information est dans le cours ou la question fournit ses données.
   - CAS 2 (clarifier) si un référent ambigu ne peut pas être levé.
   - CAS 3 (refuser avec "Cette information ne figure pas dans le cours fourni.")
     uniquement si la notion est absente du cours.
3. Style : réponse directe, 1-2 phrases, pas de préambule.

Réponds UNIQUEMENT avec ce bloc, sans rien ajouter avant ni après :

VERDICT: valide|invalide
RAISON: <une phrase expliquant le verdict>
REPONSE_CORRIGEE: <réponse corrigée si invalide, sinon laisser vide>

CONTENU DU COURS :
{cours_texte}
"""

_VERDICT_RE = re.compile(
    r"VERDICT:\s*(valide|invalide)\s*\n"
    r"RAISON:\s*(.+?)\s*\n"
    r"REPONSE_CORRIGEE:\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class JudgeResult:
    valid: bool
    reason: str
    corrected: str | None  # None si valide ou si parsing échoue


def call_judge(
    question: str,
    reponse_candidate: str,
    cours_texte: str,
    api_key: str,
    model_label: str = DEFAULT_MODEL,
) -> JudgeResult:
    """Évalue `reponse_candidate` par rapport au cours et à la question.

    Retourne toujours un JudgeResult ; en cas d'erreur technique ou de parsing
    raté, le verdict est "valide" avec une raison d'erreur — l'élève n'est
    jamais bloqué par une défaillance du juge.
    """
    system_prompt = JUDGE_PROMPT_TEMPLATE.format(cours_texte=cours_texte)
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
            add_consigne=False,
        )
    except LLMError as e:
        return JudgeResult(valid=True, reason=f"Juge indisponible : {e}", corrected=None)

    m = _VERDICT_RE.search(raw)
    if not m:
        return JudgeResult(valid=True, reason="Parsing du verdict échoué — réponse originale conservée.", corrected=None)

    valid = m.group(1).lower() == "valide"
    reason = m.group(2).strip()
    corrected_raw = m.group(3).strip()
    corrected = corrected_raw if (not valid and corrected_raw) else None

    return JudgeResult(valid=valid, reason=reason, corrected=corrected)
