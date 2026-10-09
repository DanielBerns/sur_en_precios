from datetime import date

from sur_en_precios.domain.models import (
    DailyPrice,
    ListItem,
    Product,
    Store,
)
from sur_en_precios.domain.services import BasketOptimizerService


def test_basket_optimizer_single_and_item_by_item() -> None:
    calc_date = date(2026, 10, 9)
    city = "Bahía Blanca"

    p1 = Product(ean="779001", name="Milk 1L", brand="La Serenísima")
    p2 = Product(ean="779002", name="Bread 500g", brand="Bimbo")
    products_map = {p1.ean: p1, p2.ean: p2}

    s1 = Store(id="s1", chain_name="Carrefour", store_name="Central", city=city)
    s2 = Store(id="s2", chain_name="Vea", store_name="Sucursal 1", city=city)
    stores = [s1, s2]

    # Store 1: Milk=$100, Bread=$200 (Total = $300)
    # Store 2: Milk=$150, Bread=$120 (Total = $270 - Best Single Store!)
    prices = [
        DailyPrice(price_date=calc_date, ean="779001", store_id="s1", price=100),
        DailyPrice(price_date=calc_date, ean="779002", store_id="s1", price=200),
        DailyPrice(price_date=calc_date, ean="779001", store_id="s2", price=150),
        DailyPrice(price_date=calc_date, ean="779002", store_id="s2", price=120),
    ]

    items = [ListItem(ean="779001", quantity=1), ListItem(ean="779002", quantity=1)]
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
    assert result.best_single_store.store.id == "s2"
    assert result.best_single_store.total_price == 270
    assert len(result.complete_stores) == 2

    # Item-by-item cheapest: Milk from s1 ($100), Bread from s2 ($120) -> sum = 220
    assert len(result.item_by_item_optimal) == 2
    milk_opt = next(
        opt for opt in result.item_by_item_optimal if opt.product.ean == "779001"
    )
    assert milk_opt.cheapest_store.id == "s1"
    assert milk_opt.price == 100
