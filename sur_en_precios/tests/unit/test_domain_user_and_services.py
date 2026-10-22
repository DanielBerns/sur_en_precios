"""Comprehensive tests for refactored models_user.py, ports.py, and services.py."""

from datetime import date
from typing import List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.domain.models import (
    BasketOptimizationResult,
    ItemBestPrice,
    StoreBasketTotal,
    StoreItemPrice,
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
from sur_en_precios.domain.ports import (
    UserRepositoryPort,
)
from sur_en_precios.domain.services import (
    BasketOptimizerService,
    BasketPriceReportService,
    BasketYamlService,
    PriceMetricsCalculator,
    YamlValidationError,
    fuzzy_similarity_ratio,
    levenshtein_distance,
)


class TestModelsUser:
    """Tests for UserBase ORM models in models_user.py."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine("sqlite:///:memory:")
        UserBase.metadata.create_all(engine)
        with Session(engine) as session:
            yield session

    def test_table_names(self):
        assert User.__tablename__ == "users"
        assert Basket.__tablename__ == "baskets"
        assert BasketItem.__tablename__ == "basket_items"

    def test_user_creation_and_passwords(self, db_session: Session):
        user = User(email="test@example.com", password_hash="")
        user.set_password("secret_123")
        assert user.check_password("secret_123") is True
        assert user.check_password("wrong_password") is False
        assert repr(user) == "<User test@example.com>"

        db_session.add(user)
        db_session.commit()
        assert user.id is not None

    def test_basket_and_items_relationships(self, db_session: Session):
        user = User(email="shopper@test.com", password_hash="dummy")
        db_session.add(user)
        db_session.commit()

        basket = Basket(name="Weekly Groceries", user=user)
        item1 = BasketItem(ean="779001", quantity=2, basket=basket)
        item2 = BasketItem(ean="779002", quantity=1, basket=basket)

        db_session.add(basket)
        db_session.commit()

        assert repr(basket).startswith("<Basket Weekly Groceries")
        assert repr(item1) == "<BasketItem 779001 x2>"
        assert repr(item2) == "<BasketItem 779002 x1>"

        # Verify bidirectional navigation
        assert basket.user == user
        assert user.baskets == [basket]
        assert len(basket.items) == 2
        assert item1.basket == basket

    def test_cascade_delete(self, db_session: Session):
        user = User(email="delete_me@test.com", password_hash="dummy")
        basket = Basket(name="Temp Basket", user=user)
        item = BasketItem(ean="779001", quantity=1, basket=basket)

        db_session.add(user)
        db_session.commit()

        user_id = user.id
        basket_id = basket.id
        item_id = item.id

        db_session.delete(user)
        db_session.commit()

        assert db_session.get(User, user_id) is None
        assert db_session.get(Basket, basket_id) is None
        assert db_session.get(BasketItem, item_id) is None


class TestPorts:
    """Tests for abstract ports definitions in ports.py."""

    def test_user_repository_port_abstract(self):
        with pytest.raises(TypeError):
            UserRepositoryPort()  # type: ignore[abstract]

    def test_concrete_user_repository_port(self):
        class DummyUserRepo(UserRepositoryPort):
            def create_user(
                self, username: str, password_hash: str, is_admin: bool = False
            ) -> User:
                return User(
                    username=username, password_hash=password_hash, is_admin=is_admin
                )

            def get_user_by_username(self, username: str) -> Optional[User]:
                return None

            def save_basket(self, basket: Basket) -> Basket:
                return basket

            def get_user_baskets(self, user_id: int) -> List[Basket]:
                return []

            def get_basket_by_uuid(self, uuid_str: str) -> Optional[Basket]:
                return None

            def delete_basket(self, basket_id: int, user_id: int) -> bool:
                return True

        repo = DummyUserRepo()
        user = repo.create_user("testuser", "h")
        assert user.username == "testuser"
        basket = Basket(name="Test", user=user)
        assert repo.save_basket(basket) == basket
        assert repo.delete_basket(1, 1) is True


class TestPriceMetricsCalculator:
    """Tests for PriceMetricsCalculator in services.py."""

    def test_empty_prices(self):
        metric = PriceMetricsCalculator.calculate_metrics(
            metric_date=date(2026, 10, 11),
            ean="779001",
            city="Bahía Blanca",
            prices=[],
        )
        assert isinstance(metric, ArticleMetric)
        assert metric.date == date(2026, 10, 11)
        assert metric.ean == "779001"
        assert metric.city_name == "Bahía Blanca"
        assert metric.min_price is None
        assert metric.max_price is None
        assert metric.reference_price is None
        assert metric.price_dispersion is None

    def test_single_price(self):
        metric = PriceMetricsCalculator.calculate_metrics(
            metric_date=date(2026, 10, 11),
            ean="779001",
            city="Bahía Blanca",
            prices=[500],
        )
        assert metric.min_price == 500
        assert metric.max_price == 500
        assert metric.reference_price == 500
        assert metric.price_dispersion is None

    def test_multiple_prices(self):
        metric = PriceMetricsCalculator.calculate_metrics(
            metric_date=date(2026, 10, 11),
            ean="779001",
            city="Bahía Blanca",
            prices=[100, 200, 400],
        )
        assert metric.min_price == 100
        assert metric.max_price == 400
        assert metric.reference_price == 200
        assert metric.price_dispersion is not None
        assert metric.price_dispersion > 0


class TestBasketOptimizerService:
    """Tests for BasketOptimizerService in services.py using models_public entities."""

    @pytest.fixture
    def public_session(self):
        engine = create_engine("sqlite:///:memory:")
        PublicBase.metadata.create_all(engine)
        with Session(engine) as session:
            yield session

    def test_optimize_basket_with_public_models(self, public_session: Session):
        today = date(2026, 10, 11)
        ts = Timestamp(value=today)

        state = State(code="AR-B", name="Buenos Aires")
        city = City(name="Bahía Blanca", state=state)
        place1 = Place(address="Calle 1", city=city)
        place2 = Place(address="Calle 2", city=city)

        flag1 = Flag(flag="Carrefour")
        flag2 = Flag(flag="Vea")
        branch1 = Branch(branch="Sucursal Centro")
        branch2 = Branch(branch="Sucursal Shopping")

        store1 = Store(code="S001", flag=flag1, branch=branch1, place=place1)
        store2 = Store(code="S002", flag=flag2, branch=branch2, place=place2)

        ean1 = ArticleNumber(ean="779001")
        ean2 = ArticleNumber(ean="779002")

        desc1 = ArticleDescription(content="Leche Entera 1L")
        desc2 = ArticleDescription(content="Pan Lactal 500g")

        card1 = ArticleCard(article_number=ean1, description=desc1)
        card2 = ArticleCard(article_number=ean2, description=desc2)

        public_session.add_all([store1, store2, card1, card2])
        public_session.commit()

        # Store 1 prices: Leche=100, Pan=200 -> Total = 300
        # Store 2 prices: Leche=150, Pan=120 -> Total = 270 (cheapest single store)
        p1 = Price(amount=100, timestamp=ts, store=store1, article_number=ean1)
        p2 = Price(amount=200, timestamp=ts, store=store1, article_number=ean2)
        p3 = Price(amount=150, timestamp=ts, store=store2, article_number=ean1)
        p4 = Price(amount=120, timestamp=ts, store=store2, article_number=ean2)

        public_session.add_all([p1, p2, p3, p4])
        public_session.commit()

        requested_items = [
            BasketItem(basket_id=1, ean="779001", quantity=1),
            BasketItem(basket_id=1, ean="779002", quantity=1),
        ]

        products_map = {"779001": card1, "779002": card2}
        stores = [store1, store2]
        prices = [p1, p2, p3, p4]
        ref_prices = {"779001": 122, "779002": 155}

        result = BasketOptimizerService.optimize_basket(
            city="Bahía Blanca",
            calc_date=today,
            requested_items=requested_items,
            products_map=products_map,
            stores=stores,
            prices=prices,
            reference_prices=ref_prices,
        )

        assert isinstance(result, BasketOptimizationResult)
        assert result.best_single_store is not None
        assert result.best_single_store.store == store2
        assert result.best_single_store.total_price == 270
        assert len(result.complete_stores) == 2

        # Item-by-item optimal: Leche from S001 (100), Pan from S002 (120)
        assert len(result.item_by_item_optimal) == 2
        leche_opt = next(
            o for o in result.item_by_item_optimal if o.product.ean == "779001"
        )
        pan_opt = next(
            o for o in result.item_by_item_optimal if o.product.ean == "779002"
        )
        assert leche_opt.cheapest_store == store1
        assert leche_opt.price == 100
        assert pan_opt.cheapest_store == store2
        assert pan_opt.price == 120

    def test_optimize_basket_fallback_article_card(self):
        today = date(2026, 10, 11)
        store = Store(code="S001")
        price = Price(
            amount=100,
            store_id=1,
            store=store,
            article_number=ArticleNumber(ean="999001"),
        )
        store.id = 1

        requested_items = [BasketItem(basket_id=1, ean="999001", quantity=1)]

        result = BasketOptimizerService.optimize_basket(
            city="General",
            calc_date=today,
            requested_items=requested_items,
            products_map={},  # Empty products map to test fallback
            stores=[store],
            prices=[price],
            reference_prices={},
        )

        assert len(result.item_by_item_optimal) == 1
        opt = result.item_by_item_optimal[0]
        assert opt.product.ean == "999001"
        assert opt.product.name == "Producto 999001"
        assert opt.price == 100

    def test_optimize_basket_with_selected_and_factor(self):
        today = date(2026, 10, 11)
        store = Store(code="S001")
        price1 = Price(
            amount=1000, store=store, article_number=ArticleNumber(ean="779001")
        )
        price2 = Price(
            amount=2000, store=store, article_number=ArticleNumber(ean="779002")
        )
        price3 = Price(
            amount=5000, store=store, article_number=ArticleNumber(ean="779003")
        )

        # item1: price=1000, qty=2, num=1, den=2 -> effective price = 1000 * 2 * (1/2) = 1000
        item1 = BasketItem(
            ean="779001", quantity=2, selected=True, numerator=1, denominator=2
        )
        # item2: price=2000, qty=1, num=3, den=4 -> effective price = round(2000 * 1 * (3/4)) = 1500
        item2 = BasketItem(
            ean="779002", quantity=1, selected=True, numerator=3, denominator=4
        )
        # item3: selected=False -> excluded completely!
        item3 = BasketItem(
            ean="779003", quantity=1, selected=False, numerator=1, denominator=1
        )

        result = BasketOptimizerService.optimize_basket(
            city="General",
            calc_date=today,
            requested_items=[item1, item2, item3],
            products_map={},
            stores=[store],
            prices=[price1, price2, price3],
            reference_prices={},
        )

        assert result.best_single_store is not None
        # Total should be 1000 + 1500 = 2500 (item3 excluded)
        assert result.best_single_store.total_price == 2500
        assert result.best_single_store.matched_items_count == 2
        assert result.best_single_store.requested_items_count == 2
        # Optimal item by item should only have active items
        assert len(result.item_by_item_optimal) == 2


class TestLevenshteinAndFuzzy:
    """Tests for Levenshtein distance and fuzzy similarity metrics."""

    def test_levenshtein_distance(self):
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("leche", "leche") == 0
        assert levenshtein_distance("leche", "leceh") == 2
        assert levenshtein_distance("leche", "") == 5
        assert levenshtein_distance("", "pan") == 3
        assert levenshtein_distance("serenisima", "serenicima") == 1

    def test_fuzzy_similarity_ratio(self):
        assert fuzzy_similarity_ratio("leche", "leche") == 1.0
        assert fuzzy_similarity_ratio("leche", "Leche Entera") >= 0.7
        # Typo match
        typo_score = fuzzy_similarity_ratio("serenicima", "serenisima")
        assert typo_score >= 0.8
        # Unrelated
        assert fuzzy_similarity_ratio("arroz", "detergente") < 0.4


class TestBasketYamlService:
    """Tests for YAML export, import, and extensive validation."""

    def test_yaml_export_and_import_valid(self):
        user = User(email="test_yaml@example.com", password_hash="dummy")
        basket = Basket(
            name="Canasta Mensual",
            is_public=True,
            user=user,
            items=[
                BasketItem(
                    ean="779001", quantity=3, selected=True, numerator=1, denominator=1
                ),
                BasketItem(
                    ean="779002", quantity=1, selected=False, numerator=2, denominator=3
                ),
            ],
        )

        card1 = ArticleCard(
            article_number=ArticleNumber(ean="779001"),
            description=ArticleDescription(content="Aceite 1L"),
            brand=ArticleBrand(brand="Marolio"),
            category=ArticleCategory(content="Almacen"),
        )
        metadata = {"779001": card1}

        yaml_text = BasketYamlService.export_to_yaml(basket, articles_metadata=metadata)
        assert "name: Canasta Mensual" in yaml_text
        assert "is_public: true" in yaml_text
        assert (
            "ean: '779001'" in yaml_text
            or 'ean: "779001"' in yaml_text
            or "ean: 779001" in yaml_text
        )
        assert "Marolio" in yaml_text
        assert "numerator: 2" in yaml_text
        assert "denominator: 3" in yaml_text

        # Re-import valid YAML
        parsed = BasketYamlService.import_from_yaml(
            yaml_text, catalog_eans={"779001", "779002"}
        )
        assert parsed.name == "Canasta Mensual"
        assert parsed.is_public is True
        assert len(parsed.items) == 2
        assert parsed.items[0].ean == "779001"
        assert parsed.items[0].quantity == 3
        assert parsed.items[0].selected is True
        assert parsed.items[0].numerator == 1
        assert parsed.items[0].denominator == 1
        assert parsed.items[1].ean == "779002"
        assert parsed.items[1].quantity == 1
        assert parsed.items[1].selected is False
        assert parsed.items[1].numerator == 2
        assert parsed.items[1].denominator == 3
        assert len(parsed.warnings) == 0

    def test_yaml_validation_errors(self):
        # 1. Empty content
        with pytest.raises(YamlValidationError, match="vacío"):
            BasketYamlService.import_from_yaml("")

        # 2. Syntax error
        with pytest.raises(YamlValidationError, match="sintaxis"):
            BasketYamlService.import_from_yaml("basket:\n  name: [unclosed")

        # 3. Non-dictionary root
        with pytest.raises(YamlValidationError, match="Estructura inválida"):
            BasketYamlService.import_from_yaml("- a list instead")

        # 4. Missing basket key
        with pytest.raises(
            YamlValidationError, match="Falta la sección principal 'basket'"
        ):
            BasketYamlService.import_from_yaml("other: test")

        # 5. Missing name
        with pytest.raises(YamlValidationError, match="nombre de la canasta"):
            BasketYamlService.import_from_yaml(
                "basket:\n  name: ''\n  items: [{ean: '779001'}]"
            )

        # 6. Name too long
        long_name = "x" * 125
        with pytest.raises(YamlValidationError, match="120 caracteres"):
            BasketYamlService.import_from_yaml(
                f"basket:\n  name: '{long_name}'\n  items: [{{ean: '779001'}}]"
            )

        # 7. Missing items
        with pytest.raises(YamlValidationError, match="lista no vacía"):
            BasketYamlService.import_from_yaml("basket:\n  name: 'Test'\n  items: []")

        # 8. Invalid EAN
        with pytest.raises(YamlValidationError, match="EAN inválido"):
            BasketYamlService.import_from_yaml(
                "basket:\n  name: 'Test'\n  items: [{ean: 'abc123'}]"
            )

        # 9. Invalid quantity
        with pytest.raises(YamlValidationError, match="cantidad inválida"):
            BasketYamlService.import_from_yaml(
                "basket:\n  name: 'Test'\n  items: [{ean: '779001', quantity: 0}]"
            )

        # 10. Invalid numerator
        with pytest.raises(YamlValidationError, match="numerator"):
            BasketYamlService.import_from_yaml(
                "basket:\n  name: 'Test'\n  items: [{ean: '779001', numerator: -1}]"
            )

        # 11. Zero denominator (must fail fast!)
        with pytest.raises(YamlValidationError, match="denominator"):
            BasketYamlService.import_from_yaml(
                "basket:\n  name: 'Test'\n  items: [{ean: '779001', denominator: 0}]"
            )

    def test_yaml_duplicates_and_catalog_warnings(self):
        yaml_content = """
basket:
  name: "Canasta con Duplicados"
  items:
    - ean: "779001"
      quantity: 2
    - ean: "779001"
      quantity: 3
    - ean: "888001"
      quantity: 1
"""
        parsed = BasketYamlService.import_from_yaml(
            yaml_content, catalog_eans={"779001"}
        )
        # 779001 consolidated: 2 + 3 = 5
        assert len(parsed.items) == 2
        item1 = next(it for it in parsed.items if it.ean == "779001")
        assert item1.quantity == 5
        # Warnings for duplicate and missing catalog ean 888001
        assert any("duplicado" in w for w in parsed.warnings)
        assert any("no se encuentra en el catálogo" in w for w in parsed.warnings)


class TestBasketPriceReportService:
    """Tests for JSON price report generation and serialization."""

    def test_basket_price_report_json_generation(self):
        # 1. Setup mock models
        store1 = Store(
            code="S001",
            brand_name="Supermercado A",
            branch_name="Centro",
            city="Comodoro Rivadavia",
            address="Av. San Martín 100",
        )
        store2 = Store(
            code="S002",
            brand_name="Supermercado B",
            branch_name="Norte",
            city="Comodoro Rivadavia",
            address="Av. Rivadavia 200",
        )

        card1 = ArticleCard(
            ean="779001",
            name="Leche Entera 1L",
            brand_name="La Serenísima",
            package="1 L",
            package_amount=1.0,
            package_unit="L",
        )
        card2 = ArticleCard(
            ean="779002",
            name="Pan Lactal 500g",
            brand_name="Bimbo",
            package="500 g",
            package_amount=500.0,
            package_unit="g",
        )

        item1 = BasketItem(
            ean="779001", quantity=2, selected=True, numerator=1, denominator=1
        )
        item2 = BasketItem(
            ean="779002", quantity=1, selected=True, numerator=1, denominator=2
        )

        basket = Basket(
            id=10,
            name="Canasta Test",
            uuid="11111111-2222-3333-4444-555555555555",
            is_public=True,
            items=[item1, item2],
        )

        best_item1 = ItemBestPrice(
            product=card1,
            cheapest_store=store1,
            price=1000,
            unit_price=1000.0,
            unit="L",
            min_price=1000,
            reference_price=1100,
            max_price=1200,
            price_dispersion=0.09,
            quantity=2,
            numerator=1,
            denominator=1,
        )
        best_item2 = ItemBestPrice(
            product=card2,
            cheapest_store=store2,
            price=800,
            unit_price=1600.0,
            unit="kg",
            min_price=800,
            reference_price=900,
            max_price=1000,
            price_dispersion=0.11,
            quantity=1,
            numerator=1,
            denominator=2,
        )

        single_store_total = StoreBasketTotal(
            store=store1,
            total_price=3000,
            matched_items_count=2,
            requested_items_count=2,
            is_complete=True,
            item_prices={
                "779001": StoreItemPrice(ean="779001", price=1000, is_lowest=True),
                "779002": StoreItemPrice(ean="779002", price=1000, is_lowest=False),
            },
        )

        store2_total = StoreBasketTotal(
            store=store2,
            total_price=2600,
            matched_items_count=2,
            requested_items_count=2,
            is_complete=True,
            item_prices={
                "779001": StoreItemPrice(ean="779001", price=1200, is_lowest=False),
                "779002": StoreItemPrice(ean="779002", price=800, is_lowest=True),
            },
        )

        opt_result = BasketOptimizationResult(
            city="Comodoro Rivadavia",
            calculation_date=date(2026, 10, 20),
            requested_items=[item1, item2],
            best_single_store=store2_total,
            item_by_item_optimal=[best_item1, best_item2],
            complete_stores=[store2_total, single_store_total],
            partial_stores=[],
            reference_prices={"779001": 1100, "779002": 900},
            multi_store_total_price=2400,
        )

        unpriced = [{"ean": "779999", "name": "Item Sin Precio", "brand": "Marca X"}]

        # 2. Build report dict
        report = BasketPriceReportService.build_report_dict(
            result=opt_result, basket=basket, unpriced_items=unpriced
        )

        assert report["report_type"] == "basket_prices_report"
        assert report["version"] == "1.0"
        assert "generated_at" in report
        assert report["basket"]["id"] == 10
        assert report["basket"]["name"] == "Canasta Test"
        assert report["basket"]["is_public"] is True
        assert report["parameters"]["city"] == "Comodoro Rivadavia"
        assert report["parameters"]["date"] == "2026-10-20"

        # Summary
        summary = report["summary"]
        assert summary["total_requested_items"] == 2
        assert summary["priced_items_count"] == 2
        assert summary["unpriced_items_count"] == 1
        assert summary["best_single_store"]["store_code"] == "S002"
        assert summary["best_single_store"]["total_price"] == 2600
        assert summary["multi_store_optimal_total"] == 2400
        assert summary["potential_savings"] == 200
        assert summary["potential_savings_percent"] > 0

        # Articles
        articles = report["articles"]
        assert len(articles) == 2
        art1 = next(a for a in articles if a["ean"] == "779001")
        assert art1["name"] == "Leche Entera 1L"
        assert art1["min_price"] == 1000
        assert art1["reference_price"] == 1100
        assert art1["cheapest_store"]["store_code"] == "S001"
        assert art1["weighted_subtotal"] == 2000

        art2 = next(a for a in articles if a["ean"] == "779002")
        assert art2["min_price"] == 800
        assert art2["weight"] == 0.5
        assert art2["weighted_subtotal"] == 400

        # Unpriced
        assert len(report["unpriced_articles"]) == 1
        assert report["unpriced_articles"][0]["ean"] == "779999"

        # Complete stores
        assert len(report["complete_stores"]) == 2

        # 3. Test export_to_json
        json_output = BasketPriceReportService.export_to_json(
            result=opt_result, basket=basket, unpriced_items=unpriced
        )
        assert isinstance(json_output, str)
        import json
        parsed = json.loads(json_output)
        assert parsed["report_type"] == "basket_prices_report"
        assert parsed["summary"]["multi_store_optimal_total"] == 2400

