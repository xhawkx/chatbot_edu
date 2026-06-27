"""Mode 4 — Bilan pédagogique.

Reçoit la liste des questions JSON (type QCM) + les réponses de l'élève,
construit le prompt de bilan et appelle le LLM.

Format QCM attendu (champ `answers` = liste 1-based) :
  {
    "id": "q_n2_014",
    "question": "...",
    "choices": ["choix A", "choix B", "choix C", "choix D"],
    "answers": [1],          <- index 1-based de la/des bonne(s) réponse(s)
    "explanation": "...",    <- optionnel
    "keywords": [...],       <- optionnel
    "type": "qcm"
  }
"""

from __future__ import annotations
from dataclasses import dataclass, field

from core.llm import call_one, LLMError, DEFAULT_MODEL
from core.prompt import LANG_FR, LANG_AR
from core.latex import nettoie_latex


@dataclass
class ResultatQuestion:
    id: str
    question: str
    choix: list[str]
    bonnes_reponses: list[int]   # 1-based
    reponse_eleve: int | None    # 1-based, None si non répondu
    explication: str = ""
    keywords: list[str] = field(default_factory=list)

    @property
    def est_correct(self) -> bool:
        return self.reponse_eleve in self.bonnes_reponses

    @property
    def libelle_reponse_eleve(self) -> str:
        if self.reponse_eleve is None:
            return "— (sans réponse)"
        idx = self.reponse_eleve - 1
        if 0 <= idx < len(self.choix):
            return self.choix[idx]
        return f"(indice {self.reponse_eleve})"

    @property
    def libelle_bonne_reponse(self) -> str:
        labels = []
        for a in self.bonnes_reponses:
            idx = a - 1
            if 0 <= idx < len(self.choix):
                labels.append(self.choix[idx])
        return " / ".join(labels)


def _build_bilan_prompt(cours_texte: str, lang: str = LANG_FR) -> str:
    """Construit le prompt système pour la génération du bilan."""
    if lang == LANG_AR:
        return f"""أنت معلّم لطيف يكتب حصيلة بيداغوجية لتلميذ بعد إجراء تقييم.

محتوى الدرس (المرجع):
{cours_texte}

مهمتك: حلّل نتائج التلميذ أدناه وأنتج حصيلة منظّمة في 3 أجزاء:

1. **ملخّص الأداء**: النتيجة الإجمالية (X/Y)، ونبرة عامة حول النتائج (دون حكم قاسٍ).
2. **النقاط المكتسبة**: المفاهيم أو أنواع الأسئلة التي يتقنها التلميذ (مع مثال واحد على الأقل لسؤال نجح فيه).
3. **النقاط الواجب تعزيزها**: المفاهيم التي أخطأ فيها التلميذ، مع شرح موجز للطريقة الصحيحة مستمدّ من الدرس.

قواعد التحرير:
- كن مشجّعاً لكن صادقاً.
- لا تَسرد كل سؤال آلياً. اجمع حسب المفهوم.
- اعتمد فقط على الدرس المقدَّم لشرح الأخطاء، لكن أعِد الصياغة بكلماتك. لا تنسخ الدرس حرفياً.
- موجز: حوالي 120 كلمة كحد أقصى للحصيلة كلها.
- محظور تماماً استعمال ترميز LaTeX: لا $$، لا \\sqrt، لا \\frac، ولا أي أمر يبدأ بـ \\.
  اكتب الرياضيات بصيغة بسيطة وقصيرة باستعمال الرموز العادية مثل ² و √ و ×.
  تجنّب التعابير الرياضية الطويلة داخل الجمل العربية؛ اكتفِ بذكر اسم القاعدة عند الإمكان.
- استعمل عناوين عريضة للأجزاء الثلاثة وقوائم نقطية قصيرة.
- بدون مقدّمة ("بالطبع"، "إليك الحصيلة"…). ابدأ مباشرة بالجزء 1.
- أجب باللغة العربية.
"""

    return f"""Tu es un enseignant bienveillant qui rédige le bilan pédagogique d'un élève après une évaluation.

CONTENU DU COURS (référence) :
{cours_texte}

Ta mission : analyser les résultats de l'élève ci-dessous et produire un bilan structuré en 3 parties :

1. **Résumé des performances** : score global (X/Y), ton général sur les résultats (sans jugement dur).
2. **Points acquis** : les notions ou types de questions que l'élève maîtrise (au moins 1 exemple de question réussie).
3. **Points à consolider** : les notions où l'élève a fait des erreurs, avec une explication courte de la bonne démarche tirée du cours.

Règles de rédaction :
- Sois encourageant mais honnête.
- Ne liste pas mécaniquement chaque question. Regroupe par notion/concept.
- Base-toi UNIQUEMENT sur le cours fourni, mais reformule avec tes mots. Ne recopie pas le cours mot pour mot.
- Concis : environ 120 mots maximum pour tout le bilan.
- STRICTEMENT INTERDIT d'utiliser du LaTeX : pas de $$, pas de \\sqrt, pas de \\frac, ni aucune commande commençant par \\.
  Écris les maths simplement avec les symboles usuels (², √, ×). Garde les expressions mathématiques courtes,
  ou cite simplement le nom de la règle plutôt qu'une longue formule.
- Utilise des titres en gras pour les 3 parties et des listes à puces courtes.
- Pas de préambule ("Bien sûr", "Voici le bilan"…). Commence directement par la Partie 1.
- Réponds en français.
"""


def _build_bilan_question(resultats: list[ResultatQuestion], lang: str = LANG_FR) -> str:
    """Construit le message utilisateur avec les résultats de l'élève."""
    ar = lang == LANG_AR
    lbl_q = "س" if ar else "Q"
    lbl_eleve = "إجابة التلميذ" if ar else "Réponse de l'élève"
    lbl_bonne = "الإجابة الصحيحة" if ar else "Bonne réponse"
    lbl_expl = "الشرح" if ar else "Explication"

    lignes = []
    for i, r in enumerate(resultats, 1):
        statut = "✓" if r.est_correct else "✗"
        ligne = (
            f"{lbl_q}{i} [{statut}] {r.question}\n"
            f"   {lbl_eleve} : {r.libelle_reponse_eleve}\n"
            f"   {lbl_bonne} : {r.libelle_bonne_reponse}"
        )
        if r.explication:
            ligne += f"\n   {lbl_expl} : {r.explication}"
        lignes.append(ligne)

    score = sum(1 for r in resultats if r.est_correct)
    total = len(resultats)
    if ar:
        header = f"النتيجة: {score}/{total}\n\nتفصيل الأسئلة:\n"
    else:
        header = f"Score : {score}/{total}\n\nDétail des questions :\n"
    return header + "\n\n".join(lignes)


def generer_bilan(
    resultats: list[ResultatQuestion],
    cours_texte: str,
    api_key: str,
    model_label: str = DEFAULT_MODEL,
    lang: str = LANG_FR,
) -> str:
    """Appelle le LLM pour produire le bilan pédagogique.

    Lève LLMError en cas de problème technique.
    """
    system_prompt = _build_bilan_prompt(cours_texte, lang=lang)
    question_text = _build_bilan_question(resultats, lang=lang)

    brut = call_one(
        question=question_text,
        system_prompt=system_prompt,
        api_key=api_key,
        model_label=model_label,
        add_consigne=False,
        max_tokens=800,
        lang=lang,
    )
    # Filet de sécurité : si le modèle produit malgré tout du LaTeX, on le
    # convertit en symboles unicode (cohérent avec le nettoyage du cours).
    return nettoie_latex(brut)
