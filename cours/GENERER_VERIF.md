# Générer un vérificateur Python pour un cours

## Comment faire

1. Ouvre [claude.ai](https://claude.ai) et colle le prompt ci-dessous
2. Claude te demande le cours → colle le contenu de `cours.txt`
3. Il génère le fichier `verif.py`
4. Teste-le localement : `python verif.py`
5. Dépose-le dans `cours/<slug>/verif.py` ou uploade-le via l'IHM (sidebar → "Vérificateur Python (.py)")

---

## Prompt à coller

```
Je veux que tu génères un vérificateur arithmétique Python pour un chatbot pédagogique.

**Contexte**
Le chatbot produit des réponses textuelles à des questions d'élèves. Un pipeline vérifie ces réponses AVANT de les envoyer à l'élève, en cherchant des erreurs de calcul via du Python déterministe (jamais un LLM). Le vérificateur est spécifique à chaque cours.

**Interface obligatoire**
Le fichier doit exposer exactement cette fonction :

def controle_calcul(reponse: str) -> tuple[bool, str]:
    """
    Retourne (calcul_ok, message_critique).
    - calcul_ok=True  → aucune erreur détectée, on passe au juge LLM.
    - calcul_ok=False → erreur détectée, message_critique décrit le problème.
    """

**Structure attendue du fichier**
1. Fonctions Python pures qui calculent la "vérité" (ex: pgcd(a,b), facteurs_premiers(n), resoudre_equation(...)) — jamais de LLM, jamais d'approximation.
2. Fonction `verifie_reponse(reponse: str) -> list[dict]` qui :
   - Extrait les affirmations chiffrées de la réponse via regex
   - Les revérifie avec les fonctions Python pures
   - Retourne une liste d'anomalies : [{"type": ..., "affirmation": ..., "attendu": ...}]
3. Fonction `controle_calcul(reponse: str) -> tuple[bool, str]` qui appelle `verifie_reponse` et formate le message.
4. Un bloc `if __name__ == "__main__":` avec 6 à 8 exemples de test (vrais et faux) pour valider le vérificateur.

**Règles de génération**
- N'extraire QUE les types d'affirmations réellement présents dans le cours (ex: si le cours ne parle pas d'équations, ne pas vérifier les équations).
- Utiliser des regex robustes qui tolèrent les variantes d'écriture naturelle (espaces, majuscules, ponctuation variable).
- En cas de doute sur un calcul extrait (regex trop ambiguë), ne pas signaler d'erreur (biais conservateur : mieux vaut laisser passer une erreur que bloquer une bonne réponse).
- Imports autorisés : re, math, et la bibliothèque standard uniquement.
- Commentaires en français.

**Ce que j'attends de toi**
Commence par me demander le contenu du cours. Je te le partagerai, puis tu généreras le fichier verif.py complet.
```

---

## Exemple de vérificateur existant

`cours/ch11_pgcd_diviseurs/verif.py` — vérifie les produits, PGCD, divisibilité et listes de diviseurs.
À consulter comme référence de style et de structure.
