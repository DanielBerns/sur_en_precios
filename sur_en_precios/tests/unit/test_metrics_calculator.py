from datetime import date

from sur_en_precios.domain.services import PriceMetricsCalculator


def test_reference_price_geometric_mean() -> None:
    # Test geometric mean calculation: sqrt(100 * 400) = 200
    prices = [100, 400]
    ref_price = PriceMetricsCalculator.calculate_reference_price(prices)
    assert ref_price == 200


def test_reference_price_rounding_integer_pesos() -> None:
    # Test geometric mean rounding to integer Pesos: (100 * 200 * 300)^(1/3) ~ 181.71 -> 182
    prices = [100, 200, 300]
    ref_price = PriceMetricsCalculator.calculate_reference_price(prices)
    assert ref_price == 182


def test_calculate_metrics_full() -> None:
    today = date(2026, 10, 9)
    prices = [1000, 1200, 1500]

    metrics = PriceMetricsCalculator.calculate_metrics(
        metric_date=today,
        ean="7790001",
        city="Bahía Blanca",
        prices=prices,
        ref_price_7d_ago=1000,
    )

    assert metrics.metric_date == today
    assert metrics.min_price == 1000
    assert metrics.max_price == 1500
    assert metrics.median_price == 1200
    assert metrics.reference_price is not None
    assert metrics.pct_change_7d is not None
    assert metrics.pct_change_7d > 0
