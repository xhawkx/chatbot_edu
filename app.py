import json
import os
import re
import html as _html
import tempfile
import streamlit as st
from core.auth import check_auth, login_form, logout
from core.latex import nettoie_latex
from core.prompt import build_system_prompt, LANG_FR, LANG_AR
from core.llm import call_one, LLMError, MODELS, DEFAULT_MODEL
from core.judge import call_judge
from core.config import liste_cours, charge_cours
from core.pipeline.orchestrator import repond
from core.pipeline.generator import GENERATOR_MODEL
from core.pipeline.judge import JUDGE_MODEL
from core.bilan import ResultatQuestion, generer_bilan, bilan_vers_audio, VOIX_FR, VOIX_AR, TTS_PROVIDERS, DEFAULT_TTS

st.set_page_config(page_title="Chatbot pédagogique v2", page_icon="📚", layout="centered")

# Four comparable modes.
MODE_SINGLE = "💬 Single"
MODE_JUGE = "⚖️ Avec juge"
MODE_PIPELINE = "🧩 3 couches"
MODE_BILAN = "📋 Bilan élève"
MODES = [MODE_SINGLE, MODE_JUGE, MODE_PIPELINE, MODE_BILAN]


# Séquences contenant au moins un caractère LTR significatif (lettre latine,
# chiffre, opérateur math) à isoler en dir=ltr dans un bloc RTL.
# On capture la séquence ENTIÈRE — espaces et parenthèses internes compris —
# tant qu'elle ne contient aucune lettre arabe ni saut de ligne. Ainsi une
# formule comme « (a - b)² » reste dans UN seul span dir=ltr et n'est pas
# réordonnée morceau par morceau par l'algorithme bidi (parenthèses inversées).
# Une ponctuation seule (sans caractère significatif) n'est jamais capturée :
# le navigateur la gère correctement à côté du texte arabe.
_LTR_RUN = re.compile(
    r"([^؀-ۿﭐ-﷿ﹰ-﻿\n\r]*[A-Za-z0-9=+\-*/×÷^<>|_][^؀-ۿﭐ-﷿ﹰ-﻿\n\r]*)"
)


def _bidi_format(text: str) -> str:
    """Échappe le HTML puis isole en dir=ltr les séquences LTR significatives."""
    escaped = _html.escape(text)
    return _LTR_RUN.sub(r'<span dir="ltr">\1</span>', escaped)


