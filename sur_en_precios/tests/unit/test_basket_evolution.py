"""Unit tests for the pure domain basket evolution evaluator and analytics."""

from datetime import date

import pytest

from sur_en_precios.domain.evolution import (
    BasketEvolutionEvaluator,
    EvolutionBasketItem,
    EvolutionBasketSpec,
    EvolutionSummaryRecord,
    StorePriceObservation,
    build_trend,
    calculate_inflation_drivers,
    compare_cities,
    geometric_mean,
    pct_change,
    rank_best_stores,
)


def test_evolution_basket_item_cost_and_validation() -> None:
    item = EvolutionBasketItem(ean="779001", quantity=2, numerator=1, denominator=1)
    assert item.line_cost(100) == 200

    # Fractional factor: 500g of a 1kg priced item (num=1, den=2)
    fractional = EvolutionBasketItem(
        ean="779002", quantity=1, numerator=1, denominator=2
    )
    assert fractional.line_cost(100) == 50

    with pytest.raises(ValueError):
        EvolutionBasketItem(ean="", quantity=1)
    with pytest.raises(ValueError):
        EvolutionBasketItem(ean="779001", quantity=0)
    with pytest.raises(ValueError):
        EvolutionBasketItem(ean="779001", quantity=1, numerator=0)
    with pytest.raises(ValueError):
        EvolutionBasketItem(ean="779001", quantity=1, denominator=0)


def test_evolution_basket_spec_and_composition_hash() -> None:
    it1 = EvolutionBasketItem(ean="779001", quantity=2)
    it2 = EvolutionBasketItem(ean="779002", quantity=1)

    spec_a = EvolutionBasketSpec(key="basket_a", name="Basket A", items=(it1, it2))
    # Same items in reverse order should yield the exact same composition hash
    spec_b = EvolutionBasketSpec(key="basket_b", name="Basket B", items=(it2, it1))
    assert spec_a.composition_hash == spec_b.composition_hash

    # Different quantity -> different composition hash
    it2_diff = EvolutionBasketItem(ean="779002", quantity=3)
    spec_c = EvolutionBasketSpec(key="basket_c", name="Basket C", items=(it1, it2_diff))
    assert spec_a.composition_hash != spec_c.composition_hash

    with pytest.raises(ValueError):
        EvolutionBasketSpec(key="", name="Empty Key", items=(it1,))
    with pytest.raises(ValueError):
        EvolutionBasketSpec(key="empty", name="No Items", items=())
    with pytest.raises(ValueError):
        EvolutionBasketSpec(key="dup", name="Duplicate Items", items=(it1, it1))


def test_geometric_mean_and_pct_change() -> None:
    assert geometric_mean([]) is None
    assert geometric_mean([0, -5]) is None
    # geom_mean(100, 400) = sqrt(40000) = 200
    assert geometric_mean([100, 400]) == 200

    assert pct_change(None, 100) is None
    assert pct_change(100, None) is None
    assert pct_change(100, 0) is None
    assert pct_change(110, 100) == 10.0
    assert pct_change(90, 100) == -10.0


def test_evaluator_complete_and_single_store_rankings() -> None:
    it1 = EvolutionBasketItem(ean="779001", quantity=1, name="Milk")
    it2 = EvolutionBasketItem(ean="779002", quantity=2, name="Bread")
    spec = EvolutionBasketSpec(key="cba", name="CBA", items=(it1, it2))

    # Stores:
    # Store s1: it1=$100, it2=$50 -> total = 100*1 + 50*2 = $200 (Best single store)
    # Store s2: it1=$80,  it2=$70 -> total = 80*1 + 70*2 = $220
    # Store s3 (partial): only it1=$60
    obs = [
        StorePriceObservation("779001", "s1", "Carrefour", 100),
        StorePriceObservation("779002", "s1", "Carrefour", 50),
        StorePriceObservation("779001", "s2", "La Anónima", 80),
        StorePriceObservation("779002", "s2", "La Anónima", 70),
        StorePriceObservation("779001", "s3", "ChangoMás", 60),
    ]

    ev = BasketEvolutionEvaluator.evaluate_city("Comodoro Rivadavia", spec, obs)

    assert ev.city == "Comodoro Rivadavia"
    assert ev.requested_items_count == 2
    assert ev.matched_items_count == 2
    assert ev.is_complete is True
    assert ev.coverage_pct == 100.0
    assert ev.active_stores_count == 3
    assert ev.complete_stores_count == 2

    # Item 1 prices: min=60 (s3), max=100 (s1), geom_mean(60, 80, 100) = 78
    # Item 2 prices: min=50 (s1), max=70 (s2), geom_mean(50, 70) = 59
    # Total min (multi-store optimal): 60*1 + 50*2 = 160
    assert ev.total_min_price == 160
    # Total max: 100*1 + 70*2 = 240
    assert ev.total_max_price == 240
    # Total reference: 78*1 + 59*2 = 196
    assert ev.total_reference_price == (78 * 1 + 59 * 2)

    # Single store best & worst
    assert ev.best_store_code == "s1"
    assert ev.best_store_label == "Carrefour"
    assert ev.best_store_total == 200

    assert ev.worst_store_code == "s2"
    assert ev.worst_store_label == "La Anónima"
    assert ev.worst_store_total == 220


