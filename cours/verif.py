"""
Vérificateur arithmétique déterministe pour le cours :
"Les diviseurs d'un nombre naturel".

Le module expose la fonction obligatoire :
    controle_calcul(reponse: str) -> tuple[bool, str]

Principe :
- Le vérificateur extrait uniquement des affirmations chiffrées liées au cours :
  diviseurs, divisibilité, multiples, diviseurs communs, PGCD,
  nombres premiers entre eux, listes/couples de diviseurs et calculs simples.
- En cas d'ambiguïté, il ne bloque pas la réponse.
- Aucun LLM, aucune approximation : uniquement du Python déterministe.
"""

import math
import re


# ---------------------------------------------------------------------------
# 1. Fonctions Python pures : vérité mathématique du cours
# ---------------------------------------------------------------------------

MAX_N_DIVISEURS = 1_000_000


def pgcd(a: int, b: int) -> int:
    """Retourne le plus grand commun diviseur de deux entiers naturels."""
    return math.gcd(abs(a), abs(b))


def est_diviseur(b: int, a: int) -> bool:
    """Retourne True si b est un diviseur de a, avec b non nul."""
    return b != 0 and a % b == 0


def est_multiple(a: int, b: int) -> bool:
    """Retourne True si a est un multiple de b."""
    return est_diviseur(b, a)


def sont_premiers_entre_eux(a: int, b: int) -> bool:
    """Deux nombres sont premiers entre eux si leur PGCD vaut 1."""
    return pgcd(a, b) == 1


def diviseurs(n: int) -> list[int]:
    """
    Retourne tous les diviseurs positifs de n, triés dans l'ordre croissant.
    Pour rester dans le cadre du cours, on ne traite que les naturels non nuls.
    """
    if n <= 0:
        return []

    petits = []
    grands = []
    limite = math.isqrt(n)

    for d in range(1, limite + 1):
        if n % d == 0:
            petits.append(d)
            autre = n // d
            if autre != d:
                grands.append(autre)

    return petits + grands[::-1]


def diviseurs_communs(a: int, b: int) -> list[int]:
    """Retourne les diviseurs communs positifs de a et b."""
    if a <= 0 or b <= 0:
        return []
    return [d for d in diviseurs(pgcd(a, b))]


def couple_de_diviseurs(b: int, c: int, a: int) -> bool:
    """Retourne True si {b ; c} est bien un couple de diviseurs de a."""
    return b * c == a and est_diviseur(b, a) and est_diviseur(c, a)


def borne_racine_pour_tests(a: int) -> int:
    """
    Dans la méthode du carré, on teste les entiers de 1 à floor(sqrt(a)).
    """
    if a < 0:
        raise ValueError("La méthode du cours concerne les nombres naturels.")
    return math.isqrt(a)


# ---------------------------------------------------------------------------
# 2. Outils d'extraction conservateurs
# ---------------------------------------------------------------------------


def _normalise_texte(texte: str) -> str:
    """
    Normalise légèrement le texte pour rendre les regex robustes :
    - minuscules ;
    - accents français courants retirés ;
    - espaces spéciaux harmonisés.

    On évite unicodedata.normalize afin de ne pas transformer le symbole ² en 2.
    """
    table = str.maketrans(
        {
            "à": "a", "â": "a", "ä": "a", "á": "a", "ã": "a",
            "ç": "c",
            "é": "e", "è": "e", "ê": "e", "ë": "e",
            "î": "i", "ï": "i", "í": "i", "ì": "i",
            "ô": "o", "ö": "o", "ó": "o", "ò": "o", "õ": "o",
            "ù": "u", "û": "u", "ü": "u", "ú": "u",
            "ÿ": "y",
            "œ": "oe",
            "À": "a", "Â": "a", "Ä": "a", "Á": "a", "Ã": "a",
            "Ç": "c",
            "É": "e", "È": "e", "Ê": "e", "Ë": "e",
            "Î": "i", "Ï": "i", "Í": "i", "Ì": "i",
            "Ô": "o", "Ö": "o", "Ó": "o", "Ò": "o", "Õ": "o",
            "Ù": "u", "Û": "u", "Ü": "u", "Ú": "u",
            "Ÿ": "y",
            "Œ": "oe",
            "’": "'",
            "−": "-",
            "–": "-",
            "—": "-",
            "\u00a0": " ",
        }
    )
    texte = texte.translate(table).lower()
    texte = re.sub(r"[ \t]+", " ", texte)
    return texte


