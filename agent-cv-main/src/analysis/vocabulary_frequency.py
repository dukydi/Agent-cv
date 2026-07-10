"""Calcul déterministe de la fréquence des termes de vocabulaire de l'AO.

Le LLM d'Extract-Brief identifie les termes de vocabulaire à reprendre mais
ne doit jamais être chargé de compter leurs occurrences — le comptage est
fait ici, après coup, sur le texte source de l'AO.
"""
import re
import unicodedata

from src.schemas import Brief


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _count_occurrences(term: str, normalized_ao_text: str) -> int:
    term_norm = _normalize(term)
    if not term_norm:
        return 0
    pattern = r"\b" + re.escape(term_norm).replace(r"\ ", r"\s+") + r"\b"
    return len(re.findall(pattern, normalized_ao_text))


def compute_term_frequencies(brief: Brief, ao_text: str) -> Brief:
    """Retourne un `Brief` dont `vocabulaire[].frequence` a été recalculé par
    comptage littéral (insensible à la casse et aux accents, mots entiers)
    dans `ao_text`. Ne modifie rien d'autre. Retourne l'objet reçu tel quel
    si `vocabulaire` est vide."""
    if not brief.vocabulaire:
        return brief

    normalized_ao_text = _normalize(ao_text)
    updated_terms = [
        term.model_copy(update={"frequence": _count_occurrences(term.terme, normalized_ao_text)})
        for term in brief.vocabulaire
    ]
    return brief.model_copy(update={"vocabulaire": updated_terms})
