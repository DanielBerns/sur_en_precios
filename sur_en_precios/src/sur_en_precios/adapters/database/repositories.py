"""SQLAlchemy 2.0 repository implementations for catalog, prices, and users."""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased, joinedload, noload, selectinload

from sur_en_precios.domain.cleaner.text_utils import (
    slugify,
    strip_accents,
)
from sur_en_precios.domain.models import ArticlePriceStats, StorePriceDetail
from sur_en_precios.domain.models_public import (
    Article,
    Brand,
    Category,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    Tag,
)
from sur_en_precios.domain.models_user import (
    Basket,
    BasketItem,
    User,
)
from sur_en_precios.domain.ports import (
    CatalogRepositoryPort,
    PriceRepositoryPort,
    UserRepositoryPort,
)
from sur_en_precios.domain.services import (
    PriceMetricsCalculator,
    fuzzy_similarity_ratio,
)

logger = logging.getLogger("sur_en_precios.repositories")

CHUNK_SIZE = 500

_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "la",
        "las",
        "lo",
        "los",
        "o",
        "para",
        "por",
        "sin",
        "u",
        "un",
        "una",
        "unas",
        "unos",
        "x",
        "y",
    }
)


def _sql_unaccent_lower(col: Any) -> Any:
    """SQLite expression normalizing Spanish accented characters and ñ to lowercase ASCII."""
    expr: Any = func.lower(func.coalesce(col, ""))
    for src, dst in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("Á", "a"),
        ("É", "e"),
        ("Í", "i"),
        ("Ó", "o"),
        ("Ú", "u"),
        ("ü", "u"),
        ("Ü", "u"),
        ("ñ", "n"),
        ("Ñ", "n"),
    ):
        expr = func.replace(expr, src, dst)
    return expr


def _fast_fuzzy_ratio(q_norm: str, target_norm: str, min_ratio: float = 0.0) -> float:
    """Computes fuzzy_similarity_ratio with an O(1) length-ratio upper-bound short-circuit."""
    if not q_norm or not target_norm:
        return 0.0
    if q_norm == target_norm:
        return 1.0
    if q_norm in target_norm:
        return max(0.7, len(q_norm) / len(target_norm))
    max_len = max(len(q_norm), len(target_norm))
    min_len = min(len(q_norm), len(target_norm))
    if min_ratio > 0.0 and (min_len / max_len) < min_ratio:
        return 0.0
    return fuzzy_similarity_ratio(q_norm, target_norm)


def _get_brand_str(item: Any) -> Optional[str]:
    b = getattr(item, "brand_name", None) or getattr(item, "brand", None)
    if b is not None and hasattr(b, "brand"):
        return str(b.brand)
    if b is not None and hasattr(b, "name"):
        return str(b.name)
    return str(b) if b is not None else None


def _get_category_str(item: Any) -> Optional[str]:
    c = getattr(item, "category", None)
    if c is not None and hasattr(c, "content"):
        return str(c.content)
    if c is not None and hasattr(c, "name"):
        return str(c.name)
    if c is not None and hasattr(c, "category"):
        return str(c.category)
    return str(c) if c is not None else None


def _get_description_str(item: Any) -> str:
    if hasattr(item, "clean_description") and item.clean_description:
        return str(item.clean_description)
    d = getattr(item, "description", None)
    if d is not None and hasattr(d, "content"):
        return str(d.content)
    if d is not None and hasattr(d, "description"):
        return str(d.description)
    if hasattr(item, "name") and item.name:
        return str(item.name)
    return str(d) if d is not None else ""


def _get_ean_str(item: Any) -> str:
    if hasattr(item, "ean") and item.ean:
        return str(item.ean)
    an = getattr(item, "article_number", None)
    if an is not None and hasattr(an, "ean"):
        return str(an.ean)
    c = getattr(item, "code", None)
    if c is not None and hasattr(c, "ean"):
        return str(c.ean)
    return str(item) if item is not None else ""


def _get_store_code(s: Any) -> str:
    if hasattr(s, "code") and s.code:
        return str(s.code)
    if hasattr(s, "id") and s.id:
        return str(s.id)
    return str(s)


def _get_chain_name(s: Any) -> str:
    if hasattr(s, "brand_name") and s.brand_name:
        return str(s.brand_name)
    if hasattr(s, "chain_name") and s.chain_name:
        return str(s.chain_name)
    if hasattr(s, "flag") and s.flag:
        return str(s.flag.flag if hasattr(s.flag, "flag") else s.flag)
    return ""


def _get_store_name(s: Any) -> str:
    if hasattr(s, "branch_name") and s.branch_name:
        return str(s.branch_name)
    if hasattr(s, "store_name") and s.store_name:
        return str(s.store_name)
    if hasattr(s, "branch") and s.branch:
        return str(s.branch.branch if hasattr(s.branch, "branch") else s.branch)
    return ""


def _get_city_name(s: Any) -> str:
    if hasattr(s, "city") and s.city:
        c = s.city
        if hasattr(c, "name"):
            return str(c.name)
        return str(c)
    if hasattr(s, "place") and s.place and hasattr(s.place, "city") and s.place.city:
        city_obj = s.place.city
        return str(getattr(city_obj, "name", city_obj))
    return "General"