def _entiers(segment: str) -> list[int]:
    """Extrait les entiers positifs d'un segment de texte."""
    return [int(x) for x in re.findall(r"\d+", segment)]


def _format_liste(valeurs: list[int] | set[int]) -> str:
    """Formate une liste d'entiers comme dans le cours : {1, 2, 3}."""
    return "{" + ", ".join(str(v) for v in sorted(valeurs)) + "}"


def _ajoute_anomalie(
    anomalies: list[dict],
    type_: str,
    affirmation: str,
    attendu: str,
) -> None:
    """Ajoute une anomalie au format demandé."""
    anomalies.append(
        {
            "type": type_,
            "affirmation": affirmation.strip(),
            "attendu": attendu,
        }
    )


def _relation_ok(gauche: int, operateur: str, droite: int) -> bool:
    """Vérifie une relation d'ordre simple."""
    if operateur in {"<", "‹"}:
        return gauche < droite
    if operateur in {"<=", "=<", "≤"}:
        return gauche <= droite
    return False


def _contexte_non_exhaustif(texte: str, debut: int) -> bool:
    """
    Détecte des formulations du type 'quelques diviseurs de...'.
    Dans ce cas, on ne compare pas à la liste complète des diviseurs.
    """
    fenetre = texte[max(0, debut - 30):debut]
    return bool(re.search(r"\b(quelques|certains|des|parmi)\s+$", fenetre))


# ---------------------------------------------------------------------------
# 3. Vérification des affirmations chiffrées
# ---------------------------------------------------------------------------


