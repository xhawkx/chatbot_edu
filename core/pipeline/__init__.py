"""Pipeline 3 couches (Generator → Judge → Refine) avec court-circuit déterministe.

Ce sous-package est GÉNÉRIQUE (agnostique au cours). Le vérificateur arithmétique
spécifique au cours vit dans `cours/<slug>/verif.py`, chargé dynamiquement par
l'orchestrateur. Voir CLAUDE.md (contrainte d'agnosticité).
"""
