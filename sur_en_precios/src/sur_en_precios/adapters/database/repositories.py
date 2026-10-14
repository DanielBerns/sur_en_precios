import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from sur_en_precios.domain.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleCategory,
    ArticleDescription,
    ArticleMetric,
    ArticleNumber,
    Branch,
    Business,
    City,
    Flag,
    Place,
    Price,
    State,
    Store,
    Timestamp,
)
from sur_en_precios.domain.models_user import (
    Basket,
    BasketItem,
    User,
)
from sur_en_precios.domain.normalizers import decode_region_code
from sur_en_precios.domain.ports import (
    CatalogRepositoryPort,
    PriceRepositoryPort,
    UserRepositoryPort,
)
from sur_en_precios.domain.services import fuzzy_similarity_ratio

logger = logging.getLogger("sur_en_precios.repositories")

CHUNK_SIZE = 500


def _get_brand_str(item: Any) -> Optional[str]:
    b = getattr(item, "brand", None)
    if b is not None and hasattr(b, "brand"):
        return str(b.brand)
    return str(b) if b is not None else None


def _get_category_str(item: Any) -> Optional[str]:
    c = getattr(item, "category", None)
    if c is not None and hasattr(c, "content"):
        return str(c.content)
    if c is not None and hasattr(c, "category"):
        return str(c.category)
    return str(c) if c is not None else None


def _get_description_str(item: Any) -> str:
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
    if hasattr(s, "chain_name") and s.chain_name:
        return str(s.chain_name)
    if hasattr(s, "flag") and s.flag:
        return str(s.flag.flag if hasattr(s.flag, "flag") else s.flag)
    return ""


def _get_store_name(s: Any) -> str:
    if hasattr(s, "store_name") and s.store_name:
        return str(s.store_name)
    if hasattr(s, "branch_name") and s.branch_name:
        return str(s.branch_name)
    if hasattr(s, "branch") and s.branch:
        return str(s.branch.branch if hasattr(s.branch, "branch") else s.branch)
    return ""


def _get_city_name(s: Any) -> str:
    if hasattr(s, "city") and s.city:
        return str(s.city)
    if hasattr(s, "place") and s.place and hasattr(s.place, "city") and s.place.city:
        return str(s.place.city.name)
    return "General"


def _get_state_code_and_name(s: Any) -> Tuple[str, str]:
    if hasattr(s, "place") and s.place and hasattr(s.place, "city") and s.place.city:
        city_obj = s.place.city
        if hasattr(city_obj, "state") and city_obj.state:
            code = getattr(city_obj.state, "code", "AR-B")
            name = getattr(city_obj.state, "name", None) or decode_region_code(code)
            return str(code), str(name)
    if hasattr(s, "state") and s.state:
        st = s.state
        code = getattr(st, "code", "AR-B")
        name = getattr(st, "name", None) or decode_region_code(code)
        return str(code), str(name)
    if hasattr(s, "province") and s.province:
        prov = str(s.province)
        return prov, decode_region_code(prov)
    return "AR-B", "Buenos Aires"