def verifie_reponse(reponse: str) -> list[dict]:
    """
    Extrait des affirmations chiffrées de la réponse et les revérifie.

    Retourne une liste d'anomalies :
        [{"type": ..., "affirmation": ..., "attendu": ...}]

    Biais conservateur : si une affirmation est trop ambiguë pour être extraite
    proprement, elle est ignorée plutôt que bloquée.
    """
    texte = _normalise_texte(reponse)
    anomalies: list[dict] = []

    # -------------------------------------------------------------------
    # Divisibilité : formulations positives
    # -------------------------------------------------------------------

    patterns_divisibilite_positive = [
        # "6 est un diviseur de 120"
        (r"\b(\d+)\s+est\s+(?:un\s+)?diviseur\s+de\s+(\d+)\b", "diviseur"),
        # "5 divise 30" ou "5 divise également 10"
        (r"\b(\d+)\s+divise(?:\s+egalement|\s+aussi)?\s+(\d+)\b", "divise"),
        # "120 est divisible par 6"
        (r"\b(\d+)\s+est\s+divisible\s+par\s+(\d+)\b", "divisible"),
        # "120 est un multiple de 6"
        (r"\b(\d+)\s+est\s+(?:un\s+)?multiple\s+de\s+(\d+)\b", "multiple"),
    ]

    for pattern, type_pattern in patterns_divisibilite_positive:
        for m in re.finditer(pattern, texte):
            x = int(m.group(1))
            y = int(m.group(2))

            if type_pattern in {"diviseur", "divise"}:
                diviseur_candidat, nombre = x, y
                if not est_diviseur(diviseur_candidat, nombre):
                    _ajoute_anomalie(
                        anomalies,
                        "divisibilite",
                        m.group(0),
                        f"{diviseur_candidat} ne divise pas {nombre} car {nombre} % {diviseur_candidat} = {nombre % diviseur_candidat if diviseur_candidat != 0 else 'impossible'}.",
                    )
            else:
                nombre, diviseur_candidat = x, y
                if not est_diviseur(diviseur_candidat, nombre):
                    _ajoute_anomalie(
                        anomalies,
                        "divisibilite",
                        m.group(0),
                        f"{nombre} n'est pas divisible par {diviseur_candidat} car {nombre} % {diviseur_candidat} = {nombre % diviseur_candidat if diviseur_candidat != 0 else 'impossible'}.",
                    )

    # "5 divise à la fois 15 et 25" / "5 divise 15 et 25"
    for m in re.finditer(r"\b(\d+)\s+divise\s+(?:a\s+la\s+fois\s+)?(\d+)\s+et\s+(\d+)\b", texte):
        d, a, b = map(int, m.groups())
        if not (est_diviseur(d, a) and est_diviseur(d, b)):
            mauvais = [str(n) for n in (a, b) if not est_diviseur(d, n)]
            _ajoute_anomalie(
                anomalies,
                "diviseur_commun",
                m.group(0),
                f"{d} devrait diviser les deux nombres. Ce n'est pas le cas pour : {', '.join(mauvais)}.",
            )

    # "5 est un diviseur commun de 15 et 25"
    for m in re.finditer(r"\b(\d+)\s+est\s+(?:un\s+)?diviseur\s+commun\s+(?:de|a)\s+(\d+)\s+et\s+(\d+)\b", texte):
        d, a, b = map(int, m.groups())
        if not (est_diviseur(d, a) and est_diviseur(d, b)):
            _ajoute_anomalie(
                anomalies,
                "diviseur_commun",
                m.group(0),
                f"Un diviseur commun doit diviser {a} et {b}. Ici, {d} ne divise pas les deux.",
            )

    # -------------------------------------------------------------------
    # Divisibilité : formulations négatives
    # -------------------------------------------------------------------

    patterns_divisibilite_negative = [
        # "3 n'est pas un diviseur de 9"
        (r"\b(\d+)\s+n'\s*est\s+pas\s+(?:un\s+)?diviseur\s+de\s+(\d+)\b", "diviseur"),
        # "3 ne divise pas 9"
        (r"\b(\d+)\s+ne\s+divise\s+pas\s+(\d+)\b", "divise"),
        # "9 n'est pas divisible par 3"
        (r"\b(\d+)\s+n'\s*est\s+pas\s+divisible\s+par\s+(\d+)\b", "divisible"),
        # "9 n'est pas un multiple de 3"
        (r"\b(\d+)\s+n'\s*est\s+pas\s+(?:un\s+)?multiple\s+de\s+(\d+)\b", "multiple"),
    ]

    for pattern, type_pattern in patterns_divisibilite_negative:
        for m in re.finditer(pattern, texte):
            x = int(m.group(1))
            y = int(m.group(2))

            if type_pattern in {"diviseur", "divise"}:
                diviseur_candidat, nombre = x, y
                if est_diviseur(diviseur_candidat, nombre):
                    _ajoute_anomalie(
                        anomalies,
                        "divisibilite_negative",
                        m.group(0),
                        f"{diviseur_candidat} divise bien {nombre} car {nombre} = {diviseur_candidat} × {nombre // diviseur_candidat}.",
                    )
            else:
                nombre, diviseur_candidat = x, y
                if est_diviseur(diviseur_candidat, nombre):
                    _ajoute_anomalie(
                        anomalies,
                        "divisibilite_negative",
                        m.group(0),
                        f"{nombre} est bien divisible par {diviseur_candidat} car {nombre} = {diviseur_candidat} × {nombre // diviseur_candidat}.",
                    )

    # -------------------------------------------------------------------
    # PGCD
    # -------------------------------------------------------------------

    patterns_pgcd = [
        # "PGCD(12 ; 18) = 6"
        r"\bpgcd\s*\(?\s*(\d+)\s*[,;]\s*(\d+)\s*\)?\s*(?:=|:|est|vaut)\s*(\d+)\b",
        # "le PGCD de 12 et 18 est 6"
        r"\bpgcd\s+de\s+(\d+)\s+(?:et|,|;)\s+(\d+)\s*(?:=|:|est|vaut)\s*(\d+)\b",
        # "le plus grand commun diviseur de 12 et 18 est 6"
        r"\bplus\s+grand\s+commun\s+diviseur\s+de\s+(\d+)\s+(?:et|,|;)\s+(\d+)\s*(?:=|:|est|vaut)\s*(\d+)\b",
    ]

    for pattern in patterns_pgcd:
        for m in re.finditer(pattern, texte):
            a, b, annonce = map(int, m.groups())
            attendu = pgcd(a, b)
            if annonce != attendu:
                _ajoute_anomalie(
                    anomalies,
                    "pgcd",
                    m.group(0),
                    f"PGCD({a} ; {b}) = {attendu}, et non {annonce}.",
                )

    # -------------------------------------------------------------------
    # Nombres premiers entre eux
    # -------------------------------------------------------------------

    for m in re.finditer(r"\b(\d+)\s+et\s+(\d+)\s+ne\s+sont\s+pas\s+premiers?\s+entre\s+eux\b", texte):
        a, b = map(int, m.groups())
        if sont_premiers_entre_eux(a, b):
            _ajoute_anomalie(
                anomalies,
                "premiers_entre_eux_negative",
                m.group(0),
                f"{a} et {b} sont premiers entre eux car PGCD({a} ; {b}) = 1.",
            )

    for m in re.finditer(r"\b(\d+)\s+et\s+(\d+)\s+sont\s+premiers?\s+entre\s+eux\b", texte):
        a, b = map(int, m.groups())
        g = pgcd(a, b)
        if g != 1:
            _ajoute_anomalie(
                anomalies,
                "premiers_entre_eux",
                m.group(0),
                f"{a} et {b} ne sont pas premiers entre eux car PGCD({a} ; {b}) = {g}.",
            )

    # -------------------------------------------------------------------
    # Listes de diviseurs
    # -------------------------------------------------------------------

    pattern_liste = re.compile(
        r"\b(?:les\s+)?diviseurs\s+de\s+(\d+)\s*(?:sont|:|=)\s*"
        r"(\{[^}]+\}|\[[^\]]+\]|\([^)]*\)|[0-9\s,;et]+)(?=[\.\n]|$)"
    )

    for m in pattern_liste.finditer(texte):
        if _contexte_non_exhaustif(texte, m.start()):
            continue
        n = int(m.group(1))
        if n <= 0 or n > MAX_N_DIVISEURS:
            continue
        annonce = sorted(set(_entiers(m.group(2))))
        if not annonce:
            continue
        attendu = diviseurs(n)
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "liste_diviseurs",
                m.group(0),
                f"Les diviseurs de {n} sont {_format_liste(attendu)}.",
            )

    # -------------------------------------------------------------------
    # Listes de diviseurs communs
    # -------------------------------------------------------------------

    pattern_communs = re.compile(
        r"\b(?:les\s+)?diviseurs\s+communs\s+(?:a|de)\s+(\d+)\s*(?:et|,|;)\s*(\d+)\s*"
        r"(?:sont|:|=)\s*(\{[^}]+\}|\[[^\]]+\]|\([^)]*\)|[0-9\s,;et]+)(?=[\.\n]|$)"
    )

    for m in pattern_communs.finditer(texte):
        if _contexte_non_exhaustif(texte, m.start()):
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 0 or b <= 0 or max(a, b) > MAX_N_DIVISEURS:
            continue
        annonce = sorted(set(_entiers(m.group(3))))
        if not annonce:
            continue
        attendu = diviseurs_communs(a, b)
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "liste_diviseurs_communs",
                m.group(0),
                f"Les diviseurs communs à {a} et {b} sont {_format_liste(attendu)}.",
            )

    # -------------------------------------------------------------------
    # Couples de diviseurs : "{4 ; 8} est un couple de diviseurs de 32"
    # -------------------------------------------------------------------

    for m in re.finditer(
        r"[\{\(]\s*(\d+)\s*[;,]\s*(\d+)\s*[\}\)]\s*"
        r"(?:est\s+)?(?:un\s+)?couple\s+de\s+diviseurs\s+de\s+(\d+)\b",
        texte,
    ):
        b, c, a = map(int, m.groups())
        if not couple_de_diviseurs(b, c, a):
            _ajoute_anomalie(
                anomalies,
                "couple_diviseurs",
                m.group(0),
                f"{{{b} ; {c}}} n'est pas un couple de diviseurs de {a}, car {b} × {c} = {b * c}.",
            )

    # -------------------------------------------------------------------
    # Calculs simples présents dans le cours : multiplication, division,
    # addition, soustraction et encadrements par carrés.
    # -------------------------------------------------------------------

    # Multiplications du type "120 = 6 × 20"
    for m in re.finditer(r"\b(\d+)\s*=\s*(\d+)\s*(?:×|x|\*)\s*(\d+)\b", texte):
        annonce, b, c = map(int, m.groups())
        attendu = b * c
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "multiplication",
                m.group(0),
                f"{b} × {c} = {attendu}, et non {annonce}.",
            )

    # Multiplications du type "6 × 20 = 120"
    for m in re.finditer(r"\b(\d+)\s*(?:×|x|\*)\s*(\d+)\s*=\s*(\d+)\b", texte):
        b, c, annonce = map(int, m.groups())
        attendu = b * c
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "multiplication",
                m.group(0),
                f"{b} × {c} = {attendu}, et non {annonce}.",
            )

    # Divisions du type "32 ÷ 4 = 8" ou "32 / 4 = 8".
    for m in re.finditer(r"\b(\d+)\s*(?:÷|/|:)\s*(\d+)\s*=\s*(-?\d+)\b", texte):
        a, b, annonce = map(int, m.groups())
        if b == 0:
            _ajoute_anomalie(
                anomalies,
                "division",
                m.group(0),
                "La division par 0 est impossible.",
            )
            continue
        if a % b != 0 or a // b != annonce:
            attendu = f"{a} ÷ {b} = {a / b}" if a % b != 0 else f"{a} ÷ {b} = {a // b}"
            _ajoute_anomalie(anomalies, "division", m.group(0), attendu)

    # Additions simples.
    for m in re.finditer(r"\b(\d+)\s*\+\s*(\d+)\s*=\s*(\d+)\b", texte):
        a, b, annonce = map(int, m.groups())
        attendu = a + b
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "addition",
                m.group(0),
                f"{a} + {b} = {attendu}, et non {annonce}.",
            )

    # Soustractions simples.
    for m in re.finditer(r"\b(\d+)\s*-\s*(\d+)\s*=\s*(-?\d+)\b", texte):
        a, b, annonce = map(int, m.groups())
        attendu = a - b
        if annonce != attendu:
            _ajoute_anomalie(
                anomalies,
                "soustraction",
                m.group(0),
                f"{a} - {b} = {attendu}, et non {annonce}.",
            )

    # Encadrements numériques : "25 < 32 < 36".
    for m in re.finditer(r"\b(\d+)\s*(<|<=|≤)\s*(\d+)\s*(<|<=|≤)\s*(\d+)\b", texte):
        a, op1, b, op2, c = m.groups()
        a_i, b_i, c_i = int(a), int(b), int(c)
        if not (_relation_ok(a_i, op1, b_i) and _relation_ok(b_i, op2, c_i)):
            _ajoute_anomalie(
                anomalies,
                "encadrement",
                m.group(0),
                f"L'encadrement est faux : il faut vérifier séparément {a_i} {op1} {b_i} et {b_i} {op2} {c_i}.",
            )

    # Encadrements avec carrés : "5² < 32 < 6²" ou "5^2 < 32 < 6^2".
    for m in re.finditer(r"\b(\d+)\s*(?:²|\^2)\s*(<|<=|≤)\s*(\d+)\s*(<|<=|≤)\s*(\d+)\s*(?:²|\^2)\b", texte):
        n1, op1, a, op2, n2 = m.groups()
        gauche = int(n1) ** 2
        milieu = int(a)
        droite = int(n2) ** 2
        if not (_relation_ok(gauche, op1, milieu) and _relation_ok(milieu, op2, droite)):
            _ajoute_anomalie(
                anomalies,
                "encadrement_carres",
                m.group(0),
                f"L'encadrement est faux : {int(n1)}² = {gauche} et {int(n2)}² = {droite}.",
            )

    # Méthode du carré : "pour les diviseurs de 32, on teste de 1 à 5".
    pattern_methode_carre = re.compile(
        r"diviseurs\s+de\s+(\d+).{0,80}?test(?:e|er|es|ons)?\s+"
        r"(?:les\s+nombres\s+)?(?:de\s+)?1\s+(?:a|à|-)\s+(\d+)",
        flags=re.DOTALL,
    )
    for m in pattern_methode_carre.finditer(texte):
        a, borne_annoncee = map(int, m.groups())
        if a < 0 or a > MAX_N_DIVISEURS:
            continue
        attendu = borne_racine_pour_tests(a)
        if borne_annoncee != attendu:
            _ajoute_anomalie(
                anomalies,
                "methode_carre",
                m.group(0),
                f"Pour {a}, on teste les nombres de 1 à {attendu}, car floor(sqrt({a})) = {attendu}.",
            )

    return anomalies


