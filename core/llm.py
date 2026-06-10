import re, time
from openai import OpenAI

MODELS = {
    "GPT-OSS 120B (défaut)":  {"provider": "openrouter", "name": "openai/gpt-oss-120b:free",                          "cadrage": "gpt-oss-120b"},
    "Llama 4 Scout":           {"provider": "openrouter", "name": "meta-llama/llama-4-scout-17b-16e-instruct",         "cadrage": "llama-4-scout"},
    "DeepSeek Chat v3":        {"provider": "openrouter", "name": "deepseek/deepseek-chat-v3-0324",                    "cadrage": "deepseek-chat-v3"},
    "Gemma 4 31B":             {"provider": "openrouter", "name": "google/gemma-4-31b-it:free",                        "cadrage": "gemma-4-31b"},
    "Gemini 2.5 Flash":        {"provider": "openrouter", "name": "google/gemini-2.5-flash",                           "cadrage": "gemini-2.5-flash"},
}

DEFAULT_MODEL = "GPT-OSS 120B (défaut)"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_TOKENS = 150


class LLMError(Exception):
    """Erreur technique lors de l'appel au modèle (réseau, quota, réponse vide…).

    À distinguer d'une vraie réponse pédagogique : l'appelant attrape cette
    exception pour la logger ou l'afficher, sans la confondre avec le contenu.
    """


def _parse_retry_delay(msg: str) -> float:
    m = re.search(r"(\d+)m(\d+(?:\.\d+)?)s", str(msg))
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 5
    m = re.search(r"(\d+(?:\.\d+)?)s", str(msg))
    return float(m.group(1)) + 5 if m else 60.0


def call_one(question: str, system_prompt: str, api_key: str,
             model_label: str = DEFAULT_MODEL, *,
             base_url: str = DEFAULT_BASE_URL,
             max_tokens: int = DEFAULT_MAX_TOKENS,
             max_retries: int = 3,
             add_consigne: bool = True,
             historique: list | None = None) -> str:
    """Interroge un modèle et retourne sa réponse textuelle.

    La clé API est injectée par l'appelant (la couche métier ne devine pas la
    config). Lève `LLMError` en cas de problème technique.
    Passer `add_consigne=False` pour les appels non pédagogiques (ex. juge).
    `historique` : liste de tours {"role", "content"} insérés avant la question
    courante (multi-turn). None = appel sans contexte conversationnel.
    """
    if not api_key:
        raise LLMError("Clé API manquante.")

    cfg = MODELS[model_label]
    client = OpenAI(api_key=api_key, base_url=base_url)

    if add_consigne:
        from core.prompt import CONSIGNE_BRIEVETE
        user_content = CONSIGNE_BRIEVETE + "\n\nQuestion de l'élève : " + question
    else:
        user_content = question

    messages = [{"role": "system", "content": system_prompt}]
    if historique:
        messages.extend(historique)
    messages.append({"role": "user", "content": user_content})

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=cfg["name"], messages=messages,
                temperature=0, max_tokens=max_tokens,
            )
            if not resp.choices:
                raise LLMError("Réponse vide (filtrage ou surcharge modèle).")
            content = resp.choices[0].message.content
            if content is None:
                raise LLMError("Réponse vide (content=None).")
            return content.strip()
        except LLMError:
            raise
        except Exception as e:
            if "429" in str(e):
                time.sleep(_parse_retry_delay(str(e)))
            else:
                raise LLMError(str(e)) from e
    raise LLMError("Nombre maximum de tentatives atteint (quota).")
