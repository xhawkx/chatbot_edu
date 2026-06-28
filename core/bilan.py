"""Mode 4 — Bilan pédagogique oral.

Reçoit la liste des questions JSON (type QCM) + les réponses de l'élève,
agrège les notions maîtrisées / à consolider, puis demande au LLM un texte
fluide prêt pour la synthèse vocale (3 paragraphes, sans équations ni markdown).
"""

from __future__ import annotations
from dataclasses import dataclass, field

import asyncio
import io

import edge_tts

from core.llm import call_one, DEFAULT_MODEL
from core.prompt import LANG_FR, LANG_AR
from core.latex import nettoie_latex

# ── Providers TTS disponibles ──────────────────────────────────────────────
# `voix` indique si le provider expose un choix Homme/Femme dans l'IHM.
TTS_PROVIDERS = {
    "Edge TTS (Microsoft)": {
        "key": "edge",
        "voix": True,
        "description": "Voix neurales Microsoft ar-DZ / fr-FR — gratuit, nécessite internet",
    },
    "gTTS (Google Translate)": {
        "key": "gtts",
        "voix": False,
        "description": "Voix Google Translate ar / fr — gratuit, accent plus naturel",
    },
}
DEFAULT_TTS = "Edge TTS (Microsoft)"

# Voix neurales Microsoft — voix algériennes pour l'arabe (ar-DZ), françaises pour le français
VOIX_FR = {"Homme": "fr-FR-HenriNeural", "Femme": "fr-FR-DeniseNeural"}
VOIX_AR = {"Homme": "ar-DZ-IsmaelNeural", "Femme": "ar-DZ-AminaNeural"}

# Prosodie par langue : débit légèrement ralenti + ton posé → rythme d'enseignant
# pitch en Hz (format attendu par edge-tts), rate en %
_PROSODY = {
    "fr": {"rate": "-12%", "pitch": "-4Hz"},
    "ar": {"rate": "-15%", "pitch": "-5Hz"},
}


