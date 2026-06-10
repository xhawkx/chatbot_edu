"""
Vérificateur arithmétique déterministe pour le chatbot pédagogique (diviseurs/PGCD).

⚠️ SPÉCIFIQUE AU COURS CH11 (PGCD / diviseurs). Chaque cours qui le nécessite
fournit son propre `verif.py` dans son dossier `cours/<slug>/`. Un cours sans
calculs vérifiables peut simplement ne pas avoir de `verif.py` : l'orchestrateur
le détecte et court-circuite la vérification (cf. core/pipeline/orchestrator.py).

Principe : on n'utilise JAMAIS un LLM pour vérifier un calcul.
On extrait les affirmations chiffrables de la réponse du générateur,
puis on les revérifie avec du Python pur. Le résultat prime sur tout LLM.

Retour : liste d'anomalies. Liste vide = aucun calcul faux détecté.
"""

import re
import math


# ─────────────────────────────────────────────────────────────
#  VÉRITÉS DE BASE (Python pur, déterministe)
# ─────────────────────────────────────────────────────────────

def divise(b: int, a: int) -> bool:
    """b est-il un diviseur de a ?  (reste nul)"""
    return b != 0 and a % b == 0


def diviseurs(n: int) -> set:
    """Ensemble de tous les diviseurs de n (méthode de l'encadrement)."""
    if n <= 0:
        return set()
    divs = set()
    for b in range(1, int(math.isqrt(n)) + 1):
        if n % b == 0:
            divs.add(b)
            divs.add(n // b)   # le grand diviseur image
    return divs


def pgcd(a: int, b: int) -> int:
    """PGCD via l'algorithme standard de la bibliothèque."""
    return math.gcd(a, b)


# ─────────────────────────────────────────────────────────────
#  EXTRACTION DES AFFIRMATIONS depuis la réponse du LLM
# ─────────────────────────────────────────────────────────────

def verifie_reponse(reponse: str) -> list:
    """Analyse la réponse du LLM et renvoie la liste des anomalies trouvées.

    Chaque anomalie = dict {type, affirmation, attendu}.
    Liste vide => aucun calcul faux détecté.
    """
    anomalies = []
    txt = reponse.replace("×", "x").replace("·", "x")

    # ── 1. "a = b x c"  → vérifier que le produit est exact ──
    for m in re.finditer(r"(\d+)\s*=\s*(\d+)\s*x\s*(\d+)", txt):
        a, b, c = map(int, m.groups())
        if b * c != a:
            anomalies.append({
                "type": "produit",
                "affirmation": f"{a} = {b} x {c}",
                "attendu": f"{b} x {c} = {b * c}",
            })

    # ── 2. "PGCD(a, b) = g"  → recalculer ──
    for m in re.finditer(r"PGCD\s*\(\s*(\d+)\s*[;,]\s*(\d+)\s*\)\s*=\s*(\d+)", txt, re.I):
        a, b, g = map(int, m.groups())
        vrai = pgcd(a, b)
        if g != vrai:
            anomalies.append({
                "type": "pgcd",
                "affirmation": f"PGCD({a}, {b}) = {g}",
                "attendu": f"PGCD({a}, {b}) = {vrai}",
            })

    # ── 3. "X divise Y"  → vérifier la divisibilité ──
    for m in re.finditer(r"(\d+)\s+divise\s+(\d+)", txt, re.I):
        b, a = int(m.group(1)), int(m.group(2))
        if not divise(b, a):
            anomalies.append({
                "type": "divisibilite",
                "affirmation": f"{b} divise {a}",
                "attendu": f"{b} ne divise PAS {a} (reste {a % b})",
            })

    # ── 4. "les diviseurs de N sont {...}"  → comparer l'ensemble ──
    m = re.search(r"diviseurs\s+(?:du nombre\s+|de\s+)?(\d+)\s+sont\s*[:\s]*\{?([\d,\s]+)\}?",
                  txt, re.I)
    if m:
        n = int(m.group(1))
        cites = {int(x) for x in re.findall(r"\d+", m.group(2))}
        vrai = diviseurs(n)
        if cites != vrai:
            anomalies.append({
                "type": "liste_diviseurs",
                "affirmation": f"diviseurs de {n} = {sorted(cites)}",
                "attendu": f"diviseurs de {n} = {sorted(vrai)} "
                           f"(manquants : {sorted(vrai - cites)}, "
                           f"en trop : {sorted(cites - vrai)})",
            })

    return anomalies


# ─────────────────────────────────────────────────────────────
#  INTÉGRATION DANS LE PIPELINE
# ─────────────────────────────────────────────────────────────

def controle_calcul(reponse: str) -> tuple:
    """Point d'entrée pour le pipeline.

    Retourne (calcul_ok: bool, message_critique: str).
    - calcul_ok=True  → on passe au juge LLM normalement.
    - calcul_ok=False → on saute directement au Refine avec le message.
    """
    anomalies = verifie_reponse(reponse)
    if not anomalies:
        return True, ""

    lignes = ["Erreur(s) de calcul détectée(s) par vérification déterministe :"]
    for a in anomalies:
        lignes.append(f"  • {a['affirmation']}  →  {a['attendu']}")
    return False, "\n".join(lignes)


if __name__ == "__main__":
    exemples = [
        "5 divise 30. 30 = 5 x 6",
        "7 divise 30",
        "Les diviseurs de 32 sont {1, 2, 4, 8, 16, 32}",
        "Les diviseurs de 32 sont {1, 2, 4, 8, 32}",
        "PGCD(15, 25) = 5",
        "PGCD(12, 18) = 9",
        "32 = 4 x 8",
        "32 = 4 x 9",
    ]
    for ex in exemples:
        ok, msg = controle_calcul(ex)
        statut = "OK " if ok else "NOK"
        print(f"[{statut}] {ex}")
        if not ok:
            print(f"       {msg.splitlines()[-1].strip()}")
