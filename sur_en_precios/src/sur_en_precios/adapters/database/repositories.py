from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import (
    DailyPriceModel,
    DailyProductMetricModel,
    ProductModel,
    StoreModel,
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


class SqlAlchemyCatalogRepository(CatalogRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for products and stores catalog."""

    def __init__(self, session: Session):
        self._session = session

    def save_products(self, products: List[Product]) -> None:
        for p in products:
            model = ProductModel(
                ean=p.ean, name=p.name, brand=p.brand, category=p.category
            )
            self._session.merge(model)
        self._session.commit()

    def save_stores(self, stores: List[Store]) -> None:
        for s in stores:
            model = StoreModel(
                id=s.id,
                chain_name=s.chain_name,
                store_name=s.store_name,
                city=s.city,
                address=s.address,
                latitude=s.latitude,
                longitude=s.longitude,
            )
            self._session.merge(model)
        self._session.commit()

    def search_products(self, query: str, limit: int = 50) -> List[Product]:
        pattern = f"%{query}%"
        stmt = (
            select(ProductModel)
            .where(
                (ProductModel.name.ilike(pattern))
                | (ProductModel.brand.ilike(pattern))
                | (ProductModel.ean == query)
            )
            .limit(limit)
        )
        results = self._session.execute(stmt).scalars().all()
        return [
            Product(ean=m.ean, name=m.name, brand=m.brand, category=m.category)
            for m in results
        ]

    def get_product_by_ean(self, ean: str) -> Optional[Product]:
        stmt = select(ProductModel).where(ProductModel.ean == ean)
        m = self._session.execute(stmt).scalar_one_or_none()
        if not m:
            return None
        return Product(ean=m.ean, name=m.name, brand=m.brand, category=m.category)

    def get_stores_by_city(self, city: str) -> List[Store]:
        stmt = select(StoreModel).where(StoreModel.city == city)
        results = self._session.execute(stmt).scalars().all()
        return [
            Store(
                id=m.id,
                chain_name=m.chain_name,
                store_name=m.store_name,
                city=m.city,
                address=m.address,
                latitude=m.latitude,
                longitude=m.longitude,
            )
            for m in results
        ]


class SqlAlchemyPriceRepository(PriceRepositoryPort):
    """SQLAlchemy 2.0 repository implementation for prices and metrics."""

    def __init__(self, session: Session):
        self._session = session

    def save_prices(self, prices: List[DailyPrice]) -> None:
        for p in prices:
            model = DailyPriceModel(
                date=p.price_date, ean=p.ean, store_id=p.store_id, price=p.price
            )
            self._session.merge(model)
        self._session.commit()

    def save_metrics(self, metrics: List[DailyProductMetrics]) -> None:
        for m in metrics:
            model = DailyProductMetricModel(
                date=m.metric_date,
                ean=m.ean,
                city=m.city,
                min_price=m.min_price,
                max_price=m.max_price,
                median_price=m.median_price,
                reference_price=m.reference_price,
                price_dispersion=m.price_dispersion,
                pct_change_7d=m.pct_change_7d,
                pct_change_30d=m.pct_change_30d,
                pct_change_90d=m.pct_change_90d,
            )
            self._session.merge(model)
        self._session.commit()

    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[DailyPrice]:
        stmt = (
            select(DailyPriceModel)
            .join(StoreModel, DailyPriceModel.store_id == StoreModel.id)
            .where(
                StoreModel.city == city,
                DailyPriceModel.date == price_date,
                DailyPriceModel.ean.in_(eans),
            )
        )
        results = self._session.execute(stmt).scalars().all()
        return [
            DailyPrice(price_date=m.date, ean=m.ean, store_id=m.store_id, price=m.price)
            for m in results
        ]

    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]:
        stmt = select(
            DailyProductMetricModel.ean, DailyProductMetricModel.reference_price
        ).where(
            DailyProductMetricModel.city == city,
            DailyProductMetricModel.date == price_date,
            DailyProductMetricModel.ean.in_(eans),
        )
        results = self._session.execute(stmt).all()
        return {ean: ref_p for ean, ref_p in results if ref_p is not None}


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
        list_model = ShoppingListModel(
            id=shopping_list.id if shopping_list.id else None,
            user_id=shopping_list.user_id,
            name=shopping_list.name,
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
            )
            for m in results
        ]

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