async def _synthese_async(texte: str, voix: str, lang_key: str = "fr") -> bytes:
    # Le proxy d'entreprise re-signe les certificats TLS avec sa propre CA.
    # edge-tts construit un contexte SSL au niveau module (communicate._SSL_CTX,
    # basé sur certifi) qu'il passe explicitement à ws_connect(ssl=...).
    # On désactive la vérification sur cet objet précis le temps de l'appel.
    import ssl as _ssl
    from edge_tts import communicate as _edge_comm

    p = _PROSODY.get(lang_key, {"rate": "-10%", "pitch": "-3Hz"})
    ctx = _edge_comm._SSL_CTX
    _saved = (ctx.check_hostname, ctx.verify_mode)
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    try:
        buf = io.BytesIO()
        communicate = edge_tts.Communicate(texte, voix, rate=p["rate"], pitch=p["pitch"])
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return buf.read()
    finally:
        ctx.check_hostname, ctx.verify_mode = _saved


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
        return """أنتَ مُعلِّمٌ تُخاطِبُ تِلميذَكَ مُباشَرةً بَعدَ تَقييمٍ. تَكلَّمْ مَعَهُ بِضَميرِ المُخاطَبِ (أنتَ).

مَهمَّتُكَ: كِتابةُ نَصٍّ مُتدفِّقٍ يُقرَأُ بِصَوتٍ عالٍ، مُقسَّمٌ إلى 3 فَقَراتٍ فَقَط:

الفَقرةُ 1 — الأداءُ العامُّ: خاطِبِ التِّلميذَ مُباشَرةً بِالنِّسبةِ المِئَويَّةِ لِإِجاباتِهِ الصَّحيحةِ وأَعطِهِ رَأيَكَ المُوجَزَ.
الفَقرةُ 2 — نِقاطُ الضَّعفِ: أَخبِرهُ بِالمَفاهيمِ الَّتي يَحتاجُ إلى تَعزيزِها، بِأَسمائِها فَقَط، دونَ ذِكرِ مُعادَلاتٍ.
الفَقرةُ 3 — نِقاطُ القُوَّةِ ثُمَّ التَّوجيهُ: المَفاهيمُ الَّتي يُتقِنُها، ثُمَّ جُملةٌ تَشجيعيَّةٌ تَدفَعُهُ إلى مُواصَلةِ العَمَلِ.

القَواعِدُ الصَّارِمةُ:
- نَصٌّ مُستمِرٌّ فَقَط: لا عَناوينَ، لا قَوائِمَ نُقطيَّةً، لا نُجومَ، لا شُرَطَ في بِدايةِ السَّطرِ.
- لا مُعادَلاتٍ ولا صِيَغَ رِياضيَّةً مِن أيِّ نَوعٍ.
- سَمِّ المَفاهيمَ بِاسمِها دونَ أيِّ تَفصيلٍ تِقنيٍّ.
- أُسلوبٌ بَسيطٌ مُناسِبٌ لِتِلميذٍ في المُتوسِّطِ، نَبرةٌ مُشجِّعةٌ وحَميمةٌ.
- حَوالي 80 كَلمةً كَحَدٍّ أَقصى.
- ضَعِ التَّشكيلَ الكامِلَ (الحَرَكاتِ) على كُلِّ الكَلِماتِ لِيَكونَ النُّطقُ واضِحاً.
- ابدَأ مُباشَرةً بِالفَقرةِ الأولى.
- أَجِبْ بِاللُّغةِ العَرَبيَّةِ."""

    return """Tu es un enseignant qui s'adresse directement à son élève après une évaluation. Parle-lui à la deuxième personne du singulier (tu).

Ta mission : écrire un texte fluide destiné à être lu à voix haute, en 3 paragraphes seulement :

Paragraphe 1 — Performance globale : interpelle l'élève directement avec son pourcentage de bonnes réponses et donne-lui ton avis bref et sincère.
Paragraphe 2 — Points faibles d'abord : dis-lui les notions qu'il doit travailler, nommées simplement, sans équations ni types de questions.
Paragraphe 3 — Points forts puis trajectoire : les notions qu'il maîtrise, puis une phrase d'encouragement qui l'incite à combler ses lacunes.

Règles strictes :
- Texte continu uniquement : pas de titres, pas de listes à puces, pas d'astérisques, pas de tirets en début de ligne.
- Aucune équation, aucune formule mathématique d'aucune sorte.
- Nomme les notions par leur nom (ex : factorisation, identités remarquables, développement…) sans détail technique.
- Style simple adapté à un élève de collège, ton chaleureux et encourageant.
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


def _synthese_gtts(texte: str, lang: str = LANG_FR) -> bytes:
    """Synthèse via gTTS (Google Translate TTS) — gratuit, accent naturel."""
    from gtts import gTTS
    lang_code = "ar" if lang == LANG_AR else "fr"
    buf = io.BytesIO()
    tts = gTTS(text=texte, lang=lang_code, slow=True)
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf.read()



def bilan_vers_audio(
    texte: str,
    lang: str = LANG_FR,
    genre: str = "Femme",
    tts_provider: str = DEFAULT_TTS,
) -> tuple[bytes, str]:
    """Convertit le texte du bilan en audio.

    `tts_provider`  : clé d'affichage du dict TTS_PROVIDERS.
    `genre`         : "Femme" ou "Homme" — utilisé par Edge TTS.
    Retourne (bytes_audio, format) avec format = "audio/mp3".
    """
    provider_key = TTS_PROVIDERS.get(tts_provider, TTS_PROVIDERS[DEFAULT_TTS])["key"]

    if provider_key == "gtts":
        return _synthese_gtts(texte, lang=lang), "audio/mp3"

    # Défaut : Edge TTS
    voix_map = VOIX_AR if lang == LANG_AR else VOIX_FR
    voix = voix_map.get(genre, list(voix_map.values())[0])
    lang_key = "ar" if lang == LANG_AR else "fr"
    return asyncio.run(_synthese_async(texte, voix, lang_key)), "audio/mp3"


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
