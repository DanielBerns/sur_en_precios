"""Domain data normalizers and cleaners for SEPA datasets.

Provides pure, framework-free normalization for region codes, cities, brands,
product descriptions, and store metadata.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Set

# ISO 3166-2:AR: Argentine provinces and autonomous city
ARGENTINA_PROVINCES: Dict[str, str] = {
    "AR-A": "Salta",
    "AR-B": "Buenos Aires",
    "AR-C": "Ciudad Autónoma de Buenos Aires",
    "AR-D": "San Luis",
    "AR-E": "Entre Ríos",
    "AR-F": "La Rioja",
    "AR-G": "Santiago del Estero",
    "AR-H": "Chaco",
    "AR-J": "San Juan",
    "AR-K": "Catamarca",
    "AR-L": "La Pampa",
    "AR-M": "Mendoza",
    "AR-N": "Misiones",
    "AR-P": "Formosa",
    "AR-Q": "Neuquén",
    "AR-R": "Río Negro",
    "AR-S": "Santa Fe",
    "AR-T": "Tucumán",
    "AR-U": "Chubut",
    "AR-V": "Tierra del Fuego",
    "AR-W": "Corrientes",
    "AR-X": "Córdoba",
    "AR-Y": "Jujuy",
    "AR-Z": "Santa Cruz",
}

# Words that remain lowercase in Spanish title-casing (unless first word)
SPANISH_LOWERCASE_WORDS: Set[str] = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "los",
    "o",
    "para",
    "por",
    "sin",
    "y",
    "e",
    "u",
}

# Known abbreviations or acronyms to preserve in UPPERCASE
KNOWN_ACRONYMS: Set[str] = {
    "ypf",
    "3m",
    "lg",
    "bgh",
    "tcl",
    "tv",
    "led",
    "uht",
    "dha",
    "bpa",
    "ars",
    "usb",
    "hdmi",
    "pvc",
    "epa",
    "s.a.",
    "sa",
    "s.r.l.",
    "srl",
    "xl",
    "xxl",
    "xs",
    "bb",
    "bc",
}

# Regex to detect unit tokens, e.g. 500ml, 1kg, 250g, 1.5l, 100u
UNIT_TOKEN_REGEX = re.compile(
    r"^\d+(?:[.,]\d+)?(?:ml|cc|lt|l|g|gr|kg|cm|mm|m|mg|oz|u|un|pack)$",
    re.IGNORECASE,
)

# Known Argentine cities with accented canonical forms
CANONICAL_CITIES: Dict[str, str] = {
    "playa union": "Playa Unión",
    "bahia blanca": "Bahía Blanca",
    "rio cuarto": "Río Cuarto",
    "rio gallegos": "Río Gallegos",
    "rio grande": "Río Grande",
    "rio tercero": "Río Tercero",
    "parana": "Paraná",
    "neuquen": "Neuquén",
    "concepcion del uruguay": "Concepción del Uruguay",
    "gualeguaychu": "Gualeguaychú",
    "san martin": "San Martín",
    "general san martin": "General San Martín",
    "san nicolas": "San Nicolás",
    "chivilcoy": "Chivilcoy",
    "junin": "Junín",
    "moron": "Morón",
    "lanus": "Lanús",
    "quilmes": "Quilmes",
    "avellaneda": "Avellaneda",
    "cordoba": "Córdoba",
    "rosario": "Rosario",
    "santa fe": "Santa Fe",
    "salta": "Salta",
    "san miguel de tucuman": "San Miguel de Tucumán",
    "mar del plata": "Mar del Plata",
    "posadas": "Posadas",
    "corrientes": "Corrientes",
    "resistencia": "Resistencia",
    "comodoro rivadavia": "Comodoro Rivadavia",
    "puerto madryn": "Puerto Madryn",
    "trelew": "Trelew",
    "esquel": "Esquel",
    "rawson": "Rawson",
    "sarmiento": "Sarmiento",
    "gaiman": "Gaiman",
    "rada tilly": "Rada Tilly",
    "lago puelo": "Lago Puelo",
    "trevelin": "Trevelin",
}


def clean_whitespace(text: Optional[str]) -> str:
    """Replaces non-breaking spaces and collapses consecutive whitespace."""
    if not text:
        return ""
    # Replace non-breaking spaces (\xa0, \u200b, etc.)
    text = text.replace("\xa0", " ").replace("\u200b", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_accents(text: str) -> str:
    """Removes combining diacritical marks (e.g. 'Cañuelas' -> 'Canuelas')."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def to_spanish_title(text: str, preserve_acronyms: Optional[Set[str]] = None) -> str:
    """Converts text to Spanish Title Case, keeping prepositions lowercase."""
    cleaned = clean_whitespace(text)
    if not cleaned:
        return ""

    acronyms = KNOWN_ACRONYMS | (preserve_acronyms or set())

    # Split on words while preserving tokens
    words = cleaned.split(" ")
    result = []
    for i, word in enumerate(words):
        w_lower = word.lower()
        # Handle word with attached trailing/leading punctuation
        pure_word = word.strip(".,;:()[]{}-_/\"'")
        pure_lower = pure_word.lower()

        if pure_lower in acronyms:
            result.append(word.upper())
        elif UNIT_TOKEN_REGEX.match(word):
            result.append(w_lower)
        elif i > 0 and w_lower in SPANISH_LOWERCASE_WORDS:
            result.append(w_lower)
        else:
            # Capitalize first letter of word, lower remainder
            # Handle hyphenated parts (e.g., 'San-Martin' or 'Pre-Frito')
            if "-" in word and len(word) > 1:
                parts = [
                    p.capitalize()
                    if p.lower() not in SPANISH_LOWERCASE_WORDS
                    else p.lower()
                    for p in word.split("-")
                ]
                result.append("-".join(parts))
            elif "." in word and len(word) > 1 and not word.endswith("."):
                # Handle dotted words like 'ALF.TRIPLE' -> 'Alf.Triple'
                parts = [p.capitalize() for p in word.split(".")]
                result.append(".".join(parts))
            else:
                result.append(word.capitalize())

    return " ".join(result)


