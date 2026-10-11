import uuid
from datetime import date, datetime, time
from typing import Dict, List, Optional, Set

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleCategory,
    ArticleCode,
    ArticleDescription,
    Branch,
    Business,
    City,
    DailyPriceModel,
    DailyProductMetricModel,
    Flag,
    Place,
    PointOfSale,
    Price,
    ProductModel,
    StoreModel,
    Timestamp,
)
from sur_en_precios.adapters.database.models_user import (
    ListItemModel,
    ShoppingListModel,
    UserModel,
)
from sur_en_precios.domain.models import (
    DailyPrice,
    DailyProductMetrics,
    ListItem,
    Product,
    ShoppingList,
    Store,
    User,
)
from sur_en_precios.domain.ports import (
    CatalogRepositoryPort,
    PriceRepositoryPort,
    UserRepositoryPort,
)


CHUNK_SIZE = 500


class SqlAlchemyCatalogRepository(CatalogRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for products and stores catalog."""

    def __init__(self, session: Session):
        self._session = session

    def save_products(self, products: List[Product], batch_size: int = 10_000) -> None:
        if not products:
            return

        # 1. Distinct Brands
        brands: List[str] = list({p.brand for p in products if p.brand})
        for i in range(0, len(brands), CHUNK_SIZE):
            chunk_brands = [{"brand": b} for b in brands[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleBrand).values(chunk_brands)
            stmt = stmt.on_conflict_do_nothing(index_elements=["brand"])
            self._session.execute(stmt)

        # 2. Distinct Categories
        categories: List[str] = list({p.category for p in products if p.category})
        for i in range(0, len(categories), CHUNK_SIZE):
            chunk_cats = [{"category": c} for c in categories[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleCategory).values(chunk_cats)
            stmt = stmt.on_conflict_do_nothing(index_elements=["category"])
            self._session.execute(stmt)

        # 3. Distinct Descriptions
        descriptions: List[str] = list({p.name for p in products if p.name})
        for i in range(0, len(descriptions), CHUNK_SIZE):
            chunk_descs = [{"description": d} for d in descriptions[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleDescription).values(chunk_descs)
            stmt = stmt.on_conflict_do_nothing(index_elements=["description"])
            self._session.execute(stmt)

        # 4. Distinct Article Codes (EAN)
        eans: List[str] = list({p.ean for p in products if p.ean})
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = [{"ean": e} for e in eans[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleCode).values(chunk_eans)
            stmt = stmt.on_conflict_do_nothing(index_elements=["ean"])
            self._session.execute(stmt)

        self._session.flush()

        # Build lookup dicts using chunked IN queries
        brand_map: Dict[str, int] = {}
        for i in range(0, len(brands), CHUNK_SIZE):
            chunk = brands[i : i + CHUNK_SIZE]
            for b in self._session.execute(
                select(ArticleBrand).where(ArticleBrand.brand.in_(chunk))
            ).scalars():
                brand_map[b.brand] = b.id

        cat_map: Dict[str, int] = {}
        for i in range(0, len(categories), CHUNK_SIZE):
            chunk = categories[i : i + CHUNK_SIZE]
            for c in self._session.execute(
                select(ArticleCategory).where(ArticleCategory.category.in_(chunk))
            ).scalars():
                cat_map[c.category] = c.id

        desc_map: Dict[str, int] = {}
        for i in range(0, len(descriptions), CHUNK_SIZE):
            chunk = descriptions[i : i + CHUNK_SIZE]
            for d in self._session.execute(
                select(ArticleDescription).where(ArticleDescription.description.in_(chunk))
            ).scalars():
                desc_map[d.description] = d.id

        code_map: Dict[str, int] = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk = eans[i : i + CHUNK_SIZE]
            for c in self._session.execute(
                select(ArticleCode).where(ArticleCode.ean.in_(chunk))
            ).scalars():
                code_map[c.ean] = c.id

        # 5. Insert / Upsert ArticleCards in chunked batches
        cards_to_insert = []
        for p in products:
            code_id = code_map.get(p.ean)
            if not code_id:
                continue
            brand_id = brand_map.get(p.brand) if p.brand else None
            cat_id = cat_map.get(p.category) if p.category else None
            desc_id = desc_map.get(p.name) if p.name else None

            cards_to_insert.append(
                {
                    "code_id": code_id,
                    "brand_id": brand_id,
                    "category_id": cat_id,
                    "description_id": desc_id,
                }
            )

        for i in range(0, len(cards_to_insert), CHUNK_SIZE):
            chunk_cards = cards_to_insert[i : i + CHUNK_SIZE]
            stmt = sqlite_insert(ArticleCard).values(chunk_cards)
            stmt = stmt.on_conflict_do_nothing(index_elements=["code_id"])
            self._session.execute(stmt)

        self._session.commit()

    def save_stores(self, stores: List[Store], batch_size: int = 10_000) -> None:
        if not stores:
            return

        flags: List[str] = list({s.chain_name for s in stores if s.chain_name})
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk_flags = [{"flag": f} for f in flags[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Flag).values(chunk_flags).on_conflict_do_nothing(index_elements=["flag"])
            )
            chunk_biz = [{"business": f} for f in flags[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Business).values(chunk_biz).on_conflict_do_nothing(index_elements=["business"])
            )

        branches: List[str] = list({s.store_name for s in stores if s.store_name})
        for i in range(0, len(branches), CHUNK_SIZE):
            chunk_branches = [{"branch": b} for b in branches[i : i + CHUNK_SIZE]]
            self._session.execute(
                sqlite_insert(Branch).values(chunk_branches).on_conflict_do_nothing(index_elements=["branch"])
            )

        cities: List[str] = list({s.city for s in stores if s.city})
        for c in cities:
            existing_city = self._session.execute(select(City).where(City.name == c)).scalar_one_or_none()
            if not existing_city:
                self._session.add(City(name=c))

        self._session.flush()

        flag_map: Dict[str, int] = {}
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk = flags[i : i + CHUNK_SIZE]
            for f in self._session.execute(select(Flag).where(Flag.flag.in_(chunk))).scalars():
                flag_map[f.flag] = f.id

        biz_map: Dict[str, int] = {}
        for i in range(0, len(flags), CHUNK_SIZE):
            chunk = flags[i : i + CHUNK_SIZE]
            for b in self._session.execute(select(Business).where(Business.business.in_(chunk))).scalars():
                biz_map[b.business] = b.id

        branch_map: Dict[str, int] = {}
        for i in range(0, len(branches), CHUNK_SIZE):
            chunk = branches[i : i + CHUNK_SIZE]
            for b in self._session.execute(select(Branch).where(Branch.branch.in_(chunk))).scalars():
                branch_map[b.branch] = b.id

        city_map: Dict[str, int] = {}
        for i in range(0, len(cities), CHUNK_SIZE):
            chunk = cities[i : i + CHUNK_SIZE]
            for c in self._session.execute(select(City).where(City.name.in_(chunk))).scalars():
                city_map[c.name] = c.id

        for s in stores:
            city_id = city_map.get(s.city)
            place = Place(
                address=s.address,
                city_id=city_id,
                latitude=s.latitude,
                longitude=s.longitude,
            )
            self._session.add(place)
            self._session.flush()

            pos = self._session.execute(
                select(PointOfSale).where(PointOfSale.code == s.id)
            ).scalar_one_or_none()

            flag_id = flag_map.get(s.chain_name)
            biz_id = biz_map.get(s.chain_name)
            branch_id = branch_map.get(s.store_name)

            if pos:
                pos.flag_id = flag_id
                pos.business_id = biz_id
                pos.branch_id = branch_id
                pos.place_id = place.id
            else:
                pos = PointOfSale(
                    code=s.id,
                    flag_id=flag_id,
                    business_id=biz_id,
                    branch_id=branch_id,
                    place_id=place.id,
                )
                self._session.add(pos)

        self._session.commit()

    def search_products(self, query: str, limit: int = 50) -> List[Product]:
        pattern = f"%{query}%"
        stmt = (
            select(ArticleCard)
            .join(ArticleCode, ArticleCard.code_id == ArticleCode.id)
            .outerjoin(ArticleDescription, ArticleCard.description_id == ArticleDescription.id)
            .outerjoin(ArticleBrand, ArticleCard.brand_id == ArticleBrand.id)
            .outerjoin(ArticleCategory, ArticleCard.category_id == ArticleCategory.id)
            .where(
                (ArticleDescription.description.ilike(pattern))
                | (ArticleBrand.brand.ilike(pattern))
                | (ArticleCode.ean == query)
            )
            .limit(limit)
        )
        results = self._session.execute(stmt).scalars().all()
        return [
            Product(
                ean=card.code.ean,
                name=card.description.description if card.description else "",
                brand=card.brand.brand if card.brand else None,
                category=card.category.category if card.category else None,
            )
            for card in results
        ]

    def get_product_by_ean(self, ean: str) -> Optional[Product]:
        stmt = (
            select(ArticleCard)
            .join(ArticleCode, ArticleCard.code_id == ArticleCode.id)
            .outerjoin(ArticleDescription, ArticleCard.description_id == ArticleDescription.id)
            .outerjoin(ArticleBrand, ArticleCard.brand_id == ArticleBrand.id)
            .outerjoin(ArticleCategory, ArticleCard.category_id == ArticleCategory.id)
            .where(ArticleCode.ean == ean)
        )
        card = self._session.execute(stmt).scalar_one_or_none()
        if not card:
            return None
        return Product(
            ean=card.code.ean,
            name=card.description.description if card.description else "",
            brand=card.brand.brand if card.brand else None,
            category=card.category.category if card.category else None,
        )

    def get_stores_by_city(self, city: str) -> List[Store]:
        stmt = (
            select(PointOfSale)
            .join(Place, PointOfSale.place_id == Place.id)
            .join(City, Place.city_id == City.id)
            .outerjoin(Flag, PointOfSale.flag_id == Flag.id)
            .outerjoin(Branch, PointOfSale.branch_id == Branch.id)
            .where(City.name == city)
        )
        results = self._session.execute(stmt).scalars().all()
        stores = []
        for pos in results:
            chain_name = pos.flag.flag if pos.flag else ""
            store_name = pos.branch.branch if pos.branch else ""
            addr = pos.place.address if pos.place else None
            lat = pos.place.latitude if pos.place else None
            lon = pos.place.longitude if pos.place else None
            stores.append(
                Store(
                    id=pos.code,
                    chain_name=chain_name,
                    store_name=store_name,
                    city=city,
                    address=addr,
                    latitude=lat,
                    longitude=lon,
                )
            )
        return stores


class SqlAlchemyPriceRepository(PriceRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for prices and metrics."""

    def __init__(self, session: Session):
        self._session = session

    def save_prices(self, prices: List[DailyPrice], batch_size: int = 10_000) -> None:
        if not prices:
            return

        # 1. Ensure Timestamp records exist
        distinct_dates = {p.price_date for p in prices}
        timestamp_map = {}
        for p_date in distinct_dates:
            dt = datetime.combine(p_date, time.min)
            ts = self._session.execute(
                select(Timestamp).where(func.date(Timestamp.timestamp) == p_date.isoformat())
            ).scalar_one_or_none()
            if not ts:
                ts = Timestamp(timestamp=dt)
                self._session.add(ts)
                self._session.flush()
            timestamp_map[p_date] = ts.id

        # 2. Ensure ArticleCodes exist in chunked batches
        distinct_eans: List[str] = list({p.ean for p in prices})
        for i in range(0, len(distinct_eans), CHUNK_SIZE):
            chunk_eans = [{"ean": e} for e in distinct_eans[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(ArticleCode).values(chunk_eans).on_conflict_do_nothing(index_elements=["ean"])
            self._session.execute(stmt)
        self._session.flush()

        code_map: Dict[str, int] = {}
        for i in range(0, len(distinct_eans), CHUNK_SIZE):
            chunk = distinct_eans[i : i + CHUNK_SIZE]
            for c in self._session.execute(
                select(ArticleCode).where(ArticleCode.ean.in_(chunk))
            ).scalars():
                code_map[c.ean] = c.id

        # 3. Ensure PointOfSale records exist in chunked batches
        distinct_stores: List[str] = list({p.store_id for p in prices})
        for i in range(0, len(distinct_stores), CHUNK_SIZE):
            chunk_stores = [{"code": s} for s in distinct_stores[i : i + CHUNK_SIZE]]
            stmt = sqlite_insert(PointOfSale).values(chunk_stores).on_conflict_do_nothing(index_elements=["code"])
            self._session.execute(stmt)
        self._session.flush()

        pos_map: Dict[str, int] = {}
        for i in range(0, len(distinct_stores), CHUNK_SIZE):
            chunk = distinct_stores[i : i + CHUNK_SIZE]
            for pos in self._session.execute(
                select(PointOfSale).where(PointOfSale.code.in_(chunk))
            ).scalars():
                pos_map[pos.code] = pos.id

        # 4. Insert/Upsert Prices in chunked batches
        values = []
        for p in prices:
            ts_id = timestamp_map.get(p.price_date)
            art_id = code_map.get(p.ean)
            pos_id = pos_map.get(p.store_id)
            if ts_id and art_id and pos_id:
                values.append(
                    {
                        "amount": p.price,
                        "timestamp_id": ts_id,
                        "article_code_id": art_id,
                        "point_of_sale_id": pos_id,
                    }
                )

        eff_batch = min(batch_size, 200)
        for i in range(0, len(values), eff_batch):
            chunk = values[i : i + eff_batch]
            stmt = sqlite_insert(Price).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["timestamp_id", "point_of_sale_id", "article_code_id"],
                set_={"amount": stmt.excluded.amount},
            )
            self._session.execute(stmt)
        self._session.commit()

    def save_metrics(
        self, metrics: List[DailyProductMetrics], batch_size: int = 10_000
    ) -> None:
        if not metrics:
            return
        values = [
            {
                "date": m.metric_date,
                "ean": m.ean,
                "city": m.city,
                "min_price": m.min_price,
                "max_price": m.max_price,
                "median_price": m.median_price,
                "reference_price": m.reference_price,
                "price_dispersion": m.price_dispersion,
                "pct_change_7d": m.pct_change_7d,
                "pct_change_30d": m.pct_change_30d,
                "pct_change_90d": m.pct_change_90d,
            }
            for m in metrics
        ]
        eff_batch = min(batch_size, 80)
        for i in range(0, len(values), eff_batch):
            chunk = values[i : i + eff_batch]
            stmt = sqlite_insert(DailyProductMetricModel).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "ean", "city"],
                set_={
                    "min_price": stmt.excluded.min_price,
                    "max_price": stmt.excluded.max_price,
                    "median_price": stmt.excluded.median_price,
                    "reference_price": stmt.excluded.reference_price,
                    "price_dispersion": stmt.excluded.price_dispersion,
                    "pct_change_7d": stmt.excluded.pct_change_7d,
                    "pct_change_30d": stmt.excluded.pct_change_30d,
                    "pct_change_90d": stmt.excluded.pct_change_90d,
                },
            )
            self._session.execute(stmt)
        self._session.commit()

    def delete_prices_for_date(self, price_date: date) -> int:
        ts_ids = self._session.execute(
            select(Timestamp.id).where(func.date(Timestamp.timestamp) == price_date.isoformat())
        ).scalars().all()
        if not ts_ids:
            return 0
        stmt = delete(Price).where(Price.timestamp_id.in_(ts_ids))
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_metrics_for_date(self, metric_date: date) -> int:
        stmt = delete(DailyProductMetricModel).where(
            DailyProductMetricModel.date == metric_date
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[DailyPrice]:
        results = []
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = (
                select(Price)
                .join(PointOfSale, Price.point_of_sale_id == PointOfSale.id)
                .join(Place, PointOfSale.place_id == Place.id)
                .join(City, Place.city_id == City.id)
                .join(ArticleCode, Price.article_code_id == ArticleCode.id)
                .join(Timestamp, Price.timestamp_id == Timestamp.id)
                .where(
                    City.name == city,
                    func.date(Timestamp.timestamp) == price_date.isoformat(),
                    ArticleCode.ean.in_(chunk_eans),
                )
            )
            chunk_results = self._session.execute(stmt).scalars().all()
            results.extend(chunk_results)

        return [
            DailyPrice(
                price_date=price_date,
                ean=p.article_code.ean,
                store_id=p.point_of_sale.code,
                price=p.amount,
            )
            for p in results
        ]

    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]:
        ref_dict = {}
        for i in range(0, len(eans), CHUNK_SIZE):
            chunk_eans = eans[i : i + CHUNK_SIZE]
            stmt = select(
                DailyProductMetricModel.ean, DailyProductMetricModel.reference_price
            ).where(
                DailyProductMetricModel.city == city,
                DailyProductMetricModel.date == price_date,
                DailyProductMetricModel.ean.in_(chunk_eans),
            )
            results = self._session.execute(stmt).all()
            for ean, ref_p in results:
                if ref_p is not None:
                    ref_dict[ean] = ref_p

        return ref_dict


