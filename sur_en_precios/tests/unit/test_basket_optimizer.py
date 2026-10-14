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
