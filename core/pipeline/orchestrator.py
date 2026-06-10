"""Couche d'assemblage — Orchestrator.

Assemble Generator → (court-circuit déterministe) → Judge → Refine, avec les
garde-fous et la hiérarchie de décision :

    Python (calculs)  >  citation du cours (factuel)  >  original par défaut

Point d'entrée unique : `repond(question, historique, *, cours_texte, ...)` qui
retourne la réponse finale + métadonnées (verdict, nb d'itérations, méthode, trace).

Le vérificateur arithmétique est SPÉCIFIQUE au cours : il est chargé dynamiquement
depuis `verif_path` (cours/<slug>/verif.py). S'il est absent, le contrôle de calcul
est un no-op (cours sans calculs → on passe directement au juge).
"""

import importlib.util
import logging

from core.llm import LLMError
from core.pipeline.generator import generate, GENERATOR_MODEL
from core.pipeline.judge import juge, JUDGE_MODEL
from core.pipeline.refine import refine

logger = logging.getLogger("pipeline")

MAX_ITERATIONS = 2   # hard cap on refine loops, per spec


def _charge_controle_calcul(verif_path: str | None):
    """Charge dynamiquement `controle_calcul` depuis le verif.py du cours.

    Retourne la fonction, ou un no-op (toujours OK) si aucun verif.py n'est fourni
    ou s'il est inutilisable — un cours sans calculs ne doit pas bloquer le pipeline.
    """
    def _noop(_reponse: str):
        return True, ""

    if not verif_path:
        return _noop
    try:
        spec = importlib.util.spec_from_file_location("cours_verif", verif_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "controle_calcul", _noop)
    except Exception as e:
        logger.warning("verif.py introuvable/illisible (%s) → contrôle calcul désactivé", e)
        return _noop


def repond(question: str, historique: list | None = None, *,
           cours_texte: str, api_key: str,
           verif_path: str | None = None,
           cadrage_slug: str | None = None,
           model_generateur: str = GENERATOR_MODEL,
           model_juge: str = JUDGE_MODEL) -> dict:
    """Exécute le pipeline 3 couches et retourne un dict :

        {
          "reponse": str,            # réponse finale transmise à l'élève
          "verdict": str,            # OK | NOK | CALCUL_FAUX | ERREUR
          "iterations": int,         # nombre de passes de Refine effectuées
          "methode": str,            # comment la réponse finale a été obtenue
          "reponse_v1": str,         # réponse brute du générateur (debug)
          "trace": list[str],        # journal lisible des étapes
        }

    Hiérarchie : Python (calcul) > citation du cours (juge) > original.
    """
    trace: list[str] = []

    def _log(msg: str):
        logger.info(msg)
        trace.append(msg)

    controle_calcul = _charge_controle_calcul(verif_path)

    # ── Couche 1 : Generator ─────────────────────────────────────────────
    try:
        reponse = generate(question, cours_texte, api_key,
                           historique=historique, cadrage_slug=cadrage_slug,
                           model_label=model_generateur)
    except LLMError as e:
        _log(f"[Generator/{model_generateur}] ÉCHEC : {e}")
        return {"reponse": "", "verdict": "ERREUR", "iterations": 0,
                "methode": "echec_generateur", "reponse_v1": "", "trace": trace}

    reponse_v1 = reponse
    _log(f"[Generator/{model_generateur}] réponse v1 produite ({len(reponse)} car.)")

    iterations = 0
    methode = "original"  # default decision: keep the generator's answer

    while iterations < MAX_ITERATIONS:
        # ── Court-circuit déterministe : Python prime sur tout LLM ────────
        calcul_ok, message_calcul = controle_calcul(reponse)
        if not calcul_ok:
            _log(f"[Verif/Python] CALCUL FAUX → court-circuit du juge (itération {iterations + 1})")
            critique = message_calcul
            verdict_courant = "CALCUL_FAUX"
        else:
            _log("[Verif/Python] calcul OK (ou non vérifiable) → passage au juge")
            # ── Couche 2 : Judge ─────────────────────────────────────────
            v = juge(question, reponse, cours_texte, api_key, model_label=model_juge)
            if v.valid:
                _log(f"[Judge/{model_juge}] OK — {v.critique}")
                # OK → retour direct, aucun appel supplémentaire.
                return {"reponse": reponse, "verdict": "OK", "iterations": iterations,
                        "methode": methode, "reponse_v1": reponse_v1, "trace": trace}
            _log(f"[Judge/{model_juge}] NOK justifié ({v.critere}) — citation : « {v.extrait[:60]}… »")
            critique = f"{v.critique}\n\nExtrait du cours invoqué : {v.extrait}"
            verdict_courant = "NOK"

        # ── Couche 3 : Refine (calcul faux OU NOK justifié) ──────────────
        iterations += 1
        try:
            # Refine reuses the generator model (architecture invariant).
            reponse = refine(question, reponse, critique, cours_texte, api_key,
                            historique=historique, cadrage_slug=cadrage_slug,
                            model_label=model_generateur)
            methode = "python_refine" if verdict_courant == "CALCUL_FAUX" else "juge_refine"
            _log(f"[Refine/{model_generateur}] réponse reformulée (itération {iterations})")
        except LLMError as e:
            # Refine technical failure → keep the last valid answer, stop.
            _log(f"[Refine/{model_generateur}] ÉCHEC : {e} → on conserve la réponse précédente")
            return {"reponse": reponse, "verdict": verdict_courant, "iterations": iterations,
                    "methode": "echec_refine", "reponse_v1": reponse_v1, "trace": trace}
        # Loop continues: the refined answer is re-checked (verif + judge).

    # ── Plafond d'itérations atteint : on retourne la dernière reformulation ─
    _log(f"[Stop] plafond de {MAX_ITERATIONS} itérations atteint")
    # Final verdict reflects the last known state of the answer.
    calcul_ok, _ = controle_calcul(reponse)
    verdict_final = "CALCUL_FAUX" if not calcul_ok else "NOK"
    return {"reponse": reponse, "verdict": verdict_final, "iterations": iterations,
            "methode": methode, "reponse_v1": reponse_v1, "trace": trace}