# ---------------------------------------------------------------------------
# 4. Interface obligatoire du pipeline
# ---------------------------------------------------------------------------


def controle_calcul(reponse: str) -> tuple[bool, str]:
    """
    Retourne (calcul_ok, message_critique).
    - calcul_ok=True  → aucune erreur détectée, on passe au juge LLM.
    - calcul_ok=False → erreur détectée, message_critique décrit le problème.
    """
    anomalies = verifie_reponse(reponse)

    if not anomalies:
        return True, "Aucune erreur de calcul détectée."

    lignes = ["Erreur(s) de calcul détectée(s) :"]
    for i, anomalie in enumerate(anomalies, start=1):
        lignes.append(
            f"{i}. Type : {anomalie['type']} | "
            f"Affirmation : « {anomalie['affirmation']} » | "
            f"Attendu : {anomalie['attendu']}"
        )

    return False, "\n".join(lignes)


# ---------------------------------------------------------------------------
# 5. Exemples de validation manuelle
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    exemples = [
        (
            "6 est un diviseur de 120 car 120 = 6 × 20. PGCD(12 ; 18) = 6.",
            True,
        ),
        (
            "6 est un diviseur de 121.",
            False,
        ),
        (
            "120 est divisible par 7.",
            False,
        ),
        (
            "PGCD(15 ; 25) = 10.",
            False,
        ),
        (
            "14 et 25 sont premiers entre eux.",
            True,
        ),
        (
            "12 et 18 sont premiers entre eux.",
            False,
        ),
        (
            "Les diviseurs de 32 sont : {1, 2, 4, 8, 16, 32}.",
            True,
        ),
        (
            "Les diviseurs communs à 12 et 18 sont {1, 2, 4, 6}.",
            False,
        ),
    ]

    for numero, (texte_test, attendu_ok) in enumerate(exemples, start=1):
        ok, message = controle_calcul(texte_test)
        statut = "OK" if ok == attendu_ok else "ÉCHEC"
        print(f"[{statut}] Test {numero} - calcul_ok={ok} - attendu={attendu_ok}")
        if not ok:
            print(message)
        print("-" * 80)
