"""Unit tests for HtmlBasketEvolutionReportRenderer."""

from __future__ import annotations

import datetime as dt
from datetime import date
from pathlib import Path

from sur_en_precios.adapters.reports.html_evolution_report import (
    HtmlBasketEvolutionReportRenderer,
)
from sur_en_precios.domain.evolution import (
    CityComparisonRow,
    EvolutionSummaryRecord,
    ItemInflationDriver,
    StoreRankingRow,
    TrendRow,
)
from sur_en_precios.domain.ports_evolution import (
    EvolutionReportData,
    TrackedBasketInfo,
)


def test_html_basket_evolution_report_renderer(tmp_path: Path) -> None:
    renderer = HtmlBasketEvolutionReportRenderer()
    output_path = tmp_path / "reports" / "evolution_latest.html"

    basket_info = TrackedBasketInfo(
        basket_key="basket_aceites",
        name="Aceites Comestibles",
        items_count=2,
        composition_hash="hash_aceites",
        source_file="basket_aceites.yaml",
        first_date=date(2026, 10, 1),
        last_date=date(2026, 10, 2),
        evaluations_count=2,
    )

    summary_1 = EvolutionSummaryRecord(
        price_date=date(2026, 10, 1),
        basket_key="basket_aceites",
        basket_name="Aceites Comestibles",
        region="AR-U",
        city="Comodoro Rivadavia",
        composition_hash="hash_aceites",
        requested_items_count=2,
        matched_items_count=2,
        active_stores_count=3,
        complete_stores_count=3,
        total_min_price=1000,
        total_reference_price=1100,
        total_max_price=1200,
        best_store_code="s1",
        best_store_label="La Anónima Suc. 24",
        best_store_total=1050,
        worst_store_label="Carrefour",
        worst_store_total=1180,
        dispersion_pct=10.0,
        store_dispersion_pct=9.5,
    )

    summary_2 = EvolutionSummaryRecord(
        price_date=date(2026, 10, 2),
        basket_key="basket_aceites",
        basket_name="Aceites Comestibles",
        region="AR-U",
        city="Comodoro Rivadavia",
        composition_hash="hash_aceites",
        requested_items_count=2,
        matched_items_count=2,
        active_stores_count=3,
        complete_stores_count=3,
        total_min_price=1050,
        total_reference_price=1150,
        total_max_price=1250,
        best_store_code="s1",
        best_store_label="La Anónima Suc. 24",
        best_store_total=1100,
        worst_store_label="Carrefour",
        worst_store_total=1220,
        dispersion_pct=9.5,
        store_dispersion_pct=9.0,
    )

    trend_rows = [
        TrendRow(
            price_date=date(2026, 10, 1),
            record=summary_1,
            change_prev_pct=None,
            change_base_pct=0.0,
            comparable_with_prev=False,
        ),
        TrendRow(
            price_date=date(2026, 10, 2),
            record=summary_2,
            change_prev_pct=4.55,
            change_base_pct=4.55,
            comparable_with_prev=True,
        ),
    ]

    city_comp = CityComparisonRow(
        record=summary_2,
        gap_vs_regional_pct=1.2,
        rank=1,
    )

    store_rank = StoreRankingRow(
        city="Comodoro Rivadavia",
        store_label="La Anónima Suc. 24",
        days_best=2,
        days_evaluated=2,
    )

    driver = ItemInflationDriver(
        ean="779001",
        product_name="Aceite Canola 500ml",
        quantity=1,
        numerator=1,
        denominator=1,
        initial_price=500,
        latest_price=550,
        initial_line_cost=500,
        latest_line_cost=550,
        cost_change=50,
        change_pct=10.0,
        weight_pct=47.83,
        contribution_pct=4.55,
        latest_dispersion_pct=12.0,
        cheapest_store_code="s1",
    )

    data = EvolutionReportData(
        generated_at=dt.datetime(2026, 10, 30, 12, 0, tzinfo=dt.timezone.utc),
        baskets=[basket_info],
        cities=["Comodoro Rivadavia"],
        date_range=(date(2026, 10, 1), date(2026, 10, 2)),
        summaries=[summary_1, summary_2],
        trends={"basket_aceites": {"Comodoro Rivadavia": trend_rows}},
        city_comparisons={"basket_aceites": (1150, [city_comp])},
        store_rankings={"basket_aceites": [store_rank]},
        inflation_drivers={"basket_aceites": {"Comodoro Rivadavia": [driver]}},
    )

    res_path = renderer.render(data, output_path)

    assert res_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 5000

    content = output_path.read_text(encoding="utf-8")

    # Localized Spanish UI assertions
    assert "Sur en Precios — Evolución de Canastas Testigo" in content
    assert "Disparidad Interurbana" in content
    assert "Motores de Inflación (Artículos)" in content
    assert "Competitividad de Comercios" in content
    assert "UNPSJB Ingestion Server" in content
    assert "Modo 100% Offline" in content

    # Self-containment & zero-CDN assertions (no external script/stylesheet links)
    assert '<script src="http' not in content
    assert '<link rel="stylesheet" href="http' not in content
    assert "unpkg.com" not in content
    assert "cdnjs.cloudflare.com" not in content

    # Embedded data verification
    assert '"basket_aceites"' in content
    assert '"Comodoro Rivadavia"' in content
    assert '"Aceite Canola 500ml"' in content
