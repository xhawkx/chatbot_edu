# CLAUDE.md

Contexte du projet pour Claude Code. À lire avant toute intervention.

## But du projet

Chatbot pédagogique (élève niveau collège / BEM). Il répond aux questions d'un
élève **en se basant strictement sur le contenu d'un cours fourni** (pas de
connaissances générales). Le cours est injecté **en entier** dans le prompt
système (approche "full-context" — plus de RAG depuis CH11, le cours étant
suffisamment court).

L'évaluation se fait en batch : un lot de questions (souvent ambiguës, en
langage SMS) est posé à **plusieurs LLMs en parallèle**, et les réponses sont
exportées dans un Excel multi-onglets avec scoring sémantique pour comparaison.

## ⚠️ Contrainte centrale : agnosticité au cours

Le cours actuel porte sur **CH11** (`data/Cours_CH_11_clean.txt`), mais **un
autre cours (toute matière) peut être chargé à la place**. Donc :

- **Ne jamais coder en dur** de notions ou exemples spécifiques au cours courant
  dans le code générique ou les prompts.
- Le cadrage (`data/cadrage_prompt.txt`) doit rester **neutre** : il décrit le
  comportement pédagogique, jamais le sujet du cours.

Pour charger un autre cours : changer **uniquement** `COURS_PATH` dans la cellule
`2acd1369`. Si le cours est trop long pour être injecté en entier, envisager de
revenir à une architecture RAG (cf. historique git).

## Fichier principal

`groq_batch.ipynb` — le pipeline complet. Cellules clés (par `cell_id`) :

| cell_id    | rôle |
|------------|------|
| `d7ccaab2` | charge `GROQ_API_KEY` et `OPENROUTER_API_KEY` depuis les variables d'env Windows (via PowerShell) |
| `2acd1369` | **cœur** : chargement cours (`COURS_PATH`), `nettoie_latex`, injection cours complet dans `SYSTEM_PROMPT_BASE` (logique 3 cas + règles style) |
| `6c90b137` | charge les questions depuis l'Excel (multi-feuilles, jointure par `idx`) |
| `95e389e4` | **sélection des modèles** : dict `MODELS` avec `actif: True/False` par modèle |
| `3009bf5a` | inférence parallèle : `CONSIGNE_BRIEVETE`, `call_one`, retries 429, **un thread par modèle actif** |
| `a46786ee` | export Excel stylé : un onglet par feuille de questions + onglet `Récap`, scoring sémantique cosine |

Les autres notebooks (`chat_local_llm.ipynb`, `gemini_test.ipynb`,
`groq_test.ipynb`) sont des bacs à sable / tests de providers — secondaires.

## Données (`data/`)

- `Cours_CH_11_clean.txt` — cours source actuellement chargé (pré-nettoyé par
  `clean_latex.ipynb`, puis repassé par `nettoie_latex` au chargement).
- `cadrage_prompt.txt` — cadrage pédagogique **générique** (sécurité, ton,
  gestion de l'ambiguïté). Concaténé en tête de `SYSTEM_PROMPT_BASE`.
- `Lot2_questions_CH11.xlsx` — lot d'évaluation courant. Colonnes : `id`,
  `question_ambigue_utilisateur`, `reponse_attendue`. Peut contenir plusieurs feuilles.
- `Cours_CH_11_clean_reponses_llm.xlsx` — **sortie** du pipeline (régénérée à
  chaque run). Colonnes : `id`, `question`, `reponse_attendue`,
  `reponse_<label>`, `score_<label>` pour chaque modèle actif + onglet `Récap`.
- Fichiers archivés suffixés — anciennes sorties conservées par modèle/run.

## Architecture full-context (pas de RAG)

Le cours (~2 400 caractères pour CH11) est injecté **en entier** dans le prompt
système. Cette approche a remplacé le RAG car :
- Le cours est suffisamment court pour tenir dans le contexte.
- Le RAG par chunks introduisait des faux refus (retrieval manqué).

**Logique de réponse à 3 cas** (dans `SYSTEM_PROMPT_BASE`, inchangée) :
1. L'information est présente dans le cours **ou** la question fournit ses propres
   données → répondre (y compris calculer).
2. Référent ambigu non levable → demander une précision courte.
3. Notion réellement absente du cours → refuser avec la phrase exacte.
Ne jamais confondre cas 2 et cas 3 (règle anti-confusion explicite dans le prompt).

**Scoring sémantique** (cellule `a46786ee`) : cosine similarity entre
`reponse_attendue` et `reponse_llm` via `paraphrase-multilingual-MiniLM-L12-v2`.
Seuils : vert ≥ 0.70, orange 0.40–0.69, rouge < 0.40.

> Si un futur cours est trop long pour être injecté en entier, consulter
> l'historique git pour récupérer le pipeline RAG (chunking fixe + recouvrement,
> garde-fou sur `SEUIL_CONFIANCE`).

## Objectifs qualité des réponses (demandés par l'utilisateur)

- **Courtes et synthétiques** : 1 à 2 phrases, style sujet-verbe-complément.
- **S'appuyer sur les formules/équations** du cours en priorité.
- **Pas de préambule** (« Bien sûr », « En effet », « D'après le cours »…) ni de
  formule de politesse, ni d'exemple chiffré non demandé.
- Pas de limite dure de tokens trop basse (certaines réponses légitimes
  dépassent ~80 tokens) ; `max_tokens=150`.

## Workflow d'évaluation typique

1. Activer/désactiver les modèles voulus dans le dict `MODELS` (cellule `95e389e4`).
2. Exécuter le notebook (l'utilisateur le fait dans l'IDE ; clés API + kernel
   requis).
3. Analyser `data/<cours>_reponses_llm.xlsx` : onglet `Récap` pour vue globale,
   puis onglet par feuille pour les détails. Critères : verdict par question
   (correct/partiel/incorrect), verbosité, refus injustifiés, hallucinations,
   glissements thématiques.
4. Itérer sur le prompt ou les modèles.

Patterns d'erreurs à surveiller (historiquement observés) : confusion
clarification/refus (cas 2 vs cas 3), verbosité, phrases passe-partout
hors-sujet, hallucination de contexte chiffré, réponse tronquée par `max_tokens`.

## Environnement & conventions

- Windows 11, shell **bash** (syntaxe Unix : `/dev/null`, slashes). `.venv` à la
  racine.
- `requirements.txt` est minimal ; le pipeline a aussi besoin de `groq`,
  `openai`, `openpyxl`, `sentence-transformers`, `scikit-learn`, `numpy`
  (cf. cellule `%pip install` commentée en tête de `groq_batch.ipynb`).
- **Éditer les notebooks via NotebookEdit** (l'outil Edit échoue sur `.ipynb`).
- Providers LLM disponibles dans le dict `MODELS` (cellule `95e389e4`) :
  - **Groq** (`provider: "groq"`) : llama-4-scout, llama-3.1-8b… Nécessite `GROQ_API_KEY`.
  - **OpenRouter** (`provider: "openrouter"`) : claude-sonnet-4-6, gemini-2.5-flash,
    deepseek-chat-v3, gemma-4-31b:free, gpt-oss-120b:free… Nécessite `OPENROUTER_API_KEY`.
  - **Ollama local** (`provider: "ollama"`) : mistral-small (aucune clé requise).
  - Les deux clés sont chargées depuis les variables d'env utilisateur Windows.
- Réponses et commentaires de code **en français** (public cible francophone).
