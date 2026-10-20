"""Product classification engine that maps cleaned article records to taxonomy categories and tags."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from sur_en_precios.domain.cleaner.article_cleaner import CleanedArticleData
from sur_en_precios.domain.cleaner.text_utils import normalize_nfc, strip_accents
from sur_en_precios.domain.taxonomy.rules import CLASSIFICATION_RULES, FACET_TAG_RULES


@dataclass
class ClassificationResult:
    department: str
    subcategory: str
    tags: List[str] = field(default_factory=list)


class TaxonomyClassifier:
    """Classifies products into retail Department and Subcategory, and attaches facet tags."""

    def __init__(self) -> None:
        self._compiled_category_rules: List[Tuple[str, str, re.Pattern]] = []
        for dept, sub, pats in CLASSIFICATION_RULES:
            pat_combined = "|".join(f"(?:{p})" for p in pats)
            self._compiled_category_rules.append(
                (dept, sub, re.compile(pat_combined, re.IGNORECASE))
            )

        self._compiled_facet_rules: List[Tuple[str, re.Pattern]] = []
        for tag_name, pats in FACET_TAG_RULES:
            pat_combined = "|".join(f"(?:{p})" for p in pats)
            self._compiled_facet_rules.append(
                (tag_name, re.compile(pat_combined, re.IGNORECASE))
            )

    def classify(self, article: CleanedArticleData) -> ClassificationResult:
        """Classify a cleaned article into Department and Subcategory and extract facet tags."""
        # Build search text from clean description, raw description, and existing tags
        components = [
            article.clean_description,
            article.raw_description,
            article.brand_name or "",
            " ".join(article.tags),
        ]
        raw_text = " ".join(components)
        text_normalized = strip_accents(normalize_nfc(raw_text)).lower()

        matched_dept: Optional[str] = None
        matched_sub: Optional[str] = None

        # 1. Match category rules
        for dept, sub, regex in self._compiled_category_rules:
            if regex.search(text_normalized):
                matched_dept = dept
                matched_sub = sub
                break

        # Fallback if unclassified
        if not matched_dept or not matched_sub:
            matched_dept = "Almacén"
            matched_sub = "Almacén General"

        # 2. Extract facet tags
        extracted_tags: Set[str] = set(article.tags)
        for tag_name, regex in self._compiled_facet_rules:
            if regex.search(text_normalized):
                extracted_tags.add(tag_name)

        return ClassificationResult(
            department=matched_dept,
            subcategory=matched_sub,
            tags=sorted(extracted_tags),
        )
