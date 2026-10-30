"""Unit tests for GenerateBasketEvolutionReportUseCase."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from sur_en_precios.domain.evolution import (
    EvolutionBasketSpec,
    EvolutionSummaryRecord,
)
from sur_en_precios.domain.ports_evolution import (
    EvolutionReportData,
    EvolutionReportRendererPort,
    EvolutionRepositoryPort,
    TrackedBasketInfo,
)
from sur_en_precios.use_cases.generate_basket_evolution_report import (
    GenerateBasketEvolutionReportUseCase,
)


class MockEvolutionRepo(EvolutionRepositoryPort):
    def start_run(self, region: str, price_date: Optional[date]) -> int:
        return 1

    def finish_run(
        self,
        run_id: int,
        status: str,
        baskets_evaluated: int,
        baskets_failed: int,
        message: Optional[str] = None,
    ) -> None:
        pass

    def upsert_basket(self, spec: EvolutionBasketSpec) -> int:
        return 1

    def replace_city_evaluation(self, *args, **kwargs) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def list_baskets(self) -> List[TrackedBasketInfo]:
        return [
            TrackedBasketInfo(
                basket_key="basket_1",
                name="Canasta Test",
                items_count=2,
                composition_hash="hash123",
                source_file="basket_1.yaml",
                first_date=date(2026, 10, 1),
                last_date=date(2026, 10, 2),
                evaluations_count=2,
            )
        ]

    def get_summaries(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[EvolutionSummaryRecord]:
        return [
            EvolutionSummaryRecord(
                price_date=date(2026, 10, 1),
                basket_key="basket_1",
                basket_name="Canasta Test",
                region="AR-U",
                city="Comodoro Rivadavia",
                composition_hash="hash123",
                requested_items_count=2,
                matched_items_count=2,
                active_stores_count=2,
                complete_stores_count=2,
                total_min_price=1000,
                total_reference_price=1100,
                total_max_price=1200,
                best_store_code="s1",
                best_store_label="Store 1",
                best_store_total=1050,
                worst_store_label="Store 2",
                worst_store_total=1150,
                dispersion_pct=10.0,
                store_dispersion_pct=9.5,
            ),
            EvolutionSummaryRecord(
                price_date=date(2026, 10, 2),
                basket_key="basket_1",
                basket_name="Canasta Test",
                region="AR-U",
                city="Comodoro Rivadavia",
                composition_hash="hash123",
                requested_items_count=2,
                matched_items_count=2,
                active_stores_count=2,
                complete_stores_count=2,
                total_min_price=1050,
                total_reference_price=1150,
                total_max_price=1250,
                best_store_code="s1",
                best_store_label="Store 1",
                best_store_total=1100,
                worst_store_label="Store 2",
                worst_store_total=1200,
                dispersion_pct=10.0,
                store_dispersion_pct=9.1,
            ),
        ]

    def get_latest_date(self, basket_key: str) -> Optional[date]:
        return date(2026, 10, 2)

    def get_item_rows(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        return [
            {
                "ean": "779001",
                "product_name": "Product 1",
                "quantity": 1,
                "numerator": 1,
                "denominator": 1,
                "reference_price": 500,
                "min_price": 480,
                "max_price": 520,
                "cheapest_store_code": "s1",
            }
        ]


class MockRenderer(EvolutionReportRendererPort):
    def __init__(self) -> None:
        self.rendered_payloads: List[EvolutionReportData] = []
        self.rendered_paths: List[Path] = []

    def render(self, data: EvolutionReportData, output_path: Path) -> Path:
        self.rendered_payloads.append(data)
        self.rendered_paths.append(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<html>Report</html>", encoding="utf-8")
        return output_path


def test_generate_basket_evolution_report_use_case(tmp_path: Path) -> None:
    repo = MockEvolutionRepo()
    renderer = MockRenderer()
    use_case = GenerateBasketEvolutionReportUseCase(
        evolution_repo=repo, report_renderer=renderer
    )

    out_file = tmp_path / "reports" / "evolution_latest.html"
    archive_file = tmp_path / "reports" / "evolution_2026-10-02.html"

    res = use_case.execute(
        output_path=out_file,
        archive_path=archive_file,
    )

    assert res == out_file
    assert out_file.exists()
    assert archive_file.exists()
    assert len(renderer.rendered_payloads) == 2

    payload = renderer.rendered_payloads[0]
    assert len(payload.baskets) == 1
    assert payload.cities == ["Comodoro Rivadavia"]
    assert payload.date_range == (date(2026, 10, 1), date(2026, 10, 2))
    assert "basket_1" in payload.trends
    assert "Comodoro Rivadavia" in payload.trends["basket_1"]
    assert len(payload.trends["basket_1"]["Comodoro Rivadavia"]) == 2
    assert "basket_1" in payload.store_rankings
    assert "basket_1" in payload.city_comparisons
    assert "basket_1" in payload.inflation_drivers
