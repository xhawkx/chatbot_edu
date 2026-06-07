import re


def nettoie_latex(txt: str) -> str:
    remplacements = {
        r"\\times": " × ", r"\\leq": " ≤ ", r"\\geq": " ≥ ", r"\\div": " ÷ ",
        r"\\Rightarrow": " ⇒ ", r"\\Leftarrow": " ⇐ ", r"\\neq": " ≠ ",
        r"\\pm": " ± ", r"\\cdot": " · ", r"\\quad": " ", r"\\qquad": " ",
        r"\\PGCD": "PGCD", r"\\PPCM": "PPCM",
    }
    for pat, rep in remplacements.items():
        txt = re.sub(pat, rep, txt)
    txt = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", txt)
    txt = re.sub(r"\\sqrt\{([^}]*)\}", r"√(\1)", txt)
    txt = re.sub(r"\\text\{([^}]*)\}", r"\1", txt)
    txt = re.sub(r"\\[a-zA-Z]+\*?\{([^}]*)\}", r"\1", txt)
    txt = re.sub(r"\\[a-zA-Z]+", " ", txt)
    txt = re.sub(r"[{}$^]", "", txt)
    return re.sub(r"[ \t]+", " ", txt).strip()
