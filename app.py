import os
import streamlit as st
from core.auth import check_auth, login_form, logout
from core.latex import nettoie_latex
from core.prompt import build_system_prompt
from core.llm import call_one, LLMError, MODELS, DEFAULT_MODEL
from core.judge import call_judge

st.set_page_config(page_title="Chatbot pédagogique v2 (avec juge)", page_icon="📚", layout="centered")


def get_api_key() -> str:
    try:
        if "OPENROUTER_API_KEY" in st.secrets:
            return st.secrets["OPENROUTER_API_KEY"]
    except Exception:
        pass
    return os.environ.get("OPENROUTER_API_KEY", "")


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

    uploaded = st.file_uploader("Charger un cours (.txt)", type=["txt"])
    if uploaded is not None:
        raw = uploaded.read().decode("utf-8")
        st.session_state["cours_texte"] = nettoie_latex(raw)
        st.session_state["cours_nom"] = uploaded.name
        st.session_state["messages"] = []
        st.success(f"{uploaded.name} — {len(st.session_state['cours_texte'])} caractères")

    if "cours_nom" in st.session_state:
        st.caption(f"Cours actif : **{st.session_state['cours_nom']}**")
    else:
        st.info("Chargez un cours pour commencer.")

    st.divider()

    st.subheader("Modèles")
    mode_juge = st.toggle("⚖️ Activer le juge LLM", value=False, key="mode_juge")

    model_repondant = st.selectbox(
        "🤖 Modèle répondant",
        options=model_keys,
        index=default_idx,
        key="model_repondant",
    )
    if mode_juge:
        model_juge = st.selectbox(
            "⚖️ Modèle juge",
            options=model_keys,
            index=default_idx,
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
        st.write(msg["content"])

user_input = st.chat_input(
    "Écris ta question ici…",
    disabled="cours_texte" not in st.session_state,
)

if user_input:
    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Réflexion…"):
            api_key = get_api_key()

            # ── Étape 1 : répondant ──────────────────────────────────────
            try:
                cadrage_slug = MODELS[model_repondant].get("cadrage")
                system_prompt = build_system_prompt(
                    st.session_state["cours_texte"],
                    cadrage_slug=cadrage_slug,
                )
                reponse_brute = call_one(
                    question=user_input,
                    system_prompt=system_prompt,
                    api_key=api_key,
                    model_label=model_repondant,
                )
            except LLMError as e:
                st.error(f"Le modèle répondant est indisponible : {e}")
                st.stop()

            # ── Étape 2 : juge (optionnel) ───────────────────────────────
            if mode_juge:
                verdict = call_judge(
                    question=user_input,
                    reponse_candidate=reponse_brute,
                    cours_texte=st.session_state["cours_texte"],
                    api_key=api_key,
                    model_label=model_juge,
                )
                reponse_finale = (
                    verdict.corrected
                    if (not verdict.valid and verdict.corrected)
                    else reponse_brute
                )
            else:
                reponse_finale = reponse_brute

        # Affichage de la réponse finale
        st.write(reponse_finale)

        # ── Détail de débogage ───────────────────────────────────────────
        if mode_juge:
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
