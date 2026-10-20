"""SQLAlchemy 2.0 repository implementations for catalog, prices, and users."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased, joinedload, selectinload




from sur_en_precios.domain.cleaner.text_utils import clean_whitespace, slugify, title_case_spanish
from sur_en_precios.domain.models_public import (
    Article,
    Brand,
    Category,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    Tag,
    article_tags,
)
from sur_en_precios.domain.models import ArticlePriceStats, StorePriceDetail
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
        brand_names = {b.strip() for a in articles if (b := _get_brand_str(a)) and b.strip()}
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
            b_name = _get_brand_str(a)
            b_id = brand_map.get(b_name) if b_name else getattr(a, "brand_id", None)
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
                    "brand_name": b_name,
                    "package": pkg,
                    "package_amount": pkg_amt,
                    "package_unit": pkg_unit,
                    "category_id": cat_id,
                    "is_reviewed": True if getattr(a, "is_reviewed", None) is None else bool(getattr(a, "is_reviewed")),
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
            addr = getattr(place_ref, "address", None) if place_ref else getattr(s, "address", None)
            lat = getattr(place_ref, "latitude", None) if place_ref else getattr(s, "latitude", None)
            lon = getattr(place_ref, "longitude", None) if place_ref else getattr(s, "longitude", None)

            rows.append(
                {
                    "code": code,
                    "sepa_id": getattr(s, "sepa_id", None),
                    "comercio_id": getattr(s, "comercio_id", None),
                    "bandera_id": getattr(s, "bandera_id", None),
                    "sucursal_id": getattr(s, "sucursal_id", None),
                    "business_name": getattr(s, "business_name", None) or _get_chain_name(s),
                    "holding_group": getattr(s, "holding_group", None),
                    "brand_name": _get_chain_name(s),
                    "store_format": getattr(s, "store_format", None),
                    "branch_name": _get_store_name(s),
                    "address": str(addr) if addr is not None else None,
                    "city": _get_city_name(s),
                    "province": getattr(s, "province", "Buenos Aires"),
                    "province_code": getattr(s, "province_code", "AR-B"),
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

    def search_articles(
        self, query: str, limit: int = 50, mode: str = "fuzzy"
    ) -> List[Article]:
        try:
            q = (query or "").strip()
            if not q:
                return []

            base_stmt = (
                select(Article)
                .options(
                    joinedload(Article.brand),
                    joinedload(Article.category),
                    selectinload(Article.tags),
                )
            )

            # 1. Exact / Direct EAN search if numeric
            if q.isdigit() and len(q) >= 6:
                ean_res = self._session.execute(
                    base_stmt.where(Article.ean == q).limit(limit)
                ).scalars().unique().all()
                if ean_res:
                    return list(ean_res)

            if mode == "exact":
                pattern = f"%{q}%"
                stmt = base_stmt.where(
                    (Article.name.ilike(pattern))
                    | (Article.clean_description.ilike(pattern))
                    | (Article.brand_name.ilike(pattern))
                    | (Article.ean == q)
                ).limit(limit)
                return list(self._session.execute(stmt).scalars().unique().all())

            # Fuzzy / Approximate Token Matching
            candidates_map: Dict[str, Article] = {}

            # Exact EAN check
            for a in self._session.execute(base_stmt.where(Article.ean == q).limit(limit)).scalars().unique():
                candidates_map[a.ean] = a

            tokens = [t.lower() for t in q.split() if t]
            conditions = []
            for tok in tokens:
                t_pat = f"%{tok}%"
                conditions.extend(
                    [
                        Article.name.ilike(t_pat),
                        Article.clean_description.ilike(t_pat),
                        Article.brand_name.ilike(t_pat),
                    ]
                )

            if conditions:
                token_stmt = base_stmt.where(or_(*conditions)).limit(limit * 3)
                for a in self._session.execute(token_stmt).scalars().unique():
                    candidates_map[a.ean] = a

            # Fallback if few candidates: check brands
            if len(candidates_map) < limit:
                all_brands = self._session.execute(select(Brand)).scalars().all()
                matched_brand_names = [
                    b.name
                    for b in all_brands
                    if any(fuzzy_similarity_ratio(tok, b.name) >= 0.75 for tok in tokens)
                    or fuzzy_similarity_ratio(q, b.name) >= 0.75
                ]
                if matched_brand_names:
                    brand_stmt = base_stmt.where(
                        Article.brand_name.in_(matched_brand_names[:20])
                    ).limit(limit * 2)
                    for a in self._session.execute(brand_stmt).scalars().unique():
                        candidates_map[a.ean] = a

            # If still few candidates, test small sample
            if len(candidates_map) < limit:
                sample_stmt = base_stmt.limit(100)
                for a in self._session.execute(sample_stmt).scalars().unique():
                    candidates_map[a.ean] = a

            # Rank candidates by similarity score
            scored: List[Tuple[float, Article]] = []
            q_lower = q.lower()

            for a in candidates_map.values():
                if a.ean == q:
                    scored.append((10.0, a))
                    continue

                desc_str = (a.name or a.clean_description or "").lower()
                b_str = (a.brand_name or "").lower()
                cat_str = (a.category.name if a.category else "").lower()
                full_text = f"{desc_str} {b_str} {cat_str}"

                if q_lower in full_text:
                    score = 5.0 + (len(q_lower) / max(len(full_text), 1))
                else:
                    tok_scores = []
                    for tok in tokens:
                        best_tok = 0.0
                        for word in full_text.split():
                            sim = fuzzy_similarity_ratio(tok, word)
                            if sim > best_tok:
                                best_tok = sim
                        tok_scores.append(best_tok)
                    avg_tok = sum(tok_scores) / len(tok_scores) if tok_scores else 0.0
                    score = max(
                        fuzzy_similarity_ratio(q_lower, desc_str),
                        fuzzy_similarity_ratio(q_lower, b_str),
                        avg_tok,
                    )

                if score >= 0.35:
                    scored.append((score, a))

            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [a for _, a in scored[:limit]]
        except Exception as exc:
            logger.error(
                "Error executing search_articles (query=%r, mode=%s): %s",
                query,
                mode,
                exc,
            )
            raise

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
        # 1. Prefer cities in the region that have points of sale with recorded prices
        if region:
            stmt_with_prices = (
                select(PointOfSale.city)
                .join(DailyPrice, DailyPrice.store_code == PointOfSale.code)
                .where(
                    func.upper(PointOfSale.province_code) == region.strip().upper(),
                    PointOfSale.city.isnot(None),
                    PointOfSale.city != "",
                )
                .distinct()
                .order_by(PointOfSale.city)
            )
            cities = list(self._session.execute(stmt_with_prices).scalars().all())
            if cities:
                return cities

            # 2. Fallback to points of sale for that region
            stmt_pos = (
                select(PointOfSale.city)
                .where(
                    func.upper(PointOfSale.province_code) == region.strip().upper(),
                    PointOfSale.city.isnot(None),
                    PointOfSale.city != "",
                    PointOfSale.city != PointOfSale.province,
                )
                .distinct()
                .order_by(PointOfSale.city)
            )
            cities = list(self._session.execute(stmt_pos).scalars().all())
            if cities:
                return cities

        # 3. Fallback: all distinct cities in points_of_sale
        stmt_all = (
            select(PointOfSale.city)
            .where(PointOfSale.city.isnot(None), PointOfSale.city != "")
            .distinct()
            .order_by(PointOfSale.city)
        )
        return list(self._session.execute(stmt_all).scalars().all())

    # Taxonomy navigation methods
    def get_departments(self) -> List[Category]:
        stmt = (
            select(Category)
            .where(Category.level == 1)
            .order_by(Category.name)
            .options(joinedload(Category.children))
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

    def get_articles_by_subcategory(
        self, subcategory_slug: str, limit: int = 50
    ) -> List[Article]:
        stmt = (
            select(Article)
            .join(Category, Article.category_id == Category.id)
            .where(Category.slug == subcategory_slug)
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().unique().all())

    def get_articles_by_tag(self, tag_name: str, limit: int = 50) -> List[Article]:
        stmt = (
            select(Article)
            .join(Article.tags)
            .where(Tag.name == tag_name)
            .options(
                joinedload(Article.brand),
                joinedload(Article.category),
                selectinload(Article.tags),
            )
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().unique().all())

    def get_candidate_substitutions(
        self, ean: str, limit: int = 5
    ) -> List[Article]:
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
            amt = getattr(p, "amount", None) or getattr(p, "price", 0)

            if raw_d and ean and store_code:
                rows.append(
                    {
                        "date": raw_d,
                        "ean": str(ean),
                        "store_code": str(store_code),
                        "price": int(amt),
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
                    DailyPrice.date == price_date,
                    DailyPrice.ean.in_(chunk_eans),
                )
            )
            results.extend(self._session.execute(stmt).scalars().all())
        return results

    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]:
        ref_dict: Dict[str, int] = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(DailyProductMetric.ean, DailyProductMetric.median_price)
                .where(
                    func.lower(DailyProductMetric.city) == func.lower(city.strip()),
                    DailyProductMetric.date == price_date,
                    DailyProductMetric.ean.in_(chunk_eans),
                )
            )
            for ean_val, med_p in self._session.execute(stmt).all():
                if med_p is not None:
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
            metric_date_stmt = select(func.max(DailyProductMetric.date)).where(
                DailyProductMetric.ean == clean_ean
            )
            if city:
                metric_date_stmt = metric_date_stmt.where(
                    func.lower(DailyProductMetric.city) == func.lower(city.strip())
                )
            target_date = self._session.execute(metric_date_stmt).scalar()

        if not target_date:
            price_date_stmt = select(func.max(DailyPrice.date)).where(
                DailyPrice.ean == clean_ean
            )
            if city:
                price_date_stmt = price_date_stmt.join(
                    PointOfSale, DailyPrice.store_code == PointOfSale.code
                ).where(func.lower(PointOfSale.city) == func.lower(city.strip()))
            target_date = self._session.execute(price_date_stmt).scalar()

        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        if not target_date:
            return ArticlePriceStats(
                ean=article.ean,
                name=article.name,
                clean_description=article.clean_description,
                brand_name=article.brand_name,
                package=article.package,
                category_name=article.category.name if article.category else None,
                date=None,
                city=city,
                min_price=None,
                max_price=None,
                reference_price=None,
                price_dispersion=None,
                cheapest_store=None,
                most_expensive_store=None,
                stores_count=0,
                store_prices=[],
            )

        # Observed store prices on target_date
        price_stmt = (
            select(DailyPrice, PointOfSale)
            .join(PointOfSale, DailyPrice.store_code == PointOfSale.code)
            .where(DailyPrice.ean == clean_ean, DailyPrice.date == target_date)
        )
        if city:
            price_stmt = price_stmt.where(
                func.lower(PointOfSale.city) == func.lower(city.strip())
            )

        price_stmt = price_stmt.order_by(DailyPrice.price.asc())
        price_rows = self._session.execute(price_stmt).all()

        store_details: List[StorePriceDetail] = []
        observed_prices: List[int] = []

        for dp, pos in price_rows:
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

        # Precomputed metrics on target_date
        metric_stmt = select(DailyProductMetric).where(
            DailyProductMetric.ean == clean_ean, DailyProductMetric.date == target_date
        )
        if city:
            metric_stmt = metric_stmt.where(
                func.lower(DailyProductMetric.city) == func.lower(city.strip())
            )

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
                ref_p = PriceMetricsCalculator.calculate_reference_price(observed_prices)
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
            store_details[0].city if store_details else (metrics[0].city if metrics else None)
        )

        return ArticlePriceStats(
            ean=article.ean,
            name=article.name,
            clean_description=article.clean_description,
            brand_name=article.brand_name,
            package=article.package,
            category_name=article.category.name if article.category else None,
            date=target_date,
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

    def create_user(self, email: str, password_hash: str) -> User:
        try:
            user_entity = User(email=email, password_hash=password_hash)
            self._session.add(user_entity)
            self._session.commit()
            self._session.refresh(user_entity)
            return user_entity
        except Exception as exc:
            self._session.rollback()
            logger.error("Failed to create user with email %s: %s", email, exc)
            raise

    def get_user_by_email(self, email: str) -> Optional[User]:
        try:
            stmt = select(User).where(User.email == email)
            return self._session.execute(stmt).scalar_one_or_none()
        except Exception as exc:
            logger.error("Failed to query user by email %s: %s", email, exc)
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

    def get_basket_by_uuid(self, uuid_str: str) -> Optional[Basket]:
        try:
            stmt = (
                select(Basket)
                .options(joinedload(Basket.items))
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
