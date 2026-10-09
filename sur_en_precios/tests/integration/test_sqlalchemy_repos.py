from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import PublicBase
from sur_en_precios.adapters.database.models_user import UserBase
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.domain.models import (
    DailyPrice,
    DailyProductMetrics,
    ListItem,
    Product,
    ShoppingList,
    Store,
)


def test_user_repository_crud() -> None:
    engine = create_engine("sqlite:///:memory:")
    UserBase.metadata.create_all(engine)

    with Session(engine) as session:
        repo = SqlAlchemyUserRepository(session)

        # Create User
        user = repo.create_user("test@example.com", "hashed_pass")
        assert user.id is not None
        assert user.email == "test@example.com"

        # Create Shopping List
        slist = ShoppingList(
            id=None,
            user_id=user.id,
            name="Weekly Groceries",
            items=[ListItem(ean="779001", quantity=2)],
        )
        saved_list = repo.save_shopping_list(slist)
        assert saved_list.id is not None

        # Fetch Lists
        user_lists = repo.get_user_shopping_lists(user.id)
        assert len(user_lists) == 1
        assert user_lists[0].name == "Weekly Groceries"


def test_catalog_and_price_repositories() -> None:
    engine = create_engine("sqlite:///:memory:")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        price_repo = SqlAlchemyPriceRepository(session)

        # Save Catalog
        prod = Product(
            ean="779001",
            name="Aceite de Oliva Aerosol 120ml",
            brand="Freir",
            category="Aceites",
        )
        store = Store(
            id="s1", chain_name="Carrefour", store_name="Central", city="Bahía Blanca"
        )

        cat_repo.save_products([prod])
        cat_repo.save_stores([store])

        # Search Products
        found = cat_repo.search_products("Freir")
        assert len(found) == 1
        assert found[0].ean == "779001"

        # Save Prices & Metrics
        today = date(2026, 10, 9)
        dprice = DailyPrice(price_date=today, ean="779001", store_id="s1", price=1250)
        dmetric = DailyProductMetrics(
            metric_date=today, ean="779001", city="Bahía Blanca", reference_price=1200
        )

        price_repo.save_prices([dprice])
        price_repo.save_metrics([dmetric])

        # Fetch Basket Prices
        basket_prices = price_repo.get_prices_for_basket(
            "Bahía Blanca", today, ["779001"]
        )
        assert len(basket_prices) == 1
        assert basket_prices[0].price == 1250

        # Fetch Reference Prices
        ref_prices = price_repo.get_reference_prices("Bahía Blanca", today, ["779001"])
        assert ref_prices.get("779001") == 1200