class SqlAlchemyCatalogRepository(CatalogRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for article and store catalog."""

    def __init__(self, session: Session):
        self._session = session

    def save_articles(
        self, articles: List[ArticleCard], batch_size: int = 10_000
    ) -> None:
        if not articles:
            return

        # 1. Distinct Brands
        brand_set: Set[str] = set()
        for a in articles:
            b_val = _get_brand_str(a)
            if b_val:
                brand_set.add(b_val)
        brands = list(brand_set)
        for i in range(0, len(brands), CHUNK_SIZE):
            chunk_brands = [{"brand": b} for b in brands[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleBrand).values(chunk_brands)
            stmt = stmt.on_conflict_do_nothing(index_elements=["brand"])
            self._session.execute(stmt)

        # 2. Distinct Categories (content column)
        cat_set: Set[str] = set()
        for a in articles:
            c_val = _get_category_str(a)
            if c_val:
                cat_set.add(c_val)
        categories = list(cat_set)
        for i in range(0, len(categories), CHUNK_SIZE):
            chunk_cats = [{"content": c} for c in categories[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleCategory).values(chunk_cats)
            stmt = stmt.on_conflict_do_nothing(index_elements=["content"])
            self._session.execute(stmt)

        # 3. Distinct Descriptions (content column)
        desc_set: Set[str] = set()
        for a in articles:
            d_val = _get_description_str(a)
            if d_val:
                desc_set.add(d_val)
        descriptions = list(desc_set)
        for i in range(0, len(descriptions), CHUNK_SIZE):
            chunk_descs = [{"content": d} for d in descriptions[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleDescription).values(chunk_descs)
            stmt = stmt.on_conflict_do_nothing(index_elements=["content"])
            self._session.execute(stmt)

        # 4. Distinct Article Numbers (ean column in article_numbers)
        ean_set: Set[str] = set()
        for a in articles:
            e_val = _get_ean_str(a)
            if e_val:
                ean_set.add(e_val)
        eans = list(ean_set)
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = [{"ean": e} for e in eans[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleNumber).values(chunk_eans)
            stmt = stmt.on_conflict_do_nothing(index_elements=["ean"])
            self._session.execute(stmt)

        self._session.flush()

        # Build lookup dicts using chunked IN queries
        brand_map: Dict[str, int] = {}
        for i in range(0, len(brands), CHUNK_SIZE):
            chunk_b = brands[i : i + CHUNK_SIZE]
            for brand_entity in self._session.execute(
                select(ArticleBrand).where(ArticleBrand.brand.in_(chunk_b))
            ).scalars():
                brand_map[brand_entity.brand] = brand_entity.id

        cat_map: Dict[str, int] = {}
        for i in range(0, len(categories), CHUNK_SIZE):
            chunk_c = categories[i : i + CHUNK_SIZE]
            for cat_entity in self._session.execute(
                select(ArticleCategory).where(ArticleCategory.content.in_(chunk_c))
            ).scalars():
                cat_map[cat_entity.content] = cat_entity.id

        desc_map: Dict[str, int] = {}
        for i in range(0, len(descriptions), CHUNK_SIZE):
            chunk_d = descriptions[i : i + CHUNK_SIZE]
            for desc_entity in self._session.execute(
                select(ArticleDescription).where(
                    ArticleDescription.content.in_(chunk_d)
                )
            ).scalars():
                desc_map[desc_entity.content] = desc_entity.id

        number_map: Dict[str, int] = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_n = eans[i : i + CHUNK_SIZE]
            for num_entity in self._session.execute(
                select(ArticleNumber).where(ArticleNumber.ean.in_(chunk_n))
            ).scalars():
                number_map[num_entity.ean] = num_entity.id

        # 5. Insert ArticleCards in chunked batches
        cards_to_insert = []
        for a in articles:
            ean_val = _get_ean_str(a)
            number_id = number_map.get(ean_val)
            if not number_id:
                continue
            desc_val = _get_description_str(a)
            desc_id = desc_map.get(desc_val)
            if not desc_id:
                continue
            brand_val = _get_brand_str(a)
            cat_val = _get_category_str(a)

            brand_id = brand_map.get(brand_val) if brand_val else None
            cat_id = cat_map.get(cat_val) if cat_val else None

            cards_to_insert.append(
                {
                    "article_number_id": number_id,
                    "description_id": desc_id,
                    "brand_id": brand_id,
                    "category_id": cat_id,
                }
            )

        for i in range(0, len(cards_to_insert), CHUNK_SIZE):
            chunk_cards = cards_to_insert[i : i + CHUNK_SIZE]
            stmt = sqlite_insert(ArticleCard).values(chunk_cards)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["article_number_id", "description_id"]
            )
            self._session.execute(stmt)

        self._session.commit()

    def save_stores(self, stores: List[Store], batch_size: int = 10_000) -> None:
        if not stores:
            return

        flags_set: Set[str] = set()
        branches_set: Set[str] = set()
        for s in stores:
            f_val = _get_chain_name(s)
            if f_val:
                flags_set.add(f_val)
            b_val = _get_store_name(s)
            if b_val:
                branches_set.add(b_val)

        flags = list(flags_set)
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk_flags = [{"flag": f} for f in flags[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Flag)
                .values(chunk_flags)
                .on_conflict_do_nothing(index_elements=["flag"])
            )
            chunk_biz = [{"business": f} for f in flags[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Business)
                .values(chunk_biz)
                .on_conflict_do_nothing(index_elements=["business"])
            )

        branches = list(branches_set)
        for i in range(0, len(branches), CHUNK_SIZE):
            chunk_branches = [{"branch": b} for b in branches[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Branch)
                .values(chunk_branches)
                .on_conflict_do_nothing(index_elements=["branch"])
            )

        # Ensure States exist
        states_dict: Dict[str, str] = {}
        for s in stores:
            st_code, st_name = _get_state_code_and_name(s)
            states_dict[st_code] = st_name

        for st_code, st_name in states_dict.items():
            self._session.execute(
                sqlite_insert(State)
                .values([{"code": st_code, "name": st_name}])
                .on_conflict_do_nothing(index_elements=["code"])
            )
        self._session.flush()

        state_map: Dict[str, int] = {}
        for st_entity in self._session.execute(
            select(State).where(State.code.in_(list(states_dict.keys())))
        ).scalars():
            state_map[st_entity.code] = st_entity.id

        # Ensure Cities exist (UniqueConstraint: name, state_id)
        city_tuples: Set[Tuple[str, int]] = set()
        for s in stores:
            c_name = _get_city_name(s)
            st_code, _ = _get_state_code_and_name(s)
            st_id = state_map.get(st_code) or next(iter(state_map.values()))
            city_tuples.add((c_name, st_id))

        for c_name, st_id in city_tuples:
            self._session.execute(
                sqlite_insert(City)
                .values([{"name": c_name, "state_id": st_id}])
                .on_conflict_do_nothing(index_elements=["name", "state_id"])
            )
        self._session.flush()

        city_map: Dict[str, int] = {}
        for city_entity in self._session.execute(
            select(City).where(City.name.in_([ct[0] for ct in city_tuples]))
        ).scalars():
            city_map[city_entity.name] = city_entity.id

        flag_map: Dict[str, int] = {}
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk_fl = flags[i : i + CHUNK_SIZE]
            for flag_entity in self._session.execute(
                select(Flag).where(Flag.flag.in_(chunk_fl))
            ).scalars():
                flag_map[flag_entity.flag] = flag_entity.id

        biz_map: Dict[str, int] = {}
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk_bz = flags[i : i + CHUNK_SIZE]
            for biz_entity in self._session.execute(
                select(Business).where(Business.business.in_(chunk_bz))
            ).scalars():
                biz_map[biz_entity.business] = biz_entity.id

        branch_map: Dict[str, int] = {}
        for i in range(0, len(branches), CHUNK_SIZE):
            chunk_br = branches[i : i + CHUNK_SIZE]
            for branch_entity in self._session.execute(
                select(Branch).where(Branch.branch.in_(chunk_br))
            ).scalars():
                branch_map[branch_entity.branch] = branch_entity.id

        for s in stores:
            store_code = _get_store_code(s)
            city_str = _get_city_name(s)
            city_id = city_map.get(city_str)

            place_ref = getattr(s, "place", None)
            address_val = (
                getattr(place_ref, "address", None)
                if place_ref
                else getattr(s, "address", None)
            )
            addr_str: Optional[str] = None
            if address_val is not None:
                if hasattr(address_val, "address"):
                    addr_str = str(address_val.address)
                else:
                    addr_str = str(address_val)

            lat_val = (
                getattr(place_ref, "latitude", None)
                if place_ref
                else getattr(s, "latitude", None)
            )
            lon_val = (
                getattr(place_ref, "longitude", None)
                if place_ref
                else getattr(s, "longitude", None)
            )

            pos = self._session.execute(
                select(Store).where(Store.code == store_code)
            ).scalar_one_or_none()

            chain_str = _get_chain_name(s)
            store_str = _get_store_name(s)
            flag_id = flag_map.get(chain_str)
            biz_id = biz_map.get(chain_str)
            branch_id = branch_map.get(store_str)

            lat_float = float(lat_val) if lat_val is not None else None
            lon_float = float(lon_val) if lon_val is not None else None

            if pos and pos.place_id:
                place = self._session.get(Place, pos.place_id)
                if place:
                    place.address = addr_str
                    place.city_id = city_id
                    place.latitude = lat_float
                    place.longitude = lon_float
                else:
                    place = Place(
                        address=addr_str,
                        city_id=city_id,
                        latitude=lat_float,
                        longitude=lon_float,
                    )
                    self._session.add(place)
                    self._session.flush()
                    pos.place_id = place.id
                pos.flag_id = flag_id
                pos.business_id = biz_id
                pos.branch_id = branch_id
            elif pos:
                place = Place(
                    address=addr_str,
                    city_id=city_id,
                    latitude=lat_float,
                    longitude=lon_float,
                )
                self._session.add(place)
                self._session.flush()
                pos.flag_id = flag_id
                pos.business_id = biz_id
                pos.branch_id = branch_id
                pos.place_id = place.id
            else:
                place = Place(
                    address=addr_str,
                    city_id=city_id,
                    latitude=lat_float,
                    longitude=lon_float,
                )
                self._session.add(place)
                self._session.flush()
                pos = Store(
                    code=store_code,
                    flag_id=flag_id,
                    business_id=biz_id,
                    branch_id=branch_id,
                    place_id=place.id,
                )
                self._session.add(pos)

        self._session.commit()

    def search_articles(
        self, query: str, limit: int = 50, mode: str = "fuzzy"
    ) -> List[ArticleCard]:
        """
        Searches articles in the catalog by description, brand, category, or EAN.
        Supports exact search or approximate/fuzzy search using Levenshtein distance.
        """
        try:
            q = (query or "").strip()
            if not q:
                return []

            base_stmt = (
                select(ArticleCard)
                .join(
                    ArticleNumber,
                    ArticleCard.article_number_id == ArticleNumber.id,
                )
                .join(
                    ArticleDescription,
                    ArticleCard.description_id == ArticleDescription.id,
                )
                .outerjoin(ArticleBrand, ArticleCard.brand_id == ArticleBrand.id)
                .outerjoin(
                    ArticleCategory,
                    ArticleCard.category_id == ArticleCategory.id,
                )
                .options(
                    joinedload(ArticleCard.article_number),
                    joinedload(ArticleCard.description),
                    joinedload(ArticleCard.brand),
                    joinedload(ArticleCard.category),
                )
            )

            if mode == "exact":
                pattern = f"%{q}%"
                stmt = base_stmt.where(
                    (ArticleDescription.content.ilike(pattern))
                    | (ArticleBrand.brand.ilike(pattern))
                    | (ArticleCategory.content.ilike(pattern))
                    | (ArticleNumber.ean == q)
                ).limit(limit)
                return list(self._session.execute(stmt).scalars().all())

            # Fuzzy / Approximate search
            candidates_map: Dict[int, ArticleCard] = {}

            # 1. Exact EAN search if query looks like a code
            if q.isdigit() and len(q) >= 6:
                ean_stmt = base_stmt.where(ArticleNumber.ean == q).limit(limit)
                for card in self._session.execute(ean_stmt).scalars():
                    candidates_map[card.id] = card

            # 2. Token-based ILIKE candidate matching
            tokens = [t.lower() for t in q.split() if t]
            conditions = []
            for tok in tokens:
                t_pat = f"%{tok}%"
                conditions.extend(
                    [
                        ArticleDescription.content.ilike(t_pat),
                        ArticleBrand.brand.ilike(t_pat),
                        ArticleCategory.content.ilike(t_pat),
                        ArticleNumber.ean == tok,
                    ]
                )

            if conditions:
                token_stmt = base_stmt.where(or_(*conditions)).limit(limit * 3)
                for card in self._session.execute(token_stmt).scalars():
                    candidates_map[card.id] = card

            # 3. If candidates are few (< limit), check fuzzy Levenshtein match on brands
            if len(candidates_map) < limit:
                all_brands = self._session.execute(select(ArticleBrand)).scalars().all()
                matched_brand_ids = [
                    b.id
                    for b in all_brands
                    if any(
                        fuzzy_similarity_ratio(tok, b.brand) >= 0.75 for tok in tokens
                    )
                    or fuzzy_similarity_ratio(q, b.brand) >= 0.75
                ]
                if matched_brand_ids:
                    brand_stmt = base_stmt.where(
                        ArticleCard.brand_id.in_(matched_brand_ids[:20])
                    ).limit(limit * 2)
                    for card in self._session.execute(brand_stmt).scalars():
                        candidates_map[card.id] = card

            # Fallback: if still few candidates, fetch a small catalog slice to test typos
            if len(candidates_map) < limit:
                sample_stmt = base_stmt.limit(100)
                for card in self._session.execute(sample_stmt).scalars():
                    candidates_map[card.id] = card

            # 4. Rank candidates by similarity score
            scored_cards: List[Tuple[float, ArticleCard]] = []
            q_lower = q.lower()

            for card in candidates_map.values():
                if card.ean == q:
                    scored_cards.append((10.0, card))
                    continue

                desc_str = (card.name or "").lower()
                brand_str = (card.brand_name or "").lower()
                cat_str = (card.category_name or "").lower()
                full_text = f"{desc_str} {brand_str} {cat_str}"

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
                        fuzzy_similarity_ratio(q_lower, brand_str),
                        avg_tok,
                    )

                if score >= 0.35:
                    scored_cards.append((score, card))

            scored_cards.sort(key=lambda pair: pair[0], reverse=True)
            return [card for _, card in scored_cards[:limit]]
        except Exception as exc:
            logger.error(
                "Error executing search_articles (query=%r, mode=%s): %s",
                query,
                mode,
                exc,
                exc_info=True,
            )
            raise

    def get_article_by_ean(self, ean: str) -> Optional[ArticleCard]:
        stmt = (
            select(ArticleCard)
            .join(ArticleNumber, ArticleCard.article_number_id == ArticleNumber.id)
            .join(
                ArticleDescription,
                ArticleCard.description_id == ArticleDescription.id,
            )
            .outerjoin(ArticleBrand, ArticleCard.brand_id == ArticleBrand.id)
            .outerjoin(ArticleCategory, ArticleCard.category_id == ArticleCategory.id)
            .options(
                joinedload(ArticleCard.article_number),
                joinedload(ArticleCard.description),
                joinedload(ArticleCard.brand),
                joinedload(ArticleCard.category),
            )
            .where(ArticleNumber.ean == ean)
        )
        return self._session.execute(stmt).scalars().first()

    def get_stores_by_city(self, city: str) -> List[Store]:
        stmt = (
            select(Store)
            .join(Place, Store.place_id == Place.id)
            .join(City, Place.city_id == City.id)
            .outerjoin(Flag, Store.flag_id == Flag.id)
            .outerjoin(Branch, Store.branch_id == Branch.id)
            .outerjoin(Business, Store.business_id == Business.id)
            .options(
                joinedload(Store.place).joinedload(Place.city).joinedload(City.state),
                joinedload(Store.flag),
                joinedload(Store.branch),
                joinedload(Store.business),
            )
            .where(City.name == city)
        )
        results = self._session.execute(stmt).scalars().all()
        return list(results)


class SqlAlchemyPriceRepository(PriceRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for prices and metrics."""

    def __init__(self, session: Session):
        self._session = session

    def save_prices(self, prices: List[Price], batch_size: int = 10_000) -> None:
        if not prices:
            return

        # 1. Distinct Timestamps (Timestamp.value is date)
        distinct_dates: Set[date] = set()
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
            if isinstance(raw_d, date):
                distinct_dates.add(raw_d)

        for p_date in distinct_dates:
            stmt = (
                sqlite_insert(Timestamp)
                .values([{"value": p_date}])
                .on_conflict_do_nothing(index_elements=["value"])
            )
            self._session.execute(stmt)
        self._session.flush()

        timestamp_map: Dict[date, int] = {}
        for ts in self._session.execute(
            select(Timestamp).where(Timestamp.value.in_(list(distinct_dates)))
        ).scalars():
            timestamp_map[ts.value] = ts.id

        # 2. Distinct Article Numbers (table article_numbers)
        distinct_eans_set: Set[str] = set()
        for p in prices:
            e_str = _get_ean_str(p)
            if e_str:
                distinct_eans_set.add(e_str)
        distinct_eans = list(distinct_eans_set)

        for i in range(0, len(distinct_eans), CHUNK_SIZE):
            chunk_eans = [{"ean": e} for e in distinct_eans[i : i + CHUNK_SIZE]]
            stmt = (
                sqlite_insert(ArticleNumber)
                .values(chunk_eans)
                .on_conflict_do_nothing(index_elements=["ean"])
            )
            self._session.execute(stmt)
        self._session.flush()

        number_map: Dict[str, int] = {}
        for i in range(0, len(distinct_eans), CHUNK_SIZE):
            chunk_en = distinct_eans[i : i + CHUNK_SIZE]
            for an in self._session.execute(
                select(ArticleNumber).where(ArticleNumber.ean.in_(chunk_en))
            ).scalars():
                number_map[an.ean] = an.id

        # 3. Distinct Stores (table stores)
        distinct_stores_set: Set[str] = set()
        for p in prices:
            st_ref = getattr(p, "store", None)
            if st_ref is not None:
                distinct_stores_set.add(_get_store_code(st_ref))
            else:
                code_val = getattr(p, "store_code", None) or getattr(
                    p, "store_id", None
                )
                if code_val is not None:
                    distinct_stores_set.add(str(code_val))
        distinct_stores = list(distinct_stores_set)

        for i in range(0, len(distinct_stores), CHUNK_SIZE):
            chunk_st = [{"code": s} for s in distinct_stores[i : i + CHUNK_SIZE]]
            stmt = (
                sqlite_insert(Store)
                .values(chunk_st)
                .on_conflict_do_nothing(index_elements=["code"])
            )
            self._session.execute(stmt)
        self._session.flush()

        store_map: Dict[str, int] = {}
        for i in range(0, len(distinct_stores), CHUNK_SIZE):
            chunk_sc = distinct_stores[i : i + CHUNK_SIZE]
            for st in self._session.execute(
                select(Store).where(Store.code.in_(chunk_sc))
            ).scalars():
                store_map[st.code] = st.id

        # 4. Insert/Upsert Prices in chunked batches
        values = []
        for p in prices:
            p_date_val: Optional[date] = getattr(p, "date", None) or getattr(
                p, "price_date", None
            )
            if (
                p_date_val is None
                and hasattr(p, "timestamp")
                and p.timestamp is not None
            ):
                ts_inner = getattr(p.timestamp, "value", p.timestamp)
                if isinstance(ts_inner, datetime):
                    p_date_val = ts_inner.date()
                elif isinstance(ts_inner, date):
                    p_date_val = ts_inner
            elif isinstance(p_date_val, datetime):
                p_date_val = p_date_val.date()

            ts_id = timestamp_map.get(p_date_val) if p_date_val else None
            art_id = number_map.get(_get_ean_str(p))

            store_ref = getattr(p, "store_code", None)
            if not store_ref and hasattr(p, "store") and p.store is not None:
                store_ref = p.store.code
            if not store_ref:
                store_ref = getattr(p, "store_id", None)
            st_id = store_map.get(str(store_ref)) if store_ref else None

            amt_raw = getattr(p, "amount", None)
            if amt_raw is None:
                amt_raw = getattr(p, "price", 0)
            amt_int = int(amt_raw) if amt_raw is not None else 0

            if ts_id and art_id and st_id:
                values.append(
                    {
                        "amount": amt_int,
                        "timestamp_id": ts_id,
                        "store_id": st_id,
                        "article_number_id": art_id,
                    }
                )

        eff_batch = min(batch_size, 200)
        for i in range(0, len(values), eff_batch):
            chunk_prices = values[i : i + eff_batch]
            stmt = sqlite_insert(Price).values(chunk_prices)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "timestamp_id",
                    "store_id",
                    "article_number_id",
                ],
                set_={"amount": stmt.excluded.amount},
            )
            self._session.execute(stmt)
        self._session.commit()

    def save_metrics(
        self, metrics: List[ArticleMetric], batch_size: int = 10_000
    ) -> None:
        if not metrics:
            return

        distinct_dates: Set[date] = set()
        distinct_eans: Set[str] = set()
        distinct_cities: Set[str] = set()

        for m in metrics:
            m_date_val: Optional[date] = getattr(m, "date", None)
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

            if isinstance(m_date_val, date):
                distinct_dates.add(m_date_val)

            ean = _get_ean_str(m)
            if ean:
                distinct_eans.add(ean)

            city_name = getattr(m, "city_name", None) or (
                m.city.name
                if hasattr(m, "city") and m.city
                else getattr(m, "city", "General")
            )
            distinct_cities.add(str(city_name))

        # 1. Timestamps
        for d in distinct_dates:
            self._session.execute(
                sqlite_insert(Timestamp)
                .values([{"value": d}])
                .on_conflict_do_nothing(index_elements=["value"])
            )
        self._session.flush()
        ts_map = {
            ts.value: ts.id
            for ts in self._session.execute(
                select(Timestamp).where(Timestamp.value.in_(list(distinct_dates)))
            ).scalars()
        }

        # 2. ArticleNumbers
        distinct_eans_list = list(distinct_eans)
        for i in range(0, len(distinct_eans_list), CHUNK_SIZE):
            chunk_eans = [{"ean": e} for e in distinct_eans_list[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(ArticleNumber)
                .values(chunk_eans)
                .on_conflict_do_nothing(index_elements=["ean"])
            )
        self._session.flush()

        num_map = {}
        for i in range(0, len(distinct_eans_list), CHUNK_SIZE):
            chunk_en = distinct_eans_list[i : i + CHUNK_SIZE]
            for an in self._session.execute(
                select(ArticleNumber).where(ArticleNumber.ean.in_(chunk_en))
            ).scalars():
                num_map[an.ean] = an.id

        # 3. Cities
        existing_cities = {
            c.name: c.id
            for c in self._session.execute(
                select(City).where(City.name.in_(list(distinct_cities)))
            ).scalars()
        }
        missing_cities = [c for c in distinct_cities if c not in existing_cities]

        if missing_cities:
            default_state = self._session.execute(select(State)).scalars().first()
            if not default_state:
                default_state = State(code="AR-B", name="Buenos Aires")
                self._session.add(default_state)
                self._session.flush()

            for c in missing_cities:
                self._session.execute(
                    sqlite_insert(City)
                    .values([{"name": c, "state_id": default_state.id}])
                    .on_conflict_do_nothing(index_elements=["name", "state_id"])
                )
            self._session.flush()

        city_map = {
            c.name: c.id
            for c in self._session.execute(
                select(City).where(City.name.in_(list(distinct_cities)))
            ).scalars()
        }

        values = []
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

            ts_id = getattr(m, "timestamp_id", None) or (
                ts_map.get(m_date_val) if m_date_val else None
            )
            ean = _get_ean_str(m)
            num_id = getattr(m, "article_number_id", None) or num_map.get(ean)

            c_name = getattr(m, "city_name", None) or (
                m.city.name
                if hasattr(m, "city") and m.city
                else getattr(m, "city", "General")
            )
            city_id = getattr(m, "city_id", None) or city_map.get(str(c_name))

            if ts_id and num_id and city_id:
                values.append(
                    {
                        "timestamp_id": ts_id,
                        "article_number_id": num_id,
                        "city_id": city_id,
                        "min_price": getattr(m, "min_price", None),
                        "max_price": getattr(m, "max_price", None),
                        "reference_price": getattr(m, "reference_price", None),
                        "price_dispersion": getattr(m, "price_dispersion", None),
                    }
                )

        eff_batch = min(batch_size, 80)
        for i in range(0, len(values), eff_batch):
            chunk_metrics = values[i : i + eff_batch]
            stmt = sqlite_insert(ArticleMetric).values(chunk_metrics)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "timestamp_id",
                    "article_number_id",
                    "city_id",
                ],
                set_={
                    "min_price": stmt.excluded.min_price,
                    "max_price": stmt.excluded.max_price,
                    "reference_price": stmt.excluded.reference_price,
                    "price_dispersion": stmt.excluded.price_dispersion,
                },
            )
            self._session.execute(stmt)
        self._session.commit()

    def delete_prices_for_date(self, price_date: date) -> int:
        ts_ids = (
            self._session.execute(
                select(Timestamp.id).where(Timestamp.value == price_date)
            )
            .scalars()
            .all()
        )
        if not ts_ids:
            return 0
        stmt = delete(Price).where(Price.timestamp_id.in_(ts_ids))
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_metrics_for_date(self, metric_date: date) -> int:
        ts_ids = (
            self._session.execute(
                select(Timestamp.id).where(Timestamp.value == metric_date)
            )
            .scalars()
            .all()
        )
        if not ts_ids:
            return 0
        stmt = delete(ArticleMetric).where(ArticleMetric.timestamp_id.in_(ts_ids))
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[Price]:
        results: List[Price] = []
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(Price)
                .join(Store, Price.store_id == Store.id)
                .join(Place, Store.place_id == Place.id)
                .join(City, Place.city_id == City.id)
                .join(ArticleNumber, Price.article_number_id == ArticleNumber.id)
                .join(Timestamp, Price.timestamp_id == Timestamp.id)
                .options(
                    joinedload(Price.store)
                    .joinedload(Store.place)
                    .joinedload(Place.city),
                    joinedload(Price.store).joinedload(Store.flag),
                    joinedload(Price.store).joinedload(Store.branch),
                    joinedload(Price.store).joinedload(Store.business),
                    joinedload(Price.article_number),
                    joinedload(Price.timestamp),
                )
                .where(
                    City.name == city,
                    Timestamp.value == price_date,
                    ArticleNumber.ean.in_(chunk_eans),
                )
            )
            chunk_results = self._session.execute(stmt).scalars().all()
            results.extend(chunk_results)

        return results

    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]:
        ref_dict: Dict[str, int] = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(ArticleNumber.ean, ArticleMetric.reference_price)
                .join(
                    ArticleNumber,
                    ArticleMetric.article_number_id == ArticleNumber.id,
                )
                .join(City, ArticleMetric.city_id == City.id)
                .join(Timestamp, ArticleMetric.timestamp_id == Timestamp.id)
                .where(
                    City.name == city,
                    Timestamp.value == price_date,
                    ArticleNumber.ean.in_(chunk_eans),
                )
            )
            results = self._session.execute(stmt).all()
            for ean, ref_p in results:
                if ref_p is not None:
                    ref_dict[ean] = int(ref_p)

        return ref_dict


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
            logger.error(
                "Failed to create user with email %s: %s", email, exc, exc_info=True
            )
            raise

    def get_user_by_email(self, email: str) -> Optional[User]:
        try:
            stmt = select(User).where(User.email == email)
            return self._session.execute(stmt).scalar_one_or_none()
        except Exception as exc:
            logger.error(
                "Failed to query user by email %s: %s", email, exc, exc_info=True
            )
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
                exc_info=True,
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
                exc_info=True,
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
            logger.error(
                "Failed to fetch basket by uuid %s: %s", uuid_str, exc, exc_info=True
            )
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
                exc_info=True,
            )
            raise
