"""Core article cleaner for processing and standardizing messy retail product records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from sur_en_precios.domain.cleaner.brand_cleaner import (
    BrandLexicon,
    clean_brand_name,
)
from sur_en_precios.domain.cleaner.package_parser import (
    PackageInfo,
    build_package_patterns,
    parse_package,
)
from sur_en_precios.domain.cleaner.text_utils import (
    clean_whitespace,
    normalize_nfc,
    strip_accents,
    title_case_spanish,
)


@dataclass
class CleanedArticleData:
    """Standardized and cleaned representation of an article."""
    ean: str
    name: str
    clean_description: str
    raw_description: str
    brand_name: Optional[str]
    package: Optional[str]
    package_amount: Optional[float]
    package_unit: Optional[str]
    tags: List[str] = field(default_factory=list)


# General package residue regex to remove stray unit patterns at ends of descriptions
RESIDUAL_PACKAGE_RE = re.compile(
    r"\b(?:\d+[\.,]\d+|\d+)\s*(?:cc|cm3|ml|lt|lts|l|gr|grs|g|kg|kgs|k|un|und|unid|u|mt|mts|m)\b",
    re.IGNORECASE,
)

# Common pack multiplier residue, e.g. "x 6", "6 un", "pack x 2"
PACK_RESIDUE_RE = re.compile(
    r"\b(?:pack\s*(?:x\s*)?\d+|\bx\s*\d+\s*(?:un|u)?)\b",
    re.IGNORECASE,
)


class ArticleCleaner:
    """Cleans article descriptions, handles brand and package separation, and generates clean data."""

    def __init__(self, brand_lexicon: Optional[BrandLexicon] = None) -> None:
        self.brand_lexicon = brand_lexicon or BrandLexicon()

    def clean_description_from_raw(
        self,
        raw_description: str,
        brand_name: Optional[str],
        pkg_info: PackageInfo,
    ) -> str:
        """Derive a clean generic description from a raw description when no clean tag exists."""
        text = normalize_nfc(raw_description).lower()

        # 1. Strip the specific package patterns for this article
        if pkg_info.amount is not None and pkg_info.unit:
            for pat in build_package_patterns(pkg_info.amount, pkg_info.unit):
                text = pat.sub(" ", text)

        # 2. Strip the article's own brand if known
        if brand_name:
            b_clean = normalize_nfc(brand_name).lower()
            b_esc = re.escape(b_clean)
            text = re.sub(rf"\b{b_esc}\b", " ", text, flags=re.IGNORECASE)

            # Also strip without accents (e.g. 'canuelas' for 'cañuelas')
            b_stripped = strip_accents(b_clean)
            if b_stripped != b_clean:
                text = re.sub(rf"\b{re.escape(b_stripped)}\b", " ", text, flags=re.IGNORECASE)

        # 3. Strip any supermarket private label or known brands from lexicon
        text = self.brand_lexicon.strip_brands(text)

        # 4. Strip residual package/unit measurements
        text = RESIDUAL_PACKAGE_RE.sub(" ", text)
        text = PACK_RESIDUE_RE.sub(" ", text)

        # 5. Clean punctuation and collapse whitespace
        text = re.sub(r"[^a-záéíóúñ0-9\s/]", " ", text)
        text = clean_whitespace(text).strip(" -_,./")

        return text or normalize_nfc(raw_description).strip().lower()

    def clean_tag(self, raw_tag: str, brand_name: Optional[str], pkg_info: PackageInfo) -> str:
        """Sanitize an existing tag, ensuring it does not retain brand or package fragments."""
        tag = normalize_nfc(raw_tag).strip().lower()

        # Strip brand if present in tag
        if brand_name:
            b_clean = normalize_nfc(brand_name).lower()
            tag = re.sub(rf"\b{re.escape(b_clean)}\b", " ", tag, flags=re.IGNORECASE)
            b_stripped = strip_accents(b_clean)
            if b_stripped != b_clean:
                tag = re.sub(rf"\b{re.escape(b_stripped)}\b", " ", tag, flags=re.IGNORECASE)

        # Strip package patterns
        if pkg_info.amount is not None and pkg_info.unit:
            for pat in build_package_patterns(pkg_info.amount, pkg_info.unit):
                tag = pat.sub(" ", tag)

        tag = RESIDUAL_PACKAGE_RE.sub(" ", tag)
        tag = clean_whitespace(tag).strip(" -_,./")
        return tag

    def process(
        self,
        ean: str,
        raw_description: str,
        raw_brand: Optional[str],
        raw_package: Optional[str],
        raw_tags: Optional[List[str]] = None,
    ) -> CleanedArticleData:
        """Process and clean all fields for a single article."""
        ean = str(ean).strip()
        raw_desc = normalize_nfc(raw_description).strip()
        brand_name = clean_brand_name(raw_brand)
        pkg_info = parse_package(raw_package)

        cleaned_tags: List[str] = []
        if raw_tags:
            for rt in raw_tags:
                ct = self.clean_tag(rt, brand_name, pkg_info)
                # Filter out truncated or garbage single/two letter tags
                if ct and len(ct) >= 3 and ct not in cleaned_tags:
                    cleaned_tags.append(ct)

        # Determine clean description
        if cleaned_tags:
            # Pick the most informative tag as primary clean description
            # If there are 2 tags, prefer the longer one if it's descriptive
            best_tag = max(cleaned_tags, key=len)
            clean_desc = best_tag
        else:
            # Derive clean description from raw description
            clean_desc = self.clean_description_from_raw(raw_desc, brand_name, pkg_info)

        # Build clean, human-friendly display name
        title_desc = title_case_spanish(clean_desc)
        title_brand = f" {brand_name}" if brand_name else ""
        title_pkg = f" {pkg_info.display}" if pkg_info.display else ""
        name = f"{title_desc}{title_brand}{title_pkg}".strip()

        return CleanedArticleData(
            ean=ean,
            name=name,
            clean_description=clean_desc,
            raw_description=raw_desc,
            brand_name=brand_name,
            package=pkg_info.display,
            package_amount=pkg_info.amount,
            package_unit=pkg_info.unit,
            tags=cleaned_tags,
        )