def test_evaluator_partial_city() -> None:
    it1 = EvolutionBasketItem(ean="779001", quantity=1)
    it2 = EvolutionBasketItem(ean="779002", quantity=1)
    spec = EvolutionBasketSpec(key="test", name="Test", items=(it1, it2))

    # Only it1 is available in this city
    obs = [StorePriceObservation("779001", "s1", "Store 1", 100)]
    ev = BasketEvolutionEvaluator.evaluate_city("Esquel", spec, obs)

    assert ev.is_complete is False
    assert ev.matched_items_count == 1
    assert ev.requested_items_count == 2
    assert ev.complete_stores_count == 0
    assert ev.best_store_total is None
    assert ev.total_min_price == 100


def test_build_trend_analytics() -> None:
    r1 = EvolutionSummaryRecord(
        price_date=date(2026, 10, 1),
        basket_key="cba",
        basket_name="CBA",
        region="AR-U",
        city="Trelew",
        composition_hash="hash_a",
        requested_items_count=2,
        matched_items_count=2,
        active_stores_count=2,
        complete_stores_count=2,
        total_min_price=100,
        total_reference_price=100,
        total_max_price=120,
        best_store_code="s1",
        best_store_label="Store 1",
        best_store_total=105,
        worst_store_label="Store 2",
        worst_store_total=115,
        dispersion_pct=20.0,
        store_dispersion_pct=9.5,
    )
    r2 = EvolutionSummaryRecord(
        price_date=date(2026, 10, 8),
        basket_key="cba",
        basket_name="CBA",
        region="AR-U",
        city="Trelew",
        composition_hash="hash_a",
        requested_items_count=2,
        matched_items_count=2,
        active_stores_count=2,
        complete_stores_count=2,
        total_min_price=105,
        total_reference_price=110,  # +10% vs r1
        total_max_price=130,
        best_store_code="s1",
        best_store_label="Store 1",
        best_store_total=112,
        worst_store_label="Store 2",
        worst_store_total=125,
        dispersion_pct=23.8,
        store_dispersion_pct=11.6,
    )

    trend = build_trend([r2, r1])  # out of order input
    assert len(trend) == 2
    assert trend[0].price_date == date(2026, 10, 1)
    assert trend[0].change_prev_pct is None
    assert trend[0].change_base_pct == 0.0

    assert trend[1].price_date == date(2026, 10, 8)
    assert trend[1].change_prev_pct == 10.0
    assert trend[1].change_base_pct == 10.0


def test_compare_cities_analytics() -> None:
    def _rec(
        city: str, ref_price: int, complete: bool = True
    ) -> EvolutionSummaryRecord:
        return EvolutionSummaryRecord(
            price_date=date(2026, 10, 1),
            basket_key="cba",
            basket_name="CBA",
            region="AR-U",
            city=city,
            composition_hash="hash_a",
            requested_items_count=2,
            matched_items_count=2 if complete else 1,
            active_stores_count=2,
            complete_stores_count=1 if complete else 0,
            total_min_price=ref_price - 10,
            total_reference_price=ref_price,
            total_max_price=ref_price + 20,
            best_store_code="s1",
            best_store_label="Store 1",
            best_store_total=ref_price,
            worst_store_label="Store 2",
            worst_store_total=ref_price + 10,
            dispersion_pct=15.0,
            store_dispersion_pct=10.0,
        )

    r_trelew = _rec("Trelew", 100)
    r_comodoro = _rec("Comodoro Rivadavia", 400)
    r_incom = _rec("Rawson", 150, complete=False)

    reg_mean, rows = compare_cities([r_comodoro, r_incom, r_trelew])
    # Geometric mean of complete cities: geom_mean(100, 400) = 200
    assert reg_mean == 200

    assert len(rows) == 3
    # Sorted cheapest complete first
    assert rows[0].record.city == "Trelew"
    assert rows[0].rank == 1
    assert rows[0].gap_vs_regional_pct == -50.0  # (100 - 200) / 200 = -50%

    assert rows[1].record.city == "Comodoro Rivadavia"
    assert rows[1].rank == 2
    assert rows[1].gap_vs_regional_pct == 100.0  # (400 - 200) / 200 = +100%

    # Incomplete city
    assert rows[2].record.city == "Rawson"
    assert rows[2].rank == 0
    assert rows[2].gap_vs_regional_pct is None