class SqlAlchemyUserRepository(UserRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for user accounts and shopping lists."""

    def __init__(self, session: Session):
        self._session = session

    def create_user(self, email: str, password_hash: str) -> User:
        user_model = UserModel(email=email, password_hash=password_hash)
        self._session.add(user_model)
        self._session.commit()
        self._session.refresh(user_model)
        return User(
            id=user_model.id,
            email=user_model.email,
            password_hash=user_model.password_hash,
            created_at=user_model.created_at,
        )

    def get_user_by_email(self, email: str) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.email == email)
        u = self._session.execute(stmt).scalar_one_or_none()
        if not u:
            return None
        return User(
            id=u.id,
            email=u.email,
            password_hash=u.password_hash,
            created_at=u.created_at,
        )

    def save_shopping_list(self, shopping_list: ShoppingList) -> ShoppingList:
        list_uuid = shopping_list.uuid or str(uuid.uuid4())
        list_model = ShoppingListModel(
            id=shopping_list.id if shopping_list.id else None,
            uuid=list_uuid,
            user_id=shopping_list.user_id,
            name=shopping_list.name,
            is_public=shopping_list.is_public,
        )
        for item in shopping_list.items:
            list_model.items.append(ListItemModel(ean=item.ean, quantity=item.quantity))

        merged_model = self._session.merge(list_model)
        self._session.commit()
        self._session.refresh(merged_model)

        return ShoppingList(
            id=merged_model.id,
            user_id=merged_model.user_id,
            name=merged_model.name,
            items=[
                ListItem(ean=i.ean, quantity=i.quantity) for i in merged_model.items
            ],
            created_at=merged_model.created_at,
            is_public=merged_model.is_public,
            uuid=merged_model.uuid,
        )

    def get_user_shopping_lists(self, user_id: int) -> List[ShoppingList]:
        stmt = select(ShoppingListModel).where(ShoppingListModel.user_id == user_id)
        results = self._session.execute(stmt).scalars().all()
        return [
            ShoppingList(
                id=m.id,
                user_id=m.user_id,
                name=m.name,
                items=[ListItem(ean=i.ean, quantity=i.quantity) for i in m.items],
                created_at=m.created_at,
                is_public=m.is_public,
                uuid=m.uuid,
            )
            for m in results
        ]

    def get_shopping_list_by_uuid(self, uuid_str: str) -> Optional[ShoppingList]:
        stmt = select(ShoppingListModel).where(ShoppingListModel.uuid == uuid_str)
        m = self._session.execute(stmt).scalar_one_or_none()
        if not m:
            return None
        return ShoppingList(
            id=m.id,
            user_id=m.user_id,
            name=m.name,
            items=[ListItem(ean=i.ean, quantity=i.quantity) for i in m.items],
            created_at=m.created_at,
            is_public=m.is_public,
            uuid=m.uuid,
        )

    def delete_shopping_list(self, list_id: int, user_id: int) -> bool:
        stmt = select(ShoppingListModel).where(
            ShoppingListModel.id == list_id, ShoppingListModel.user_id == user_id
        )
        m = self._session.execute(stmt).scalar_one_or_none()
        if not m:
            return False
        self._session.delete(m)
        self._session.commit()
        return True
