from datetime import date

from sur_en_precios.domain.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleDescription,
    ArticleNumber,
    Branch,
    Flag,
    Price,
    Store,
    Timestamp,
)
from sur_en_precios.domain.models_user import BasketItem
from sur_en_precios.domain.services import BasketOptimizerService


def test_basket_optimizer_single_and_item_by_item() -> None:
    calc_date = date(2026, 10, 9)
    city = "Bahía Blanca"

    p1 = ArticleCard(
        article_number=ArticleNumber(ean="779001"),
        description=ArticleDescription(content="Milk 1L"),
        brand=ArticleBrand(brand="La Serenísima"),
    )
    p2 = ArticleCard(
        article_number=ArticleNumber(ean="779002"),
        description=ArticleDescription(content="Bread 500g"),
        brand=ArticleBrand(brand="Bimbo"),
    )
    products_map = {"779001": p1, "779002": p2}

    s1 = Store(
        code="s1",
        flag=Flag(flag="Carrefour"),
        branch=Branch(branch="Central"),
    )
    s2 = Store(
        code="s2",
        flag=Flag(flag="Vea"),
        branch=Branch(branch="Sucursal 1"),
    )
    stores = [s1, s2]

    ts = Timestamp(value=calc_date)

    # Store 1: Milk=$100, Bread=$200 (Total = $300)
    # Store 2: Milk=$150, Bread=$120 (Total = $270 - Best Single Store!)
    prices = [
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779001"),
            store=s1,
            amount=100,
        ),
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779002"),
            store=s1,
            amount=200,
        ),
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779001"),
            store=s2,
            amount=150,
        ),
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779002"),
            store=s2,
            amount=120,
        ),
    ]

    items = [
        BasketItem(ean="779001", quantity=1),
        BasketItem(ean="779002", quantity=1),
    ]
    ref_prices = {"779001": 122, "779002": 155}

    result = BasketOptimizerService.optimize_basket(
        city=city,
        calc_date=calc_date,
        requested_items=items,
        products_map=products_map,
        stores=stores,
        prices=prices,
        reference_prices=ref_prices,
    )

    assert result.best_single_store is not None
    assert result.best_single_store.store.code == "s2"
    assert result.best_single_store.total_price == 270
    assert len(result.complete_stores) == 2

    # Item-by-item cheapest: Milk from s1 ($100), Bread from s2 ($120) -> sum = 220
    assert len(result.item_by_item_optimal) == 2
    milk_opt = next(
        opt for opt in result.item_by_item_optimal if opt.product.ean == "779001"
    )
    assert milk_opt.cheapest_store.code == "s1"
    assert milk_opt.price == 100


def test_basket_optimizer_unit_pricing_and_substitutions() -> None:
    calc_date = date(2026, 10, 9)
    city = "Bahía Blanca"

    # Requested product: Premium Milk 1L, price $1000
    p1 = ArticleCard(
        article_number=ArticleNumber(ean="779100"),
        description=ArticleDescription(content="Leche Entera 1L"),
        brand=ArticleBrand(brand="Marca Premium"),
        package_amount=1.0,
        package_unit="L",
        category_id=10,
    )
    # Candidate substitute: Economy Milk 1L, price $750 (25% cheaper)
    p2 = ArticleCard(
        article_number=ArticleNumber(ean="779101"),
        description=ArticleDescription(content="Leche Entera Económica 1L"),
        brand=ArticleBrand(brand="Marca Económica"),
        package_amount=1000.0,
        package_unit="ml",
        category_id=10,
    )
    products_map = {"779100": p1, "779101": p2}

    s1 = Store(
        code="s1",
        flag=Flag(flag="Carrefour"),
        branch=Branch(branch="Central"),
    )
    stores = [s1]
    ts = Timestamp(value=calc_date)

    prices = [
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779100"),
            store=s1,
            amount=1000,
        ),
        Price(
            timestamp=ts,
            article_number=ArticleNumber(ean="779101"),
            store=s1,
            amount=750,
        ),
    ]

    items = [BasketItem(ean="779100", quantity=2)]
    ref_prices = {"779100": 1050, "779101": 780}
    sub_map = {"779100": [p2]}

    result = BasketOptimizerService.optimize_basket(
        city=city,
        calc_date=calc_date,
        requested_items=items,
        products_map=products_map,
        stores=stores,
        prices=prices,
        reference_prices=ref_prices,
        substitute_candidates_map=sub_map,
    )

    # Unit price verification:
    # 779100 (1L at $1000) -> unit_price = 1000.0, unit = 'L'
    assert len(result.item_by_item_optimal) == 1
    opt = result.item_by_item_optimal[0]
    assert opt.price == 1000
    assert opt.unit_price == 1000.0
    assert opt.unit == "L"

    # Store item price unit price verification
    store_p = result.complete_stores[0].item_prices["779100"]
    assert store_p.unit_price == 1000.0
    assert store_p.unit == "L"

    # Substitution recommendation verification
    assert opt.substitution is not None
    sub = opt.substitution
    assert sub.original_ean == "779100"
    assert sub.product.ean == "779101"
    assert sub.price == 750
    assert sub.unit_price == 750.0
    assert sub.unit == "L"
    assert sub.savings_amount == 250
    assert sub.savings_percent == 25.0
    assert len(result.suggested_substitutions) == 1