def decode_region_code(code: Optional[str]) -> str:
    """Decodes ISO 3166-2:AR code (e.g. 'AR-U') into its full province name.

    Falls back to the cleaned code if not recognized.
    """
    if not code:
        return "Buenos Aires"
    cleaned = clean_whitespace(code).upper()
    return ARGENTINA_PROVINCES.get(cleaned, cleaned)


def normalize_city(city: Optional[str]) -> str:
    """Normalizes city name to Title Case, fixes common accents and trims noise."""
    cleaned = clean_whitespace(city)
    if not cleaned or cleaned.upper() in {"GENERAL", "S/D", "SIN DATO", "DESCONOCIDO"}:
        return "General"

    # Check canonical dictionary first
    lookup_key = strip_accents(cleaned.lower())
    if lookup_key in CANONICAL_CITIES:
        return CANONICAL_CITIES[lookup_key]

    return to_spanish_title(cleaned)


def normalize_brand(brand: Optional[str]) -> str:
    """Sanitizes brand name, trims punctuation/whitespace, and applies clean casing."""
    cleaned = clean_whitespace(brand)
    if not cleaned or cleaned.upper() in {
        "SIN MARCA",
        "S/M",
        "GENERICO",
        "GENÉRICO",
        "NO INFORMA",
        "S/D",
        "-",
    }:
        return "Sin Marca"

    # Strip noise punctuation at ends (dots, colons, hyphens)
    cleaned = cleaned.strip(". ,;:-\"'/")

    lookup_lower = cleaned.lower()
    if lookup_lower in KNOWN_ACRONYMS:
        return cleaned.upper()

    return to_spanish_title(cleaned)


def strip_brand_from_description(description: str, brand: str) -> str:
    """Removes redundant mentions of the brand name from product description."""
    if not description or not brand:
        return description

    brand_clean = clean_whitespace(brand)
    if not brand_clean or brand_clean.upper() in {"SIN MARCA", "S/M"}:
        return description

    # Pattern for exact brand word boundaries
    pattern_exact = rf"\b{re.escape(brand_clean)}\b"
    stripped = re.sub(pattern_exact, "", description, flags=re.IGNORECASE)

    # Pattern for unaccented brand (e.g., 'Canuelas' vs 'Cañuelas')
    brand_no_acc = strip_accents(brand_clean)
    if brand_no_acc != brand_clean:
        pattern_no_acc = rf"\b{re.escape(brand_no_acc)}\b"
        stripped = re.sub(pattern_no_acc, "", stripped, flags=re.IGNORECASE)

    cleaned = clean_whitespace(stripped).strip(" -.,")
    return cleaned if len(cleaned) >= 2 else description


def normalize_description(
    description: Optional[str], brand: Optional[str] = None
) -> str:
    """Cleans whitespace, removes redundant embedded brand mentions, and normalizes casing."""
    cleaned = clean_whitespace(description)
    if not cleaned:
        return "Artículo sin descripción"

    if brand:
        cleaned = strip_brand_from_description(cleaned, brand)

    # Clean redundant punctuation left over
    cleaned = re.sub(r"\s+([.,;:])/s*", r"\1 ", cleaned)
    cleaned = clean_whitespace(cleaned).strip(" -.,")

    if not cleaned:
        # Fallback to original description if stripping removed everything
        cleaned = clean_whitespace(description)

    return to_spanish_title(cleaned)


def normalize_chain_name(chain: Optional[str]) -> str:
    """Normalizes supermarket chain/flag name."""
    cleaned = clean_whitespace(chain)
    if not cleaned or cleaned.upper() in {"SUPERMERCADO", "S/D"}:
        return "Supermercado"
    return to_spanish_title(cleaned)


def normalize_branch_name(branch: Optional[str]) -> str:
    """Normalizes branch name."""
    cleaned = clean_whitespace(branch)
    if not cleaned:
        return "Sucursal"
    return to_spanish_title(cleaned)
