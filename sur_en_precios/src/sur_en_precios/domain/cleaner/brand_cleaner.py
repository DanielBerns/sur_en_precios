"""Brand cleaning, normalization, and brand lexicon for stripping."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

from sur_en_precios.domain.cleaner.text_utils import (
    clean_whitespace,
    normalize_nfc,
    strip_accents,
    title_case_spanish,
)


# Known generic/unbranded strings in retail databases
UNBRANDED_TERMS = {
    "sin marca",
    "sin marca ",
    "sinn marca",
    "sinmarca",
    "sin",
    "generico",
    "no informa",
    "s/m",
    "s/d",
}


def clean_brand_name(raw_brand: str | None) -> Optional[str]:
    """Clean and standardize a brand name. Returns None if unbranded or empty.

    Examples:
        'hawaian ' -> 'Hawaian'
        "kellogg's  " -> "Kellogg's"
        'sin marca' -> None
        'molino cañuelas ' -> 'Molino Cañuelas'
    """
    if not raw_brand:
        return None

    cleaned = normalize_nfc(raw_brand).strip(" \"'-,.")
    cleaned = clean_whitespace(cleaned)

    if not cleaned:
        return None

    if cleaned.lower() in UNBRANDED_TERMS:
        return None

    return title_case_spanish(cleaned)


class BrandLexicon:
    """Compiled collection of known brand names for fast stripping from raw descriptions."""

    def __init__(self, brands: Iterable[str] | None = None) -> None:
        self._brand_patterns: List[re.Pattern] = []
        if brands:
            self.load_brands(brands)

    def load_brands(self, brands: Iterable[str]) -> None:
        """Compile brand names into regex patterns sorted by descending length."""
        unique_tokens: Set[str] = set()

        for b in brands:
            clean = clean_brand_name(b)
            if not clean:
                continue
            name_lower = clean.lower()
            if len(name_lower) >= 3:
                unique_tokens.add(name_lower)
                # Also add unaccented variant
                stripped = strip_accents(name_lower)
                if stripped != name_lower:
                    unique_tokens.add(stripped)

        # Sort longest brand phrases first so compound brands match before sub-words
        sorted_tokens = sorted(unique_tokens, key=len, reverse=True)

        self._brand_patterns = [
            re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
            for token in sorted_tokens
        ]

    def strip_brands(self, text: str) -> str:
        """Strip known brand tokens from text."""
        result = text
        for pat in self._brand_patterns:
            result = pat.sub(" ", result)
        return clean_whitespace(result)
