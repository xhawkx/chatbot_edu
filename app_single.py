import os
import streamlit as st
from core.auth import check_auth, login_form, logout
from core.latex import nettoie_latex
from core.prompt import build_system_prompt
from core.llm import call_one, LLMError, MODELS, DEFAULT_MODEL

st.set_page_config(page_title="Chatbot pédagogique", page_icon="📚", layout="centered")


def get_api_key() -> str:
    """Résout la clé OpenRouter : st.secrets (déploiement) puis variable d'env."""
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
with st.sidebar:
    st.title("📚 Chatbot pédagogique")

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

    model_label = st.selectbox(
        "Modèle",
        options=list(MODELS.keys()),
        index=list(MODELS.keys()).index(DEFAULT_MODEL),
    )

    if st.button("🗑️ Réinitialiser la conversation"):
        st.session_state["messages"] = []
        st.rerun()

# ── Zone principale ────────────────────────────────────────────────────────
st.header("Pose ta question sur le cours")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

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
            try:
                cadrage_slug = MODELS[model_label].get("cadrage")
                system_prompt = build_system_prompt(
                    st.session_state["cours_texte"],
                    cadrage_slug=cadrage_slug,
                )
                reponse = call_one(
                    question=user_input,
                    system_prompt=system_prompt,
                    api_key=get_api_key(),
                    model_label=model_label,
                )
            except LLMError as e:
                st.error(f"Le chatbot est momentanément indisponible : {e}")
                st.stop()
        st.write(reponse)

    st.session_state["messages"].append({"role": "assistant", "content": reponse})
