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

st.set_page_config(page_title="Chatbot pédagogique v2", page_icon="📚", layout="centered")

# Three comparable modes (single answer / LLM judge / 3-layer pipeline).
MODE_SINGLE = "💬 Single"
MODE_JUGE = "⚖️ Avec juge"
MODE_PIPELINE = "🧩 3 couches"
MODES = [MODE_SINGLE, MODE_JUGE, MODE_PIPELINE]


_AR_RE = re.compile(r"[؀-ۿ]")


def write_msg(text: str, lang: str = LANG_FR) -> None:
    """Affiche un message en respectant la direction RTL pour l'arabe."""
    if lang == LANG_AR:
        st.markdown(
            f'<div dir="rtl" style="text-align:right">{_html.escape(text)}</div>',
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

    # ── Choix de la langue (Mode 1 uniquement) ───────────────────────
    if mode == MODE_SINGLE:
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
