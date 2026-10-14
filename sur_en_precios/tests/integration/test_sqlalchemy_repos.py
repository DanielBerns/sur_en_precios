from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.domain.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleCategory,
    ArticleDescription,
    ArticleMetric,
    ArticleNumber,
    Branch,
    City,
    Flag,
    Place,
    Price,
    PublicBase,
    State,
    Store,
    Timestamp,
)
from sur_en_precios.domain.models_user import (
    Basket,
    BasketItem,
    User,
    UserBase,
)


def test_user_repository_crud() -> None:
    engine = create_engine("sqlite:///:memory:")
    UserBase.metadata.create_all(engine)

    with Session(engine) as session:
        # Test User password hash helpers
        user_entity = User(email="auth@test.com", password_hash="")
        user_entity.set_password("secure_pass_123")
        assert user_entity.check_password("secure_pass_123") is True
        assert user_entity.check_password("wrong_password") is False

        repo = SqlAlchemyUserRepository(session)

        # Create User
        user = repo.create_user("test@example.com", "hashed_pass")
        assert user.id is not None
        assert user.email == "test@example.com"

        # Get User by email
        fetched_user = repo.get_user_by_email("test@example.com")
        assert fetched_user is not None
        assert fetched_user.id == user.id

        assert repo.get_user_by_email("nonexistent@example.com") is None

        # Create Basket with UUID and is_public
        basket = Basket(
            id=None,
            user_id=user.id,
            name="Weekly Groceries",
            items=[BasketItem(ean="779001", quantity=2)],
            is_public=True,
        )
        saved_basket = repo.save_basket(basket)
        assert saved_basket.id is not None
        assert saved_basket.uuid is not None
        assert saved_basket.is_public is True

        # Fetch Baskets
        user_baskets = repo.get_user_baskets(user.id)
        assert len(user_baskets) == 1
        assert user_baskets[0].name == "Weekly Groceries"
        assert len(user_baskets[0].items) == 1
        assert user_baskets[0].items[0].ean == "779001"
        assert user_baskets[0].items[0].quantity == 2

        # Fetch Basket by UUID
        fetched_by_uuid = repo.get_basket_by_uuid(saved_basket.uuid)
        assert fetched_by_uuid is not None
        assert fetched_by_uuid.id == saved_basket.id
        assert fetched_by_uuid.is_public is True
        assert len(fetched_by_uuid.items) == 1
        assert fetched_by_uuid.items[0].ean == "779001"

        # Delete Basket
        deleted = repo.delete_basket(saved_basket.id, user.id)
        assert deleted is True
        assert repo.get_basket_by_uuid(saved_basket.uuid) is None
        assert repo.delete_basket(999, user.id) is False


def test_catalog_and_price_repositories() -> None:
    engine = create_engine("sqlite:///:memory:")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        price_repo = SqlAlchemyPriceRepository(session)

        # Build ArticleCard and Store
        card = ArticleCard(
            article_number=ArticleNumber(ean="779001"),
            description=ArticleDescription(content="Aceite de Oliva Aerosol 120ml"),
            brand=ArticleBrand(brand="Freir"),
            category=ArticleCategory(content="Aceites"),
        )
        store = Store(
            code="s1",
            flag=Flag(flag="Carrefour"),
            branch=Branch(branch="Central"),
            place=Place(
                address="Av. Colon 100",
                latitude=-38.71,
                longitude=-62.26,
                city=City(
                    name="Bahía Blanca",
                    state=State(code="AR-B", name="Buenos Aires"),
                ),
            ),
        )

        cat_repo.save_articles([card])
        cat_repo.save_stores([store])

        # Verify underlying normalized tables
        assert (
            session.scalar(select(ArticleNumber).where(ArticleNumber.ean == "779001"))
            is not None
        )
        assert (
            session.scalar(select(ArticleBrand).where(ArticleBrand.brand == "Freir"))
            is not None
        )
        assert (
            session.scalar(
                select(ArticleCategory).where(ArticleCategory.content == "Aceites")
            )
            is not None
        )
        assert (
            session.scalar(
                select(ArticleDescription).where(
                    ArticleDescription.content == "Aceite de Oliva Aerosol 120ml"
                )
            )
            is not None
        )
        assert session.scalar(select(ArticleCard)) is not None
        saved_store = session.scalar(select(Store).where(Store.code == "s1"))
        assert saved_store is not None
        assert saved_store.place is not None
        assert saved_store.place.address == "Av. Colon 100"
        assert saved_store.place.latitude == -38.71
        assert saved_store.place.longitude == -62.26
        assert (
            session.scalar(select(City).where(City.name == "Bahía Blanca")) is not None
        )

        # Search Articles
        found = cat_repo.search_articles("Freir")
        assert len(found) == 1
        assert found[0].ean == "779001"
        assert found[0].name == "Aceite de Oliva Aerosol 120ml"

        # Search by EAN
        found_by_ean = cat_repo.search_articles("779001")
        assert len(found_by_ean) == 1
        assert found_by_ean[0].ean == "779001"

        # Get article by EAN
        single_card = cat_repo.get_article_by_ean("779001")
        assert single_card is not None
        assert single_card.ean == "779001"
        assert single_card.name == "Aceite de Oliva Aerosol 120ml"

        # Get stores by city
        city_stores = cat_repo.get_stores_by_city("Bahía Blanca")
        assert len(city_stores) == 1
        assert city_stores[0].code == "s1"
        assert city_stores[0].chain_name == "Carrefour"
        assert city_stores[0].branch_name == "Central"
        assert city_stores[0].city == "Bahía Blanca"

        # Save Prices & Metrics
        today = date(2026, 10, 9)
        price_entry = Price(
            amount=1250,
            timestamp=Timestamp(value=today),
            store=store,
            article_number=ArticleNumber(ean="779001"),
        )
        metric_entry = ArticleMetric(
            timestamp=Timestamp(value=today),
            article_number=ArticleNumber(ean="779001"),
            city=City(
                name="Bahía Blanca", state=State(code="AR-B", name="Buenos Aires")
            ),
            min_price=1200,
            max_price=1300,
            reference_price=1250,
            price_dispersion=0.04,
        )

        price_repo.save_prices([price_entry])
        price_repo.save_metrics([metric_entry])

        # Verify Price & Timestamp & Metric tables
        assert (
            session.scalar(select(Timestamp).where(Timestamp.value == today))
            is not None
        )
        assert session.scalar(select(Price)) is not None
        assert session.scalar(select(ArticleMetric)) is not None

        # Fetch Basket Prices
        basket_prices = price_repo.get_prices_for_basket(
            "Bahía Blanca", today, ["779001"]
        )
        assert len(basket_prices) == 1
        assert basket_prices[0].price == 1250
        assert basket_prices[0].ean == "779001"
        assert basket_prices[0].store_code == "s1"

        # Fetch Reference Prices
        ref_prices = price_repo.get_reference_prices("Bahía Blanca", today, ["779001"])
        assert ref_prices.get("779001") == 1250

        # Delete Prices and Metrics for date
        deleted_metrics = price_repo.delete_metrics_for_date(today)
        assert deleted_metrics == 1
        ref_after = price_repo.get_reference_prices("Bahía Blanca", today, ["779001"])
        assert "779001" not in ref_after

        deleted_prices = price_repo.delete_prices_for_date(today)
        assert deleted_prices == 1
        prices_after = price_repo.get_prices_for_basket(
            "Bahía Blanca", today, ["779001"]
        )
        assert len(prices_after) == 0


