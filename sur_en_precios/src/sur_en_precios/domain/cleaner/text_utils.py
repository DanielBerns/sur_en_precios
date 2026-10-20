"""Text normalization and string utilities for retail data cleaning."""

from __future__ import annotations

import re
import unicodedata
from typing import List


def normalize_nfc(text: str | None) -> str:
    """Normalize text to Unicode NFC form.

    This ensures decomposed characters (like 'n' + combining tilde) become 'ñ',
    fixing encoding discrepancies between different supermarket feeds.
    """
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip()


def strip_accents(text: str | None) -> str:
    """Remove diacritical marks (accents, tildes) for robust search and pattern matching."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return stripped


def clean_whitespace(text: str | None) -> str:
    """Collapse multiple whitespace characters into a single space and strip edges."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str | None) -> str:
    """Convert a name into a lowercase, hyphenated slug."""
    if not text:
        return ""
    clean = strip_accents(text).lower()
    clean = re.sub(r"[^a-z0-9]+", "-", clean)
    return clean.strip("-")


def title_case_spanish(text: str | None) -> str:
    """Format product names and brands into clean Spanish title casing.

    Keeps short prepositions and conjunctions in lowercase (de, la, con, en, sin, etc.).
    """
    if not text:
        return ""
    lowercase_words = {
        "de",
        "del",
        "la",
        "las",
        "el",
        "los",
        "en",
        "con",
        "sin",
        "por",
        "para",
        "y",
        "o",
        "u",
        "e",
        "a",
        "al",
        "d'",
    }
    words = clean_whitespace(text).split()
    capitalized: List[str] = []
    for i, w in enumerate(words):
        w_lower = w.lower()
        if i == 0 or w_lower not in lowercase_words:
            capitalized.append(w.capitalize())
        else:
            capitalized.append(w_lower)
    return " ".join(capitalized)
