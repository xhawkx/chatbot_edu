"""Mode 4 — Bilan pédagogique oral.

Reçoit la liste des questions JSON (type QCM) + les réponses de l'élève,
agrège les notions maîtrisées / à consolider, puis demande au LLM un texte
fluide prêt pour la synthèse vocale (3 paragraphes, sans équations ni markdown).
"""

from __future__ import annotations
from dataclasses import dataclass, field

import io
from gtts import gTTS

from core.llm import call_one, DEFAULT_MODEL
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


def _agreger_notions(resultats: list[ResultatQuestion]) -> tuple[list[str], list[str]]:
    """Retourne (notions_acquises, notions_lacunes) dédupliquées et triées."""
    acquises: set[str] = set()
    lacunes: set[str] = set()
    for r in resultats:
        if r.est_correct:
            acquises.update(r.keywords)
        else:
            lacunes.update(r.keywords)
    # Une notion présente dans les deux camps va dans lacunes (partiellement acquise)
    return sorted(acquises - lacunes), sorted(lacunes)


def _build_bilan_prompt(lang: str = LANG_FR) -> str:
    if lang == LANG_AR:
        return """أنت معلّم يُعِدّ تقريراً شفهياً موجزاً لتلميذ بعد تقييم.

مهمتك: كتابة نص متدفّق يُقرأ بصوت عالٍ، مقسَّم إلى 3 فقرات فقط:

الفقرة 1 — الأداء العام: اذكر النسبة المئوية للإجابات الصحيحة وأعطِ رأياً موجزاً في هذه النتيجة.
الفقرة 2 — نقاط الضعف أولاً: المفاهيم التي يحتاج التلميذ إلى تعزيزها، بأسمائها فقط، دون ذكر معادلات أو أنواع الأسئلة.
الفقرة 3 — نقاط القوة ثم التوجيه: المفاهيم التي يتقنها التلميذ، ثم جملة تشجيعية توجّهه نحو مواصلة العمل لسدّ الثغرات.

القواعد الصارمة:
- نص مستمر فقط: لا عناوين، لا قوائم نقطية، لا نجوم، لا شرطات في بداية السطر.
- لا معادلات ولا صيغ رياضية من أي نوع.
- سمِّ المفاهيم باسمها (مثل: التحليل، الضرب، المتطابقات...) دون أي تفصيل تقني.
- أسلوب بسيط ومناسب لتلميذ في المتوسط، نبرة مشجّعة.
- حوالي 80 كلمة كحد أقصى.
- ابدأ مباشرةً بالفقرة الأولى.
- أجب باللغة العربية."""

    return """Tu es un enseignant qui prépare un compte-rendu oral et concis pour un élève après une évaluation.

Ta mission : écrire un texte fluide destiné à être lu à voix haute, en 3 paragraphes seulement :

Paragraphe 1 — Performance globale : cite le pourcentage de bonnes réponses et donne un avis bref sur ce résultat.
Paragraphe 2 — Points faibles d'abord : les notions que l'élève doit travailler, nommées simplement, sans équations ni types de questions.
Paragraphe 3 — Points forts puis trajectoire : les notions maîtrisées, puis une phrase d'encouragement qui incite l'élève à combler ses lacunes.

Règles strictes :
- Texte continu uniquement : pas de titres, pas de listes à puces, pas d'astérisques, pas de tirets en début de ligne.
- Aucune équation, aucune formule mathématique d'aucune sorte.
- Nomme les notions par leur nom (ex : factorisation, identités remarquables, développement…) sans détail technique.
- Style simple adapté à un élève de collège, ton encourageant.
- Environ 80 mots maximum.
- Commence directement par le premier paragraphe.
- Réponds en français."""


def _build_bilan_message(resultats: list[ResultatQuestion], lang: str = LANG_FR) -> str:
    """Construit le message utilisateur : score + notions agrégées (sans questions)."""
    score = sum(1 for r in resultats if r.est_correct)
    total = len(resultats)
    pct = round(score / total * 100) if total else 0

    acquises, lacunes = _agreger_notions(resultats)

    if lang == LANG_AR:
        lignes = [f"النتيجة: {score} من {total} ({pct}%)"]
        if lacunes:
            lignes.append("المفاهيم الواجب تعزيزها: " + "، ".join(lacunes))
        if acquises:
            lignes.append("المفاهيم المكتسبة: " + "، ".join(acquises))
        if not lacunes and not acquises:
            lignes.append("لا توجد كلمات مفتاحية محددة في الأسئلة.")
    else:
        lignes = [f"Score : {score}/{total} ({pct}%)"]
        if lacunes:
            lignes.append("Notions à consolider : " + ", ".join(lacunes))
        if acquises:
            lignes.append("Notions acquises : " + ", ".join(acquises))
        if not lacunes and not acquises:
            lignes.append("Aucun mot-clé de notion fourni dans les questions.")

    return "\n".join(lignes)


def bilan_vers_audio(texte: str, lang: str = LANG_FR) -> bytes:
    """Convertit le texte du bilan en MP3 via gTTS. Retourne les bytes du MP3."""
    code_lang = "ar" if lang == LANG_AR else "fr"
    buf = io.BytesIO()
    gTTS(text=texte, lang=code_lang, slow=False).write_to_fp(buf)
    buf.seek(0)
    return buf.read()


def generer_bilan(
    resultats: list[ResultatQuestion],
    cours_texte: str,
    api_key: str,
    model_label: str = DEFAULT_MODEL,
    lang: str = LANG_FR,
) -> str:
    """Appelle le LLM pour produire le bilan pédagogique oral.

    Lève LLMError en cas de problème technique.
    """
    system_prompt = _build_bilan_prompt(lang=lang)
    message = _build_bilan_message(resultats, lang=lang)

    brut = call_one(
        question=message,
        system_prompt=system_prompt,
        api_key=api_key,
        model_label=model_label,
        add_consigne=False,
        max_tokens=400,
        lang=lang,
    )
    return nettoie_latex(brut)
