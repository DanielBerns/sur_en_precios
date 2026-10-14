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
    )

    assert metrics.date == today
    assert metrics.ean == "7790001"
    assert metrics.city_name == "Bahía Blanca"
    assert metrics.min_price == 1000
    assert metrics.max_price == 1500
    assert metrics.reference_price == 1216
    assert metrics.price_dispersion is not None
    assert metrics.price_dispersion > 0