def test_search_articles_modes() -> None:
    engine = create_engine("sqlite:///:memory:")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)

        card1 = ArticleCard(
            article_number=ArticleNumber(ean="779001"),
            description=ArticleDescription(content="Leche Entera Fortificada 1L"),
            brand=ArticleBrand(brand="La Serenísima"),
            category=ArticleCategory(content="Lácteos"),
        )
        card2 = ArticleCard(
            article_number=ArticleNumber(ean="779002"),
            description=ArticleDescription(content="Pan Lactal Blanco 500g"),
            brand=ArticleBrand(brand="Bimbo"),
            category=ArticleCategory(content="Almacén"),
        )
        card3 = ArticleCard(
            article_number=ArticleNumber(ean="779003"),
            description=ArticleDescription(content="Galletitas de Chocolate"),
            brand=ArticleBrand(brand="Chocolinas"),
            category=ArticleCategory(content="Almacén"),
        )

        cat_repo.save_articles([card1, card2, card3])

        # Exact EAN search
        res_ean = cat_repo.search_articles("779001", mode="exact")
        assert len(res_ean) == 1
        assert res_ean[0].ean == "779001"

        # Exact brand search
        res_brand = cat_repo.search_articles("Bimbo", mode="exact")
        assert len(res_brand) == 1
        assert res_brand[0].ean == "779002"

        # Fuzzy search with typo in brand: "serenicima" -> "La Serenísima"
        res_fuzzy_brand = cat_repo.search_articles("serenicima", mode="fuzzy")
        assert len(res_fuzzy_brand) >= 1
        assert res_fuzzy_brand[0].ean == "779001"

        # Fuzzy search with description typo: "leceh" -> "Leche Entera"
        res_fuzzy_desc = cat_repo.search_articles("leceh", mode="fuzzy")
        assert len(res_fuzzy_desc) >= 1
        assert res_fuzzy_desc[0].ean == "779001"

        # Fuzzy search by category
        res_cat = cat_repo.search_articles("Lacteos", mode="fuzzy")
        assert len(res_cat) >= 1
        assert res_cat[0].ean == "779001"


def test_user_repository_basket_item_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    UserBase.metadata.create_all(engine)

    with Session(engine) as session:
        user_repo = SqlAlchemyUserRepository(session)
        user = user_repo.create_user("custom@test.com", "hash")

        basket = Basket(
            id=None,
            user_id=user.id,
            name="Canasta Personalizada",
            is_public=True,
            items=[
                BasketItem(
                    ean="779001",
                    quantity=3,
                    selected=True,
                    numerator=2,
                    denominator=5,
                ),
                BasketItem(
                    ean="779002",
                    quantity=1,
                    selected=False,
                    numerator=1,
                    denominator=1,
                ),
            ],
        )

        saved = user_repo.save_basket(basket)
        assert saved.id is not None
        assert saved.is_public is True

        fetched = user_repo.get_basket_by_uuid(saved.uuid)
        assert fetched is not None
        assert len(fetched.items) == 2

        item1 = next(it for it in fetched.items if it.ean == "779001")
        assert item1.quantity == 3
        assert item1.selected is True
        assert item1.numerator == 2
        assert item1.denominator == 5
        assert item1.factor == 0.4

        item2 = next(it for it in fetched.items if it.ean == "779002")
        assert item2.quantity == 1
        assert item2.selected is False
        assert item2.numerator == 1
        assert item2.denominator == 1
