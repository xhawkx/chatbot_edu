# Chatbot pédagogique

Outil d'aide à l'apprentissage pour élèves (niveau collège / BEM). Le chatbot répond aux questions d'un élève **en se basant uniquement sur le contenu d'un cours fourni** — pas de connaissances générales, pas de RAG. Le cours est injecté en entier dans le prompt système (approche *full-context*).

Le projet comprend deux composants :

- **`app.py`** — interface Streamlit pour une utilisation interactive par un élève.
- **`groq_batch.ipynb`** — pipeline d'évaluation en batch : plusieurs LLMs en parallèle, export Excel multi-onglets avec scoring sémantique.

---

## Fonctionnalités

- Chargement d'un cours au format `.txt` (nettoyage LaTeX automatique)
- Réponses courtes et synthétiques, fondées sur les formules/équations du cours
- Logique à 3 cas : répondre / demander une précision / refuser poliment
- Authentification simple (identifiants via `st.secrets`)
- Sélection du modèle LLM en temps réel
- **Mode juge LLM** : un second modèle évalue et corrige la réponse du premier avant de l'afficher
- Évaluation en batch multi-modèles avec scoring cosine (onglet `Récap`)

## Modèles disponibles (via OpenRouter)

| Label | Modèle |
|---|---|
| GPT-OSS 120B (défaut) | `openai/gpt-oss-120b:free` |
| Llama 4 Scout | `meta-llama/llama-4-scout-17b-16e-instruct` |
| DeepSeek Chat v3 | `deepseek/deepseek-chat-v3-0324` |
| Gemma 4 31B | `google/gemma-4-31b-it:free` |
| Gemini 2.5 Flash | `google/gemini-2.5-flash` |

---

## Installation

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows bash
pip install -r requirements.txt
```

`requirements.txt` contient uniquement les dépendances de l'application web (`streamlit`, `openai`). Les dépendances du notebook d'évaluation (`groq`, `sentence-transformers`, `scikit-learn`, etc.) s'installent séparément via la cellule `%pip install` en tête de `groq_batch.ipynb`.

## Configuration

### Clé API

La clé OpenRouter est lue dans cet ordre de priorité :

1. `st.secrets["OPENROUTER_API_KEY"]` (Streamlit Cloud)
2. Variable d'environnement `OPENROUTER_API_KEY`

En local, créer `.streamlit/secrets.toml` :

```toml
OPENROUTER_API_KEY = "sk-or-..."

[CREDENTIALS]
username = "eleve"
password = "motdepasse"
```

### Authentification

Les identifiants sont lus depuis `st.secrets["CREDENTIALS"]`. Valeurs par défaut si absent : `admin` / `admin`.

---

## Lancer l'application

```bash
streamlit run app.py
```

## Structure du projet

```
chatbot_edu/
├── app.py                          # Interface Streamlit
├── core/
│   ├── auth.py                     # Authentification
│   ├── latex.py                    # Nettoyage LaTeX
│   ├── llm.py                      # Appels LLM (OpenRouter)
│   ├── prompt.py                   # Construction du prompt système
│   └── judge.py                    # Juge LLM (évaluation/correction)
├── data/
│   ├── cadrage/
│   │   ├── default.txt             # Cadrage pédagogique générique
│   │   ├── gpt-oss-120b.txt        # Cadrages spécifiques par modèle
│   │   └── ...
│   ├── Cours_CH_11_clean.txt       # Cours source (remplaçable)
│   └── Lot2_questions_CH11.xlsx    # Questions d'évaluation
├── groq_batch.ipynb                # Pipeline d'évaluation en batch
└── requirements.txt
```

---

## Pipeline d'évaluation (notebook)

1. Activer/désactiver les modèles dans le dict `MODELS` (cellule `95e389e4`).
2. Exécuter `groq_batch.ipynb` (kernel Python + clés API requises).
3. Analyser `data/<cours>_reponses_llm.xlsx` :
   - Onglet `Récap` : vue globale par modèle
   - Onglets par feuille : détail question par question
4. Seuils de score cosine : vert ≥ 0.70, orange 0.40–0.69, rouge < 0.40

## Changer de cours

Modifier uniquement `COURS_PATH` dans la cellule `2acd1369` du notebook, ou charger un nouveau fichier `.txt` via l'interface Streamlit. Le cadrage pédagogique (`data/cadrage/default.txt`) est générique et ne doit pas mentionner de notions propres au cours courant.

---

## Contraintes & notes

- `max_tokens=150` — suffisant pour des réponses synthétiques, évite la verbosité.
- Retry automatique sur erreur 429 (rate limit), délai extrait du message d'erreur.
- Le cours CH11 fait ~2 400 caractères et tient dans le contexte. Pour un cours plus long, consulter l'historique git pour récupérer le pipeline RAG.