class SqlAlchemyCatalogRepository(CatalogRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for article and store catalog."""

    def __init__(self, session: Session):
        self._session = session

    def save_articles(self, articles: List[Any], batch_size: int = 10_000) -> None:
        if not articles:
            return

        # 1. Ensure Brands exist and resolve brand_map
        brand_names = {
            b.strip() for a in articles if (b := _get_brand_str(a)) and b.strip()
        }
        brand_map: Dict[str, Optional[int]] = {}
        if brand_names:
            existing_brands = self._session.execute(select(Brand)).scalars().all()
            name_to_brand: Dict[str, Brand] = {b.name: b for b in existing_brands}
            slug_to_brand: Dict[str, Brand] = {b.slug: b for b in existing_brands}

            for b_name in sorted(brand_names):
                if b_name in name_to_brand:
                    continue
                b_slug = slugify(b_name)
                if not b_slug:
                    continue
                if b_slug in slug_to_brand:
                    name_to_brand[b_name] = slug_to_brand[b_slug]
                    continue

                # Brand is genuinely new
                nb = Brand(name=b_name, slug=b_slug)
                self._session.add(nb)
                name_to_brand[b_name] = nb
                slug_to_brand[b_slug] = nb

            self._session.flush()

            for b_name in brand_names:
                brand_obj = name_to_brand.get(b_name)
                if not brand_obj:
                    b_slug = slugify(b_name)
                    brand_obj = slug_to_brand.get(b_slug)
                if brand_obj and brand_obj.id:
                    brand_map[b_name] = brand_obj.id

        # 2. Upsert Articles
        rows = []
        for a in articles:
            ean = _get_ean_str(a)
            if not ean:
                continue
            desc = _get_description_str(a)
            name = getattr(a, "name", None) or desc
            brand_name = _get_brand_str(a)
            b_id = (
                brand_map.get(brand_name)
                if brand_name
                else getattr(a, "brand_id", None)
            )
            pkg = getattr(a, "package", None)
            pkg_amt = getattr(a, "package_amount", None)
            pkg_unit = getattr(a, "package_unit", None)
            cat_id = getattr(a, "category_id", None)

            rows.append(
                {
                    "ean": ean,
                    "name": name,
                    "clean_description": desc,
                    "raw_description": getattr(a, "raw_description", desc),
                    "brand_id": b_id,
                    "brand_name": brand_name,
                    "package": pkg,
                    "package_amount": pkg_amt,
                    "package_unit": pkg_unit,
                    "category_id": cat_id,
                    "is_reviewed": True
                    if getattr(a, "is_reviewed", None) is None
                    else bool(getattr(a, "is_reviewed")),
                }
            )

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i : i + CHUNK_SIZE]
            stmt = sqlite_insert(Article).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ean"],
                set_={
                    "name": stmt.excluded.name,
                    "clean_description": stmt.excluded.clean_description,
                    "brand_name": stmt.excluded.brand_name,
                    "brand_id": stmt.excluded.brand_id,
                    "package": stmt.excluded.package,
                    "package_amount": stmt.excluded.package_amount,
                    "package_unit": stmt.excluded.package_unit,
                    "category_id": stmt.excluded.category_id,
                },
            )
            self._session.execute(stmt)

        self._session.commit()

    def save_stores(self, stores: List[Any], batch_size: int = 10_000) -> None:
        if not stores:
            return

        rows = []
        for s in stores:
            code = _get_store_code(s)
            if not code:
                continue

            place_ref = getattr(s, "place", None)
            addr = (
                getattr(place_ref, "address", None)
                if place_ref
                else getattr(s, "address", None)
            )
            lat = (
                getattr(place_ref, "latitude", None)
                if place_ref
                else getattr(s, "latitude", None)
            )
            lon = (
                getattr(place_ref, "longitude", None)
                if place_ref
                else getattr(s, "longitude", None)
            )

            rows.append(
                {
                    "code": code,
                    "sepa_id": getattr(s, "sepa_id", None),
                    "comercio_id": getattr(s, "comercio_id", None),
                    "bandera_id": getattr(s, "bandera_id", None),
                    "sucursal_id": getattr(s, "sucursal_id", None),
                    "business_name": getattr(s, "business_name", None)
                    or _get_chain_name(s),
                    "holding_group": getattr(s, "holding_group", None),
                    "brand_name": _get_chain_name(s),
                    "store_format": getattr(s, "store_format", None),
                    "branch_name": _get_store_name(s),
                    "address": str(addr) if addr is not None else None,
                    "city": _get_city_name(s),
                    "province": getattr(s, "province", "Chubut"),
                    "province_code": getattr(s, "province_code", "AR-U"),
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lon) if lon is not None else None,
                }
            )

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i : i + CHUNK_SIZE]
            stmt = (
                sqlite_insert(PointOfSale)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            self._session.execute(stmt)

        self._session.commit()

    def delete_stores_without_prices(self) -> int:
        """Removes PointOfSale rows that have no active DailyPrice observations."""
        active_codes_subq = select(DailyPrice.store_code).distinct()
        stmt = delete(PointOfSale).where(~PointOfSale.code.in_(active_codes_subq))
        res = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(res, "rowcount", 0) or 0)

    def search_articles_paginated(
        self,
        query: str,
        page: int = 1,
        per_page: int = 20,
        mode: str = "fuzzy",
    ) -> Tuple[List[Article], int]:
        try:
            q = (query or "").strip()
            if not q:
                return [], 0

            page = max(1, page)
            per_page = max(1, per_page)

            base_stmt = select(Article).options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )

            # 1. Exact / Direct EAN search if numeric
            if q.isdigit() and len(q) >= 6:
                ean_res = (
                    self._session.execute(base_stmt.where(Article.ean == q))
                    .scalars()
                    .unique()
                    .all()
                )
                if ean_res:
                    total = len(ean_res)
                    start = (page - 1) * per_page
                    return list(ean_res[start : start + per_page]), total

            q_lower = q.lower()
            q_norm = strip_accents(q_lower)

            if mode == "exact":
                norm_pattern = f"%{q_norm}%"
                filter_cond = (
                    (_sql_unaccent_lower(Article.name).like(norm_pattern))
                    | (
                        _sql_unaccent_lower(Article.clean_description).like(
                            norm_pattern
                        )
                    )
                    | (_sql_unaccent_lower(Article.brand_name).like(norm_pattern))
                    | (Article.ean == q)
                )
                count_stmt = select(func.count(Article.id)).where(filter_cond)
                total = self._session.execute(count_stmt).scalar() or 0

                offset = (page - 1) * per_page
                stmt = (
                    base_stmt.where(filter_cond)
                    .order_by(Article.name)
                    .offset(offset)
                    .limit(per_page)
                )
                items = list(self._session.execute(stmt).scalars().unique().all())
                return items, total

            # Fuzzy / Approximate Token Matching using lightweight candidate tuples
            # Tuple layout: (id, ean, name, clean_description, brand_name, category_name)
            candidates_map: Dict[str, Tuple[int, str, str, str, str, str]] = {}

            cand_base = select(
                Article.id,
                Article.ean,
                Article.name,
                Article.clean_description,
                Article.brand_name,
                Category.name,
            ).outerjoin(Category, Article.category_id == Category.id)

            def _collect_candidates(
                where_cond: Any, limit_rows: Optional[int] = None
            ) -> None:
                c_stmt = cand_base.where(where_cond)
                if limit_rows is not None:
                    c_stmt = c_stmt.limit(limit_rows)
                for row in self._session.execute(c_stmt).all():
                    candidates_map[row[1]] = (
                        row[0],
                        row[1],
                        row[2] or "",
                        row[3] or "",
                        row[4] or "",
                        row[5] or "",
                    )

            # Exact EAN check
            _collect_candidates(Article.ean == q)

            searchable_col = _sql_unaccent_lower(
                func.coalesce(Article.name, "")
                + " "
                + func.coalesce(Article.clean_description, "")
                + " "
                + func.coalesce(Article.brand_name, "")
            )

            raw_tokens = [t.lower() for t in q.split() if t]
            norm_tokens = [strip_accents(t) for t in raw_tokens if strip_accents(t)]
            significant_tokens = [
                t for t in norm_tokens if t not in _SEARCH_STOPWORDS and len(t) >= 3
            ]

            if len(significant_tokens) > 1:
                # Prefer articles containing all significant tokens first
                _collect_candidates(
                    and_(
                        *[searchable_col.like(f"%{tok}%") for tok in significant_tokens]
                    ),
                    limit_rows=3000,
                )
                if len(candidates_map) < 50:
                    _collect_candidates(
                        or_(
                            *[
                                searchable_col.like(f"%{tok}%")
                                for tok in significant_tokens
                            ]
                        ),
                        limit_rows=1500,
                    )
            elif len(significant_tokens) == 1:
                _collect_candidates(
                    searchable_col.like(f"%{significant_tokens[0]}%"),
                    limit_rows=3000,
                )
            elif q_norm:
                # Query consists solely of short tokens / stopwords (e.g. "te", "3d", "la")
                _collect_candidates(
                    or_(
                        searchable_col.like(f"{q_norm}%"),
                        searchable_col.like(f"% {q_norm}%"),
                        _sql_unaccent_lower(Article.brand_name).like(f"%{q_norm}%"),
                    ),
                    limit_rows=1000,
                )

            eval_tokens = significant_tokens if significant_tokens else norm_tokens

            # Fallback if few candidates: check brands with accent-normalized similarity
            if len(candidates_map) < 50 and eval_tokens:
                all_brand_names = (
                    self._session.execute(select(Brand.name)).scalars().all()
                )
                matched_brand_names: List[str] = []
                for b_name in all_brand_names:
                    b_norm = strip_accents(b_name).lower()
                    if not b_norm:
                        continue
                    if _fast_fuzzy_ratio(q_norm, b_norm, 0.75) >= 0.75:
                        matched_brand_names.append(b_name)
                        continue
                    b_words = [w for w in b_norm.split() if len(w) >= 3]
                    if any(
                        _fast_fuzzy_ratio(tok, b_norm, 0.75) >= 0.75
                        or any(
                            _fast_fuzzy_ratio(tok, bw, 0.75) >= 0.75 for bw in b_words
                        )
                        for tok in eval_tokens
                    ):
                        matched_brand_names.append(b_name)

                if matched_brand_names:
                    _collect_candidates(
                        Article.brand_name.in_(matched_brand_names),
                        limit_rows=1500,
                    )

            # Bounded typo-stem SQL fallback (avoids full-table ORM scans on 50k+ catalogs)
            if len(candidates_map) < 50:
                stem_conds = []
                for tok in significant_tokens:
                    if len(tok) >= 4:
                        p3 = tok[:3]
                        s3 = tok[-3:]
                        stem_conds.extend(
                            [
                                searchable_col.like(f"{p3}%"),
                                searchable_col.like(f"% {p3}%"),
                                searchable_col.like(f"%{s3} %"),
                                searchable_col.like(f"%{s3}"),
                            ]
                        )
                if stem_conds:
                    _collect_candidates(or_(*stem_conds), limit_rows=1200)

                if len(candidates_map) < 20:
                    short_stem_conds = [
                        or_(
                            searchable_col.like(f"{tok[:2]}%"),
                            searchable_col.like(f"% {tok[:2]}%"),
                        )
                        for tok in significant_tokens
                        if 4 <= len(tok) <= 8
                    ]
                    if short_stem_conds:
                        _collect_candidates(or_(*short_stem_conds), limit_rows=800)

            # Precompile per-query regexes outside the scoring loop
            word_q_re = re.compile(r"\b" + re.escape(q_norm) + r"\b")
            deriv_q_re = re.compile(
                r"\b(de|con|sabor|a base de)\s+" + re.escape(q_norm) + r"\b"
            )
            deriv_prefix_re = re.compile(
                r"^(tostadas?|galletit?as?|alfajor(es)?|oblea|snack|fideos?|harina|cerveza|copos|cereal(es)?|barra|condimento)\b"
            )
            vinagre_prefix_re = re.compile(r"^(v\s+|vinagre\s+)")
            std_pkg_re = re.compile(r"\b(1\s*kg|500\s*g|1000\s*g)\b")
            dirty_unit_re = re.compile(r"\b(para\s+1\s*u)\b")

            # Rank candidates by relevance and similarity score
            scored: List[Tuple[float, str, int]] = []

            for (
                art_id,
                art_ean,
                art_name,
                art_clean_desc,
                art_brand,
                art_cat,
            ) in candidates_map.values():
                if art_ean == q:
                    scored.append((1000.0, art_name, art_id))
                    continue

                desc_str = (art_name or art_clean_desc).lower()
                desc_norm = strip_accents(desc_str)
                b_norm = strip_accents(art_brand.lower())
                cat_norm = strip_accents(art_cat.lower())

                # Exact match on name
                if desc_norm == q_norm:
                    scored.append((500.0, art_name, art_id))
                    continue

                score = 0.0

                # 1. Primary Product: Does the description start with the query?
                # e.g. "Arroz Gallo..." when searching "arroz"
                if desc_norm.startswith(q_norm + " "):
                    score += 100.0
                elif q_norm in desc_norm:
                    score += 40.0

                # Direct brand match boost (e.g. "la anonima", "bimbo", "la serenisima")
                if b_norm:
                    if b_norm == q_norm:
                        score += 45.0
                    elif len(q_norm) >= 3 and q_norm in b_norm:
                        score += 25.0

                # 2. Whole word match
                if word_q_re.search(desc_norm):
                    score += 20.0

                # 3. Category match
                if q_norm in cat_norm:
                    score += 15.0
                    if desc_norm.startswith(q_norm + " "):
                        score += 15.0

                # 4. Derivative penalty
                # When searching a staple (like "arroz"), items that are snacks, desserts,
                # or derivatives ("tostadas de arroz", "galletitas de arroz", "arroz con leche",
                # "vinagre de arroz") should be penalized so pure products rank first.
                if deriv_q_re.search(desc_norm):
                    score -= 50.0
                if "con leche" in desc_norm or "con salsa" in desc_norm:
                    score -= 50.0
                if deriv_prefix_re.match(desc_norm):
                    score -= 60.0
                if vinagre_prefix_re.match(desc_norm):
                    score -= 60.0

                # 5. Fuzzy token fallback / typo tolerance
                # Note: fuzzy_score * 30.0 <= 30.0, so only compute Levenshtein when score < 30.0
                if score < 30.0 and eval_tokens:
                    words = f"{desc_norm} {b_norm}".split()
                    words_set = set(words)
                    tok_scores = []
                    for tok in eval_tokens:
                        if tok in words_set:
                            tok_scores.append(1.0)
                            continue
                        best_tok = 0.0
                        for word in words:
                            sim = _fast_fuzzy_ratio(tok, word, max(0.45, best_tok))
                            if sim > best_tok:
                                best_tok = sim
                        tok_scores.append(best_tok)
                    avg_tok = sum(tok_scores) / len(tok_scores)
                    fuzzy_score = max(
                        _fast_fuzzy_ratio(q_norm, desc_norm, 0.55),
                        _fast_fuzzy_ratio(q_norm, b_norm, 0.55),
                        avg_tok,
                    )
                    if fuzzy_score >= 0.55:
                        score = max(score, fuzzy_score * 30.0)

                # 6. Brand and packaging quality boosts (only if the product matched the search query)
                if score > 0:
                    if b_norm:
                        score += 5.0
                    if std_pkg_re.search(desc_norm):
                        score += 5.0

                # Penalize dirty or truncated items (e.g. "arroz para 1 u")
                if dirty_unit_re.search(desc_norm):
                    score -= 40.0

                if score >= 3.5:
                    scored.append((score, art_name, art_id))

            scored.sort(key=lambda item: (-item[0], item[1]))
            total = len(scored)
            start = (page - 1) * per_page
            page_slice = scored[start : start + per_page]
            if not page_slice:
                return [], total

            page_ids = [art_id for _, _, art_id in page_slice]
            loaded_articles = (
                self._session.execute(base_stmt.where(Article.id.in_(page_ids)))
                .scalars()
                .unique()
                .all()
            )
            articles_by_id = {a.id: a for a in loaded_articles}
            return [
                articles_by_id[art_id]
                for _, _, art_id in page_slice
                if art_id in articles_by_id
            ], total
        except Exception as exc:
            logger.error(
                "Error executing search_articles_paginated (query=%r, mode=%s, page=%s): %s",
                query,
                mode,
                page,
                exc,
            )
            raise

    def search_articles(
        self, query: str, limit: Optional[int] = None, mode: str = "fuzzy"
    ) -> List[Article]:
        per_page = limit if limit is not None and limit > 0 else 1000000
        items, _ = self.search_articles_paginated(
            query=query, page=1, per_page=per_page, mode=mode
        )
        return items

    def get_article_by_ean(self, ean: str) -> Optional[Article]:
        stmt = (
            select(Article)
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
            .where(Article.ean == str(ean).strip())
        )
        return self._session.execute(stmt).scalars().unique().first()

    def get_stores_by_city(self, city: str) -> List[PointOfSale]:
        stmt = (
            select(PointOfSale)
            .where(func.lower(PointOfSale.city) == func.lower(city.strip()))
            .order_by(PointOfSale.brand_name, PointOfSale.branch_name)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_cities_for_region(self, region: str) -> List[str]:
        valid_city_filters = (
            PointOfSale.city.isnot(None),
            PointOfSale.city != "",
            or_(
                PointOfSale.province.is_(None),
                PointOfSale.city != PointOfSale.province,
            ),
        )
        reg_clean = (region or "").strip().upper()

        # 1. Prefer cities in the configured region that have stores with active prices
        if reg_clean and reg_clean != "ALL":
            stmt_with_prices = (
                select(PointOfSale.city)
                .join(DailyPrice, DailyPrice.store_code == PointOfSale.code)
                .where(
                    func.upper(PointOfSale.province_code) == reg_clean,
                    *valid_city_filters,
                )
                .distinct()
                .order_by(PointOfSale.city)
            )
            cities = [
                c for c in self._session.execute(stmt_with_prices).scalars().all() if c
            ]
            if cities:
                return cities

        # 2. Fallback to any cities with active DailyPrice observations in this catalog DB
        stmt_any_priced = (
            select(PointOfSale.city)
            .join(DailyPrice, DailyPrice.store_code == PointOfSale.code)
            .where(*valid_city_filters)
            .distinct()
            .order_by(PointOfSale.city)
        )
        cities = [
            c for c in self._session.execute(stmt_any_priced).scalars().all() if c
        ]
        if cities:
            return cities

        # 3. Fallback to unpriced points of sale in the configured region
        if reg_clean and reg_clean != "ALL":
            stmt_pos = (
                select(PointOfSale.city)
                .where(
                    func.upper(PointOfSale.province_code) == reg_clean,
                    *valid_city_filters,
                )
                .distinct()
                .order_by(PointOfSale.city)
            )
            cities = [c for c in self._session.execute(stmt_pos).scalars().all() if c]
            if cities:
                return cities

        # 4. Final fallback: all distinct cities in points_of_sale
        stmt_all = (
            select(PointOfSale.city)
            .where(*valid_city_filters)
            .distinct()
            .order_by(PointOfSale.city)
        )
        return [c for c in self._session.execute(stmt_all).scalars().all() if c]

    # Taxonomy navigation methods
    def get_departments(self) -> List[Category]:
        stmt = (
            select(Category)
            .where(Category.level == 1)
            .order_by(Category.name)
            .options(joinedload(Category.children), noload(Category.articles))
        )
        return list(self._session.execute(stmt).scalars().unique().all())

    def get_subcategories(self, department_slug: str) -> List[Category]:
        parent_cat = aliased(Category)
        stmt = (
            select(Category)
            .join(parent_cat, Category.parent_id == parent_cat.id)
            .where(parent_cat.slug == department_slug)
            .order_by(Category.name)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_articles_by_subcategory_paginated(
        self, subcategory_slug: str, page: int = 1, per_page: int = 50
    ) -> Tuple[List[Article], int]:
        page = max(1, page)
        per_page = max(1, per_page)
        filter_cond = Category.slug == subcategory_slug

        count_stmt = (
            select(func.count(Article.id))
            .join(Category, Article.category_id == Category.id)
            .where(filter_cond)
        )
        total = self._session.execute(count_stmt).scalar() or 0

        offset = (page - 1) * per_page
        stmt = (
            select(Article)
            .join(Category, Article.category_id == Category.id)
            .where(filter_cond)
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
            .order_by(Article.name)
            .offset(offset)
            .limit(per_page)
        )
        items = list(self._session.execute(stmt).scalars().unique().all())
        return items, total

    def get_articles_by_subcategory(
        self, subcategory_slug: str, limit: int = 50
    ) -> List[Article]:
        items, _ = self.get_articles_by_subcategory_paginated(
            subcategory_slug, page=1, per_page=limit
        )
        return items

    def get_articles_by_tag_paginated(
        self, tag_name: str, page: int = 1, per_page: int = 50
    ) -> Tuple[List[Article], int]:
        page = max(1, page)
        per_page = max(1, per_page)
        filter_cond = Tag.name == tag_name

        count_stmt = (
            select(func.count(Article.id)).join(Article.tags).where(filter_cond)
        )
        total = self._session.execute(count_stmt).scalar() or 0

        offset = (page - 1) * per_page
        stmt = (
            select(Article)
            .join(Article.tags)
            .where(filter_cond)
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
            .order_by(Article.name)
            .offset(offset)
            .limit(per_page)
        )
        items = list(self._session.execute(stmt).scalars().unique().all())
        return items, total

    def get_articles_by_tag(self, tag_name: str, limit: int = 50) -> List[Article]:
        items, _ = self.get_articles_by_tag_paginated(tag_name, page=1, per_page=limit)
        return items

    def get_candidate_substitutions(self, ean: str, limit: int = 5) -> List[Article]:
        current = self.get_article_by_ean(ean)
        if not current or not current.category_id:
            return []

        stmt = (
            select(Article)
            .where(
                Article.category_id == current.category_id,
                Article.ean != current.ean,
            )
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
        )
        if current.package_unit:
            stmt = stmt.where(Article.package_unit == current.package_unit)
        stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars().unique().all())


class SqlAlchemyPriceRepository(PriceRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for prices and metrics."""

    def __init__(self, session: Session):
        self._session = session

    def save_prices(self, prices: List[Any], batch_size: int = 10_000) -> None:
        if not prices:
            return

        rows = []
        for p in prices:
            raw_d = getattr(p, "date", None) or getattr(p, "price_date", None)
            if not raw_d and hasattr(p, "timestamp") and p.timestamp is not None:
                ts_val = getattr(p.timestamp, "value", p.timestamp)
                if isinstance(ts_val, datetime):
                    raw_d = ts_val.date()
                elif isinstance(ts_val, date):
                    raw_d = ts_val
            elif isinstance(raw_d, datetime):
                raw_d = raw_d.date()

            ean = _get_ean_str(p)
            st_ref = getattr(p, "store", None)
            store_code = (
                _get_store_code(st_ref)
                if st_ref is not None
                else (getattr(p, "store_code", None) or getattr(p, "store_id", None))
            )
            amt = getattr(p, "amount", None)
            if amt is None:
                amt = getattr(p, "price", 0)

            if raw_d and ean and store_code:
                rows.append(
                    {
                        "date": raw_d,
                        "ean": str(ean),
                        "store_code": str(store_code),
                        "price": int(amt) if amt is not None else 0,
                        "unit_price": getattr(p, "unit_price", None),
                    }
                )

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i : i + CHUNK_SIZE]
            stmt = sqlite_insert(DailyPrice).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "ean", "store_code"],
                set_={
                    "price": stmt.excluded.price,
                    "unit_price": stmt.excluded.unit_price,
                },
            )
            self._session.execute(stmt)

        self._session.commit()

    def save_metrics(self, metrics: List[Any], batch_size: int = 10_000) -> None:
        if not metrics:
            return

        rows = []
        for m in metrics:
            m_date_val = getattr(m, "date", None)
            if (
                m_date_val is None
                and hasattr(m, "timestamp")
                and m.timestamp is not None
            ):
                ts_inner = getattr(m.timestamp, "value", m.timestamp)
                if isinstance(ts_inner, datetime):
                    m_date_val = ts_inner.date()
                elif isinstance(ts_inner, date):
                    m_date_val = ts_inner
            elif isinstance(m_date_val, datetime):
                m_date_val = m_date_val.date()

            ean = _get_ean_str(m)
            city_name = getattr(m, "city_name", None) or (
                m.city.name
                if hasattr(m, "city") and hasattr(m.city, "name")
                else getattr(m, "city", "General")
            )

            ref_p = getattr(m, "reference_price", None)
            med_p = getattr(m, "median_price", None) or ref_p

            if m_date_val and ean and city_name:
                rows.append(
                    {
                        "date": m_date_val,
                        "ean": str(ean),
                        "city": str(city_name),
                        "min_price": getattr(m, "min_price", None),
                        "max_price": getattr(m, "max_price", None),
                        "median_price": int(med_p) if med_p is not None else None,
                        "geo_mean_price": getattr(m, "geo_mean_price", None),
                        "price_dispersion": getattr(m, "price_dispersion", None),
                        "pct_change_7d": getattr(m, "pct_change_7d", None),
                        "pct_change_30d": getattr(m, "pct_change_30d", None),
                        "pct_change_90d": getattr(m, "pct_change_90d", None),
                    }
                )

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i : i + CHUNK_SIZE]
            stmt = sqlite_insert(DailyProductMetric).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "ean", "city"],
                set_={
                    "min_price": stmt.excluded.min_price,
                    "max_price": stmt.excluded.max_price,
                    "median_price": stmt.excluded.median_price,
                    "geo_mean_price": stmt.excluded.geo_mean_price,
                    "price_dispersion": stmt.excluded.price_dispersion,
                },
            )
            self._session.execute(stmt)

        self._session.commit()

    def delete_prices_for_date(self, price_date: date) -> int:
        stmt = delete(DailyPrice).where(DailyPrice.date == price_date)
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_metrics_for_date(self, metric_date: date) -> int:
        stmt = delete(DailyProductMetric).where(DailyProductMetric.date == metric_date)
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_prices_before_date(self, cutoff_date: date) -> int:
        """Deletes prices older than cutoff_date for rolling window pruning."""
        stmt = delete(DailyPrice).where(DailyPrice.date < cutoff_date)
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_metrics_before_date(self, cutoff_date: date) -> int:
        """Deletes metrics older than cutoff_date for rolling window pruning."""
        stmt = delete(DailyProductMetric).where(DailyProductMetric.date < cutoff_date)
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def deduplicate_prices_keep_latest(self) -> int:
        """Retains only the latest price observation for each (ean, store_code), removing older duplicates."""
        count_before = (
            self._session.scalar(select(func.count()).select_from(DailyPrice)) or 0
        )
        self._session.execute(
            text(
                """
                DELETE FROM daily_prices
                WHERE rowid NOT IN (
                    SELECT rowid
                    FROM (
                        SELECT rowid, ROW_NUMBER() OVER (
                            PARTITION BY ean, store_code 
                            ORDER BY date DESC
                        ) as rn
                        FROM daily_prices
                    )
                    WHERE rn = 1
                )
                """
            )
        )
        self._session.commit()
        count_after = (
            self._session.scalar(select(func.count()).select_from(DailyPrice)) or 0
        )
        return max(0, count_before - count_after)

    def get_active_city_prices(self) -> Dict[Tuple[str, str], List[int]]:
        """Groups active prices in daily_prices by (ean, city) for reference metrics calculation."""
        stmt = select(DailyPrice.ean, PointOfSale.city, DailyPrice.price).join(
            PointOfSale, DailyPrice.store_code == PointOfSale.code
        )
        city_prices: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for ean, city, price in self._session.execute(stmt).all():
            city_prices[(ean, city or "General")].append(price)
        return city_prices

    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[DailyPrice]:
        results: List[DailyPrice] = []
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(DailyPrice)
                .join(PointOfSale, DailyPrice.store_code == PointOfSale.code)
                .join(Article, DailyPrice.ean == Article.ean)
                .options(
                    joinedload(DailyPrice.point_of_sale),
                    joinedload(DailyPrice.article),
                )
                .where(
                    func.lower(PointOfSale.city) == func.lower(city.strip()),
                    DailyPrice.date <= price_date,
                    DailyPrice.ean.in_(chunk_eans),
                )
                .order_by(DailyPrice.date.desc())
            )
            results.extend(self._session.execute(stmt).scalars().all())

        # Retain only the latest observed price per (ean, store_code)
        deduped: Dict[Tuple[str, str], DailyPrice] = {}
        for dp in results:
            key = (dp.ean, dp.store_code)
            if key not in deduped or dp.date > deduped[key].date:
                deduped[key] = dp
        return list(deduped.values())

    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]:
        ref_dict: Dict[str, int] = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(
                    DailyProductMetric.ean,
                    DailyProductMetric.median_price,
                    DailyProductMetric.date,
                )
                .where(
                    func.lower(DailyProductMetric.city) == func.lower(city.strip()),
                    DailyProductMetric.date <= price_date,
                    DailyProductMetric.ean.in_(chunk_eans),
                )
                .order_by(DailyProductMetric.date.desc())
            )
            for ean_val, med_p, _ in self._session.execute(stmt).all():
                if med_p is not None and ean_val not in ref_dict:
                    ref_dict[ean_val] = int(med_p)
        return ref_dict

    def get_latest_price_date(self) -> Optional[date]:
        stmt = select(func.max(DailyPrice.date))
        res = self._session.execute(stmt).scalar()
        if res:
            if isinstance(res, str):
                return date.fromisoformat(res)
            return res
        return None

    def get_article_price_stats(
        self, ean: str, city: Optional[str] = None, price_date: Optional[date] = None
    ) -> Optional[ArticlePriceStats]:
        clean_ean = str(ean).strip()
        article_stmt = (
            select(Article)
            .options(joinedload(Article.brand), joinedload(Article.category))
            .where(Article.ean == clean_ean)
        )
        article = self._session.execute(article_stmt).scalars().first()
        if not article:
            return None

        # Determine target date
        target_date = price_date
        if not target_date:
            target_date = self.get_latest_price_date()

        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        # Observed store prices on or before target_date (within 7-day window)
        price_stmt = (
            select(DailyPrice, PointOfSale)
            .join(PointOfSale, DailyPrice.store_code == PointOfSale.code)
            .where(DailyPrice.ean == clean_ean)
        )
        if target_date:
            price_stmt = price_stmt.where(DailyPrice.date <= target_date)
        if city:
            price_stmt = price_stmt.where(
                func.lower(PointOfSale.city) == func.lower(city.strip())
            )

        price_stmt = price_stmt.order_by(DailyPrice.date.desc(), DailyPrice.price.asc())
        price_rows = self._session.execute(price_stmt).all()

        # Deduplicate to latest observation per store
        store_map: Dict[str, Tuple[DailyPrice, PointOfSale]] = {}
        for dp, pos in price_rows:
            if pos.code not in store_map or dp.date > store_map[pos.code][0].date:
                store_map[pos.code] = (dp, pos)

        sorted_stores = sorted(store_map.values(), key=lambda x: x[0].price)
        store_details: List[StorePriceDetail] = []
        observed_prices: List[int] = []

        for dp, pos in sorted_stores:
            observed_prices.append(dp.price)
            store_details.append(
                StorePriceDetail(
                    chain_name=pos.chain_name or pos.brand_name or "Comercio",
                    branch_name=pos.branch_name or "",
                    city=pos.city or "",
                    price=dp.price,
                    unit_price=dp.unit_price,
                    unit=article.package_unit or None,
                    date=dp.date,
                )
            )

        # Precomputed metrics on or before target_date
        metric_stmt = select(DailyProductMetric).where(
            DailyProductMetric.ean == clean_ean
        )
        if target_date:
            metric_stmt = metric_stmt.where(DailyProductMetric.date <= target_date)
        if city:
            metric_stmt = metric_stmt.where(
                func.lower(DailyProductMetric.city) == func.lower(city.strip())
            )
        metric_stmt = metric_stmt.order_by(DailyProductMetric.date.desc())

        metrics = self._session.execute(metric_stmt).scalars().all()

        min_p: Optional[int] = None
        max_p: Optional[int] = None
        ref_p: Optional[int] = None
        dispersion: Optional[float] = None

        if metrics:
            valid_min = [m.min_price for m in metrics if m.min_price is not None]
            valid_max = [m.max_price for m in metrics if m.max_price is not None]
            valid_ref = [m.median_price for m in metrics if m.median_price is not None]
            valid_disp = [
                m.price_dispersion for m in metrics if m.price_dispersion is not None
            ]

            if valid_min:
                min_p = min(valid_min)
            if valid_max:
                max_p = max(valid_max)
            if valid_ref:
                ref_p = PriceMetricsCalculator.calculate_reference_price(valid_ref)
            if valid_disp:
                dispersion = round(sum(valid_disp) / len(valid_disp), 4)

        if observed_prices:
            if min_p is None or min_p > min(observed_prices):
                min_p = min(observed_prices)
            if max_p is None or max_p < max(observed_prices):
                max_p = max(observed_prices)
            if ref_p is None:
                ref_p = PriceMetricsCalculator.calculate_reference_price(
                    observed_prices
                )
            if dispersion is None and len(observed_prices) > 1:
                mean_val = sum(observed_prices) / len(observed_prices)
                if mean_val > 0:
                    import statistics

                    dispersion = round(statistics.stdev(observed_prices) / mean_val, 4)

        cheapest_store = (
            f"{store_details[0].chain_name} ({store_details[0].branch_name})".strip()
            if store_details
            else None
        )
        most_expensive_store = (
            f"{store_details[-1].chain_name} ({store_details[-1].branch_name})".strip()
            if store_details
            else None
        )

        resolved_city = city or (
            store_details[0].city
            if store_details
            else (metrics[0].city if metrics else None)
        )

        display_date = (
            max(dp.date for dp, _ in sorted_stores) if sorted_stores else target_date
        )

        return ArticlePriceStats(
            ean=article.ean,
            name=article.name,
            clean_description=article.clean_description,
            brand_name=article.brand_name,
            package=article.package,
            category_name=article.category.name if article.category else None,
            date=display_date,
            city=resolved_city,
            min_price=min_p,
            max_price=max_p,
            reference_price=ref_p,
            price_dispersion=dispersion,
            cheapest_store=cheapest_store,
            most_expensive_store=most_expensive_store,
            stores_count=len(store_details),
            store_prices=store_details,
        )