def test_rank_best_stores_analytics() -> None:
    def _rec(city: str, best_label: str) -> EvolutionSummaryRecord:
        return EvolutionSummaryRecord(
            price_date=date(2026, 10, 1),
            basket_key="cba",
            basket_name="CBA",
            region="AR-U",
            city=city,
            composition_hash="hash_a",
            requested_items_count=1,
            matched_items_count=1,
            active_stores_count=2,
            complete_stores_count=2,
            total_min_price=100,
            total_reference_price=100,
            total_max_price=120,
            best_store_code="s1",
            best_store_label=best_label,
            best_store_total=100,
            worst_store_label="Other",
            worst_store_total=110,
            dispersion_pct=10.0,
            store_dispersion_pct=10.0,
        )

    records = [
        _rec("Comodoro", "Carrefour"),
        _rec("Comodoro", "Carrefour"),
        _rec("Comodoro", "La Anónima"),
    ]

    rankings = rank_best_stores(records)
    assert len(rankings) == 2
    assert rankings[0].store_label == "Carrefour"
    assert rankings[0].days_best == 2
    assert rankings[0].days_evaluated == 3
    assert rankings[0].share_pct == 66.7


def test_calculate_inflation_drivers() -> None:
    initial_items = [
        {
            "ean": "779001",
            "product_name": "Aceite Girasol 1L",
            "quantity": 1,
            "numerator": 1,
            "denominator": 1,
            "reference_price": 1000,
            "min_price": 950,
            "max_price": 1100,
            "cheapest_store_code": "s1",
        },
        {
            "ean": "779002",
            "product_name": "Arroz 1kg",
            "quantity": 2,
            "numerator": 1,
            "denominator": 2,  # effective quantity = 1kg
            "reference_price": 500,
            "min_price": 480,
            "max_price": 520,
            "cheapest_store_code": "s2",
        },
    ]

    latest_items = [
        {
            "ean": "779001",
            "product_name": "Aceite Girasol 1L",
            "quantity": 1,
            "numerator": 1,
            "denominator": 1,
            "reference_price": 1200,  # +200 ARS (+20%)
            "min_price": 1100,
            "max_price": 1320,
            "cheapest_store_code": "s1",
        },
        {
            "ean": "779002",
            "product_name": "Arroz 1kg",
            "quantity": 2,
            "numerator": 1,
            "denominator": 2,
            "reference_price": 500,  # no change
            "min_price": 480,
            "max_price": 540,
            "cheapest_store_code": "s2",
        },
    ]

    # Initial basket total = 1000 + 500 = 1500
    # Latest basket total = 1200 + 500 = 1700
    drivers = calculate_inflation_drivers(
        initial_items=initial_items,
        latest_items=latest_items,
        initial_basket_total=1500,
        latest_basket_total=1700,
    )

    assert len(drivers) == 2
    # Highest driver first
    d1 = drivers[0]
    assert d1.ean == "779001"
    assert d1.initial_price == 1000
    assert d1.latest_price == 1200
    assert d1.cost_change == 200
    assert d1.change_pct == 20.0
    assert d1.contribution_pct == 13.33  # 200 / 1500 * 100 = 13.33%
    assert d1.weight_pct == 70.59  # 1200 / 1700 * 100 = 70.59%
    assert d1.latest_dispersion_pct == 20.0  # (1320 - 1100) / 1100 * 100 = 20.0%

    d2 = drivers[1]
    assert d2.ean == "779002"
    assert d2.cost_change == 0
    assert d2.change_pct == 0.0
    assert d2.contribution_pct == 0.0
