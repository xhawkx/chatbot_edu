import streamlit as st


def check_auth() -> bool:
    """Retourne True si l'utilisateur est authentifié, False sinon."""
    return st.session_state.get("authenticated", False)


def login_form() -> None:
    """Affiche le formulaire de login."""
    st.title("🔐 Accès protégé")
    st.write("Veuillez vous identifier pour accéder à l'application.")

    try:
        credentials = st.secrets.get("CREDENTIALS", {})
        valid_login = credentials.get("username", "admin")
        valid_password = credentials.get("password", "admin")
    except Exception:
        st.error("Erreur : Identifiants non configurés.")
        return

    with st.form("login_form"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Connexion")

        if submit:
            if username == valid_login and password == valid_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Identifiant ou mot de passe incorrect.")


def logout() -> None:
    """Déconnecte l'utilisateur."""
    st.session_state["authenticated"] = False
    st.rerun()