class SqlAlchemyUserRepository(UserRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for user accounts and baskets."""

    def __init__(self, session: Session):
        self._session = session

    def create_user(
        self,
        username: str = "",
        password_hash: str = "",
        is_admin: bool = False,
        email: Optional[str] = None,
    ) -> User:
        effective_username = (username or email or "").strip().lower()
        if not effective_username:
            raise ValueError("Username cannot be empty")

        if is_admin:
            existing_admins = self.count_admins()
            if existing_admins >= 1:
                raise ValueError(
                    "Solo se permite un único usuario administrador en el sistema."
                )

        try:
            user_entity = User(
                username=effective_username,
                password_hash=password_hash,
                is_admin=is_admin,
            )
            self._session.add(user_entity)
            self._session.commit()
            self._session.refresh(user_entity)
            return user_entity
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "Failed to create user with username %s: %s", effective_username, exc
            )
            raise

    def get_user_by_username(self, username: str) -> Optional[User]:
        try:
            clean_name = username.strip().lower()
            stmt = select(User).where(User.username == clean_name)
            return self._session.execute(stmt).scalar_one_or_none()
        except Exception as exc:
            logger.error("Failed to query user by username %s: %s", username, exc)
            raise

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self.get_user_by_username(email)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        try:
            stmt = select(User).where(User.id == user_id)
            return self._session.execute(stmt).scalar_one_or_none()
        except Exception as exc:
            logger.error("Failed to query user by id %s: %s", user_id, exc)
            raise

    def get_all_users(self) -> List[User]:
        try:
            stmt = (
                select(User).options(joinedload(User.baskets)).order_by(User.id.asc())
            )
            return list(self._session.execute(stmt).scalars().unique().all())
        except Exception as exc:
            logger.error("Failed to query all users: %s", exc)
            raise

    def delete_user(self, user_id: int) -> bool:
        try:
            stmt = select(User).where(User.id == user_id)
            user = self._session.execute(stmt).scalar_one_or_none()
            if not user:
                return False
            self._session.delete(user)
            self._session.commit()
            return True
        except Exception as exc:
            self._session.rollback()
            logger.error("Failed to delete user %s: %s", user_id, exc)
            raise

    def count_admins(self) -> int:
        try:
            stmt = select(func.count(User.id)).where(User.is_admin.is_(True))
            return int(self._session.execute(stmt).scalar() or 0)
        except Exception as exc:
            logger.error("Failed to count admin users: %s", exc)
            raise

    def save_basket(self, basket: Basket) -> Basket:
        try:
            basket_uuid = getattr(basket, "uuid", None) or str(uuid.uuid4())
            if isinstance(basket, Basket) and basket.id:
                basket_entity = basket
                basket_entity.uuid = basket_uuid
                basket_entity.is_public = bool(getattr(basket, "is_public", False))
            else:
                basket_entity = Basket(
                    id=getattr(basket, "id", None),
                    uuid=basket_uuid,
                    user_id=basket.user_id,
                    name=basket.name,
                    is_public=bool(getattr(basket, "is_public", False)),
                )
                if hasattr(basket, "items") and basket.items:
                    for item in basket.items:
                        basket_entity.items.append(
                            BasketItem(
                                ean=item.ean,
                                quantity=getattr(item, "quantity", 1) or 1,
                                selected=getattr(item, "selected", True) is not False,
                                numerator=getattr(item, "numerator", 1) or 1,
                                denominator=getattr(item, "denominator", 1) or 1,
                            )
                        )

            merged_entity = self._session.merge(basket_entity)
            self._session.commit()
            self._session.refresh(merged_entity)
            return merged_entity
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "Failed to save basket %s: %s",
                getattr(basket, "name", "unknown"),
                exc,
            )
            raise

    def get_user_baskets(self, user_id: int) -> List[Basket]:
        try:
            stmt = (
                select(Basket)
                .options(joinedload(Basket.items))
                .where(Basket.user_id == user_id)
                .order_by(Basket.id.desc())
            )
            results = self._session.execute(stmt).scalars().unique().all()
            return list(results)
        except Exception as exc:
            logger.error(
                "Failed to fetch baskets for user_id %s: %s",
                user_id,
                exc,
            )
            raise

    def get_all_baskets(self) -> List[Basket]:
        try:
            stmt = (
                select(Basket)
                .options(joinedload(Basket.items), joinedload(Basket.user))
                .order_by(Basket.id.desc())
            )
            results = self._session.execute(stmt).scalars().unique().all()
            return list(results)
        except Exception as exc:
            logger.error("Failed to fetch all baskets: %s", exc)
            raise

    def get_basket_by_uuid(self, uuid_str: str) -> Optional[Basket]:
        try:
            stmt = (
                select(Basket)
                .options(joinedload(Basket.items), joinedload(Basket.user))
                .where(Basket.uuid == uuid_str)
            )
            return self._session.execute(stmt).scalars().first()
        except Exception as exc:
            logger.error("Failed to fetch basket by uuid %s: %s", uuid_str, exc)
            raise

    def delete_basket(self, basket_id: int, user_id: int) -> bool:
        try:
            stmt = select(Basket).where(
                Basket.id == basket_id, Basket.user_id == user_id
            )
            b = self._session.execute(stmt).scalar_one_or_none()
            if not b:
                return False
            self._session.delete(b)
            self._session.commit()
            return True
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "Failed to delete basket %s for user %s: %s",
                basket_id,
                user_id,
                exc,
            )
            raise
