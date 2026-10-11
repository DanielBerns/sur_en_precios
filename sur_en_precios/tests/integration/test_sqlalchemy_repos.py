from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleCode,
    PointOfSale,
    Price,
    PublicBase,
    Timestamp,
)
from sur_en_precios.adapters.database.models_user import UserBase, UserModel
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
        # Test UserModel password hash helpers
        user_model = UserModel(email="auth@test.com", password_hash="")
        user_model.set_password("secure_pass_123")
        assert user_model.check_password("secure_pass_123") is True
        assert user_model.check_password("wrong_password") is False

        repo = SqlAlchemyUserRepository(session)

        # Create User
        user = repo.create_user("test@example.com", "hashed_pass")
        assert user.id is not None
        assert user.email == "test@example.com"

        # Create Shopping List with UUID and is_public
        slist = ShoppingList(
            id=None,
            user_id=user.id,
            name="Weekly Groceries",
            items=[ListItem(ean="779001", quantity=2)],
            is_public=True,
        )
        saved_list = repo.save_shopping_list(slist)
        assert saved_list.id is not None
        assert saved_list.uuid is not None
        assert saved_list.is_public is True

        # Fetch Lists
        user_lists = repo.get_user_shopping_lists(user.id)
        assert len(user_lists) == 1
        assert user_lists[0].name == "Weekly Groceries"

        # Fetch List by UUID
        fetched_by_uuid = repo.get_shopping_list_by_uuid(saved_list.uuid)
        assert fetched_by_uuid is not None
        assert fetched_by_uuid.id == saved_list.id
        assert fetched_by_uuid.is_public is True
        assert len(fetched_by_uuid.items) == 1
        assert fetched_by_uuid.items[0].ean == "779001"


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

        # Verify underlying Hermes normalized tables
        assert session.query(ArticleCode).filter_by(ean="779001").first() is not None
        assert session.query(ArticleBrand).filter_by(brand="Freir").first() is not None
        assert session.query(ArticleCard).first() is not None
        assert session.query(PointOfSale).filter_by(code="s1").first() is not None

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

        # Verify Hermes normalized Price & Timestamp tables
        assert session.query(Timestamp).first() is not None
        assert session.query(Price).first() is not None

        # Fetch Basket Prices
        basket_prices = price_repo.get_prices_for_basket(
            "Bahía Blanca", today, ["779001"]
        )
        assert len(basket_prices) == 1
        assert basket_prices[0].price == 1250

        # Fetch Reference Prices
        ref_prices = price_repo.get_reference_prices("Bahía Blanca", today, ["779001"])
        assert ref_prices.get("779001") == 1200
