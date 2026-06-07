import os, re, time, subprocess
from openai import OpenAI

MODELS = {
    "GPT-OSS 120B (défaut)":  {"provider": "openrouter", "name": "openai/gpt-oss-120b:free"},
    "Llama 4 Scout":           {"provider": "openrouter", "name": "meta-llama/llama-4-scout-17b-16e-instruct"},
    "DeepSeek Chat v3":        {"provider": "openrouter", "name": "deepseek/deepseek-chat-v3-0324"},
    "Gemma 4 31B":             {"provider": "openrouter", "name": "google/gemma-4-31b-it:free"},
    "Gemini 2.5 Flash":        {"provider": "openrouter", "name": "google/gemini-2.5-flash"},
}

DEFAULT_MODEL = "GPT-OSS 120B (défaut)"


def _get_api_key() -> str:
    # Streamlit Cloud : st.secrets (importé dynamiquement pour ne pas forcer la dép)
    try:
        import streamlit as st
        if "OPENROUTER_API_KEY" in st.secrets:
            return st.secrets["OPENROUTER_API_KEY"]
    except Exception:
        pass
    # Variable d'env (local Windows après chargement par le notebook ou l'OS)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    # Fallback : lecture directe depuis les variables utilisateur Windows
    try:
        r = subprocess.run(
            ["powershell.exe", "-Command",
             "[System.Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User')"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _parse_retry_delay(msg: str) -> float:
    m = re.search(r"(\d+)m(\d+(?:\.\d+)?)s", str(msg))
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 5
    m = re.search(r"(\d+(?:\.\d+)?)s", str(msg))
    return float(m.group(1)) + 5 if m else 60.0


def call_one(question: str, system_prompt: str, model_label: str = DEFAULT_MODEL,
             max_retries: int = 3) -> str:
    from core.prompt import CONSIGNE_BRIEVETE

    cfg = MODELS[model_label]
    api_key = _get_api_key()
    if not api_key:
        return "ERREUR : clé OPENROUTER_API_KEY introuvable."

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": CONSIGNE_BRIEVETE + "\n\nQuestion de l'élève : " + question},
    ]

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=cfg["name"], messages=messages,
                temperature=0, max_tokens=150,
            )
            if not resp.choices:
                return "ERREUR : réponse vide (filtrage ou surcharge modèle)."
            content = resp.choices[0].message.content
            if content is None:
                return "ERREUR : réponse vide (content=None)."
            return content.strip()
        except Exception as e:
            if "429" in str(e):
                delay = _parse_retry_delay(str(e))
                time.sleep(delay)
            else:
                return f"ERREUR : {e}"
    return "ERREUR : nombre maximum de tentatives atteint."