def write_msg(text: str, lang: str = LANG_FR) -> None:
    """Affiche un message en respectant la direction RTL pour l'arabe."""
    if lang == LANG_AR:
        st.markdown(
            f'<div dir="rtl" style="text-align:right">{_bidi_format(text)}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.write(text)


def get_api_key() -> str:
    try:
        if "OPENROUTER_API_KEY" in st.secrets:
            return st.secrets["OPENROUTER_API_KEY"]
    except Exception:
        pass
    return os.environ.get("OPENROUTER_API_KEY", "")


def derniers_tours(messages: list, n: int = 2) -> list:
    """Reconstruit l'historique des `n` derniers tours pour le pipeline (mode 3).

    `messages` ne stocke que les réponses finales (user/assistant alternés) ;
    on renvoie au plus 2*n entrées au format attendu par call_one.
    """
    return [{"role": m["role"], "content": m["content"]} for m in messages[-2 * n:]]


# ── Authentification ───────────────────────────────────────────────────────
if not check_auth():
    login_form()
    st.stop()

# ── Sidebar ────────────────────────────────────────────────────────────────
model_keys = list(MODELS.keys())
default_idx = model_keys.index(DEFAULT_MODEL)

with st.sidebar:
    st.title("📚 Chatbot pédagogique v2")

    if st.button("🚪 Déconnexion"):
        logout()

    st.divider()

    # ── Choix du cours (dropdown depuis cours/) ──────────────────────────
    cours_dispo = liste_cours()
    if not cours_dispo:
        st.error("Aucun cours dans `cours/`. Crée un dossier `cours/<slug>/cours.txt`.")
        st.stop()

    cours_slug = st.selectbox("📖 Cours", options=cours_dispo, key="cours_slug")

    # (Re)charge le cours si la sélection a changé.
    if st.session_state.get("cours_nom") != cours_slug:
        cours_brut, verif_path = charge_cours(cours_slug)
        st.session_state["cours_texte"] = nettoie_latex(cours_brut)
        st.session_state["cours_nom"] = cours_slug
        st.session_state["verif_path"] = verif_path
        st.session_state["messages"] = []

    verif_actif = st.session_state.get("verif_path") is not None
    st.caption(
        f"Cours actif : **{st.session_state['cours_nom']}** — {len(st.session_state['cours_texte'])} car. · "
        f"vérif. calcul : {'✅' if verif_actif else '—'}"
    )

    st.divider()

    # ── Chargement d'un cours personnalisé ───────────────────────────
    st.markdown("**Ou charger un cours personnalisé**")
    uploaded_cours = st.file_uploader("Cours (.txt)", type=["txt"], key="up_cours")

    mode_courant = st.session_state.get("mode", MODE_SINGLE)
    if mode_courant == MODE_PIPELINE:
        uploaded_verif = st.file_uploader(
            "Vérificateur Python (.py) — optionnel", type=["py"], key="up_verif"
        )
    else:
        uploaded_verif = None

    if mode_courant == MODE_BILAN:
        st.markdown("**Évaluation (QCM JSON)**")
        uploaded_eval = st.file_uploader(
            "Fichier évaluation (.json)", type=["json"], key="up_eval"
        )
        # On ne (ré)initialise QUE lorsqu'un nouveau fichier est chargé :
        # st.file_uploader renvoie le même objet à chaque rerun, donc sans ce
        # garde-fou l'index du quiz serait remis à 0 à chaque clic « Suivant ».
        if uploaded_eval is not None and st.session_state.get("eval_nom") != uploaded_eval.name:
            try:
                questions_json = json.loads(uploaded_eval.read().decode("utf-8"))
                st.session_state["eval_questions"] = questions_json
                st.session_state["eval_nom"] = uploaded_eval.name
                st.session_state["quiz_index"] = 0
                st.session_state["quiz_reponses"] = {}
                st.session_state["quiz_termine"] = False
                st.session_state["bilan_texte"] = None
                st.session_state["bilan_audio"] = None
                st.success(f"{len(questions_json)} question(s) chargée(s).")
            except Exception as exc:
                st.error(f"Fichier JSON invalide : {exc}")
    else:
        uploaded_eval = None

    if uploaded_cours is not None:
        raw = uploaded_cours.read().decode("utf-8")
        st.session_state["cours_texte"] = nettoie_latex(raw)
        st.session_state["cours_nom"] = uploaded_cours.name
        st.session_state["messages"] = []
        if uploaded_verif is not None:
            tmp = tempfile.NamedTemporaryFile(
                suffix="_verif.py", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write(uploaded_verif.read().decode("utf-8"))
            tmp.close()
            st.session_state["verif_path"] = tmp.name
        else:
            st.session_state["verif_path"] = None

    st.divider()

    # ── Choix du mode ────────────────────────────────────────────────────
    mode = st.radio("🛠️ Mode", options=MODES, key="mode")

    # ── Choix de la langue (Modes Single & Bilan) ────────────────────
    if mode in (MODE_SINGLE, MODE_BILAN):
        langue = st.radio(
            "🌐 Langue",
            options=[LANG_FR, LANG_AR],
            format_func=lambda x: "Français" if x == LANG_FR else "عربي",
            key="langue",
            horizontal=True,
        )
    else:
        langue = LANG_FR

    # Sélecteurs de modèles selon le mode.
    if mode == MODE_PIPELINE:
        model_generateur = st.selectbox(
            "🤖 Modèle générateur (+ refine)", options=model_keys,
            index=model_keys.index(GENERATOR_MODEL), key="model_generateur",
        )
        model_juge_pipe = st.selectbox(
            "⚖️ Modèle juge", options=model_keys,
            index=model_keys.index(JUDGE_MODEL), key="model_juge_pipe",
        )
        if model_generateur == model_juge_pipe:
            st.warning("Générateur et juge identiques : la vérification croisée perd son intérêt.")
    elif mode == MODE_BILAN:
        model_bilan = st.selectbox(
            "🤖 Modèle bilan", options=model_keys, index=default_idx,
            key="model_bilan",
        )
        tts_keys = list(TTS_PROVIDERS.keys())
        tts_provider = st.selectbox(
            "🔊 Moteur audio",
            options=tts_keys,
            index=tts_keys.index(DEFAULT_TTS),
            key="tts_provider",
            help="\n".join(f"**{k}** — {v['description']}" for k, v in TTS_PROVIDERS.items()),
        )
    else:
        model_repondant = st.selectbox(
            "🤖 Modèle répondant", options=model_keys, index=default_idx,
            key="model_repondant",
        )
        if mode == MODE_JUGE:
            model_juge = st.selectbox(
                "⚖️ Modèle juge", options=model_keys, index=default_idx,
                key="model_juge",
            )

    st.divider()

    if st.button("🗑️ Réinitialiser la conversation"):
        st.session_state["messages"] = []
        st.rerun()

# ── Zone principale ────────────────────────────────────────────────────────

# ════════════════════════════════════════════════════════════
#  MODE 4 — Bilan élève (quiz QCM + analyse LLM)
# ════════════════════════════════════════════════════════════
if mode == MODE_BILAN:
    st.header("📋 Évaluation & Bilan pédagogique")

    questions = st.session_state.get("eval_questions")
    if not questions:
        st.info("Charge un fichier JSON d'évaluation dans la barre latérale pour commencer.")
        st.stop()

    if "cours_texte" not in st.session_state:
        st.warning("Sélectionne ou charge un cours dans la barre latérale.")
        st.stop()

    quiz_index = st.session_state.get("quiz_index", 0)
    quiz_reponses: dict = st.session_state.get("quiz_reponses", {})
    quiz_termine = st.session_state.get("quiz_termine", False)

    # ── Phase quiz ───────────────────────────────────────────
    if not quiz_termine:
        total = len(questions)
        st.progress(quiz_index / total, text=f"Question {quiz_index + 1} / {total}")

        q = questions[quiz_index]
        q_id = q.get("id", str(quiz_index))
        question_text = nettoie_latex(q.get("question", ""))
        choices_raw = q.get("choices", [])
        choices = [nettoie_latex(c) for c in choices_raw]

        st.markdown(f"**{quiz_index + 1}. {question_text}**")

        aide = q.get("help", "")
        if aide:
            with st.expander("💡 Indice"):
                st.write(nettoie_latex(aide))

        selected = st.radio(
            "Choisissez une réponse :",
            options=list(range(len(choices))),
            format_func=lambda i: choices[i],
            key=f"radio_{q_id}",
            index=None,
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            if quiz_index > 0:
                if st.button("⬅️ Précédent"):
                    st.session_state["quiz_index"] = quiz_index - 1
                    st.rerun()
        with col2:
            label_suivant = "Terminer ✅" if quiz_index == total - 1 else "Suivant ➡️"
            if st.button(label_suivant):
                # Aucune sélection = réponse invalide (0, jamais dans bonnes_reponses)
                quiz_reponses[q_id] = (selected + 1) if selected is not None else 0
                st.session_state["quiz_reponses"] = quiz_reponses
                if quiz_index < total - 1:
                    st.session_state["quiz_index"] = quiz_index + 1
                else:
                    st.session_state["quiz_termine"] = True
                st.rerun()

    # ── Phase bilan ──────────────────────────────────────────
    else:
        bilan_texte = st.session_state.get("bilan_texte")

        # Construit la liste ResultatQuestion
        resultats: list[ResultatQuestion] = []
        for i, q in enumerate(questions):
            q_id = q.get("id", str(i))
            resultats.append(ResultatQuestion(
                id=q_id,
                question=nettoie_latex(q.get("question", "")),
                choix=[nettoie_latex(c) for c in q.get("choices", [])],
                bonnes_reponses=q.get("answers", []),
                reponse_eleve=quiz_reponses.get(q_id),
                explication=nettoie_latex(q.get("explanation", "")),
                keywords=q.get("keywords", []),
            ))

        score = sum(1 for r in resultats if r.est_correct)
        total = len(resultats)

        st.subheader(f"Score : {score} / {total}")

        # Tableau récapitulatif
        with st.expander("📊 Détail des réponses", expanded=True):
            for r in resultats:
                icone = "✅" if r.est_correct else "❌"
                st.markdown(f"{icone} **{r.question}**")
                if not r.est_correct:
                    st.caption(
                        f"Ta réponse : {r.libelle_reponse_eleve}  |  "
                        f"Bonne réponse : {r.libelle_bonne_reponse}"
                    )
                    if r.explication:
                        st.caption(f"Explication : {r.explication}")

        # Génération du bilan LLM — toujours visible pour relancer avec un autre modèle
        if st.button("🤖 Générer le bilan pédagogique" if langue == LANG_FR else "🤖 توليد الحصيلة البيداغوجية"):
            api_key = get_api_key()
            with st.spinner("Analyse en cours…" if langue == LANG_FR else "جارٍ التحليل…"):
                try:
                    bilan_texte = generer_bilan(
                        resultats=resultats,
                        cours_texte=st.session_state["cours_texte"],
                        api_key=api_key,
                        model_label=st.session_state.get("model_bilan", DEFAULT_MODEL),
                        lang=langue,
                    )
                    st.session_state["bilan_texte"] = bilan_texte
                    st.session_state["bilan_audio"] = None
                    st.rerun()
                except LLMError as e:
                    st.error(f"Erreur lors de la génération du bilan : {e}")

        if bilan_texte:
            st.divider()
            st.subheader("📝 Bilan pédagogique")
            if langue == LANG_AR:
                st.markdown(
                    f'<div dir="rtl" style="text-align:right;line-height:2">{_html.escape(bilan_texte)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(bilan_texte)

            # ── Conversion audio ─────────────────────────────────────
            tts_provider = st.session_state.get("tts_provider", DEFAULT_TTS)
            provider_key = TTS_PROVIDERS.get(tts_provider, TTS_PROVIDERS[DEFAULT_TTS])["key"]

            # Le sélecteur de genre n'a de sens que pour les providers à voix multiples
            if TTS_PROVIDERS.get(tts_provider, TTS_PROVIDERS[DEFAULT_TTS]).get("voix"):
                voix_options = list((VOIX_AR if langue == LANG_AR else VOIX_FR).keys())
                genre = st.radio(
                    "🎙️ Voix" if langue == LANG_FR else "🎙️ الصوت",
                    options=voix_options,
                    horizontal=True,
                    key="bilan_genre_voix",
                )
            else:
                genre = "Femme"

            if st.button("🔊 Écouter le bilan" if langue == LANG_FR else "🔊 استمع إلى الحصيلة"):
                with st.spinner("Génération de l'audio…" if langue == LANG_FR else "جارٍ إنشاء الصوت…"):
                    try:
                        audio_bytes, audio_format = bilan_vers_audio(
                            bilan_texte, lang=langue, genre=genre,
                            tts_provider=tts_provider,
                        )
                        st.session_state["bilan_audio"] = (audio_bytes, audio_format)
                    except Exception as e:
                        st.error(f"Erreur audio : {e}")

            if st.session_state.get("bilan_audio"):
                _audio_bytes, _audio_format = st.session_state["bilan_audio"]
                st.audio(_audio_bytes, format=_audio_format)

        st.divider()
        if st.button("🔄 Recommencer l'évaluation"):
            st.session_state["quiz_index"] = 0
            st.session_state["quiz_reponses"] = {}
            st.session_state["quiz_termine"] = False
            st.session_state["bilan_texte"] = None
            st.session_state["bilan_audio"] = None
            st.rerun()

    st.stop()

st.header("Pose ta question sur le cours")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Rejoue l'historique — on stocke la réponse finale uniquement
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        write_msg(msg["content"], lang=langue)

user_input = st.chat_input(
    "Écris ta question ici…" if langue == LANG_FR else "اكتب سؤالك هنا…",
    disabled="cours_texte" not in st.session_state,
)

if user_input:
    # Historique AVANT d'ajouter la question courante (pour le mode 3).
    historique = derniers_tours(st.session_state["messages"])

    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        write_msg(user_input, lang=langue)

    with st.chat_message("assistant"):
        api_key = get_api_key()

        # ════════════════════════════════════════════════════════════
        #  MODE 3 — Pipeline 3 couches (Generator → Judge → Refine)
        # ════════════════════════════════════════════════════════════
        if mode == MODE_PIPELINE:
            cadrage_slug_pipe = MODELS[model_generateur].get("cadrage")
            with st.status("Pipeline en cours…", expanded=True) as status:
                st.write("⚙️ Génération de la réponse…")
                resultat = repond(
                    user_input,
                    historique=historique,
                    cours_texte=st.session_state["cours_texte"],
                    api_key=api_key,
                    verif_path=st.session_state.get("verif_path"),
                    cadrage_slug=cadrage_slug_pipe,
                    model_generateur=model_generateur,
                    model_juge=model_juge_pipe,
                )
                if resultat["iterations"] > 0:
                    st.write("⚖️ Jugement + correction effectués")
                etat_final = "complete" if resultat["verdict"] in ("OK", "NOK", "CALCUL_FAUX") else "error"
                status.update(label="Terminé", state=etat_final, expanded=False)
            reponse_finale = resultat["reponse"]
            if resultat["verdict"] == "ERREUR":
                derniere_trace = resultat["trace"][-1] if resultat["trace"] else "Cause inconnue."
                st.error(f"Erreur technique du pipeline : {derniere_trace}")

        # ════════════════════════════════════════════════════════════
        #  MODES 1 & 2 — Single / Avec juge
        # ════════════════════════════════════════════════════════════
        else:
            with st.spinner("Réflexion…" if langue == LANG_FR else "جارٍ التفكير…"):
                try:
                    cadrage_slug = MODELS[model_repondant].get("cadrage")
                    system_prompt = build_system_prompt(
                        st.session_state["cours_texte"],
                        cadrage_slug=cadrage_slug,
                        lang=langue,
                    )
                    reponse_brute = call_one(
                        question=user_input, system_prompt=system_prompt,
                        api_key=api_key, model_label=model_repondant,
                        lang=langue,
                    )
                except LLMError as e:
                    st.error(f"Le modèle répondant est indisponible : {e}")
                    st.stop()

                if mode == MODE_JUGE:
                    verdict = call_judge(
                        question=user_input, reponse_candidate=reponse_brute,
                        cours_texte=st.session_state["cours_texte"],
                        api_key=api_key, model_label=model_juge,
                    )
                    reponse_finale = (
                        verdict.corrected
                        if (not verdict.valid and verdict.corrected)
                        else reponse_brute
                    )
                else:
                    reponse_finale = reponse_brute

        # Affichage de la réponse finale
        if reponse_finale:
            write_msg(reponse_finale, lang=langue)
        else:
            st.warning("Aucune réponse produite (voir le détail ci-dessous).")

        # ── Détail de débogage ───────────────────────────────────────────
        if mode == MODE_PIPELINE:
            badge = {
                "OK": "✅", "NOK": "❌", "CALCUL_FAUX": "🔢", "ERREUR": "⚠️",
            }.get(resultat["verdict"], "•")
            st.caption(
                f"{badge} verdict **{resultat['verdict']}** · "
                f"{resultat['iterations']} itération(s) · méthode `{resultat['methode']}`"
            )
            if resultat["reponse_v1"] and resultat["reponse_v1"] != reponse_finale:
                with st.expander(f"🤖 Réponse v1 — {model_generateur}"):
                    st.write(resultat["reponse_v1"])
            with st.expander("🧩 Trace du pipeline"):
                st.code("\n".join(resultat["trace"]), language="text")

        elif mode == MODE_JUGE:
            with st.expander(f"🤖 Réponse brute — {model_repondant}"):
                st.write(reponse_brute)

            verdict_icon = "✅" if verdict.valid else "❌"
            with st.expander(f"⚖️ Verdict du juge — {model_juge}"):
                st.markdown(f"**{verdict_icon} Verdict :** {'valide' if verdict.valid else 'invalide'}")
                st.markdown(f"**Raison :** {verdict.reason}")
                if verdict.corrected:
                    st.markdown("**Réponse corrigée par le juge :**")
                    st.write(verdict.corrected)

            with st.expander("✅ Réponse finale transmise à l'élève"):
                st.write(reponse_finale)

    st.session_state["messages"].append({"role": "assistant", "content": reponse_finale})
