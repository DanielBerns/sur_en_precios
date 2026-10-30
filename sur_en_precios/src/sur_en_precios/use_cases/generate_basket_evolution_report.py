"""Use case for generating standalone interactive HTML evolution reports."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sur_en_precios.domain.evolution import (
    CityComparisonRow,
    ItemInflationDriver,
    StoreRankingRow,
    TrendRow,
    build_trend,
    calculate_inflation_drivers,
    compare_cities,
    rank_best_stores,
)
from sur_en_precios.domain.ports_evolution import (
    EvolutionReportData,
    EvolutionReportRendererPort,
    EvolutionRepositoryPort,
)

logger = logging.getLogger(__name__)

__all__ = ["GenerateBasketEvolutionReportUseCase"]


class GenerateBasketEvolutionReportUseCase:
    """Coordinates compiling time-series data and generating offline HTML reports."""

    def __init__(
        self,
        evolution_repo: EvolutionRepositoryPort,
        report_renderer: EvolutionReportRendererPort,
    ) -> None:
        self._evolution_repo = evolution_repo
        self._report_renderer = report_renderer

    def execute(
        self,
        output_path: Path,
        basket_key: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
        archive_path: Optional[Path] = None,
    ) -> Path:
        """Collects historical metrics, prepares report data, and writes the HTML report.

        Args:
            output_path: Target path for the main report (e.g. evolution_latest.html).
            basket_key: Optional specific basket key to report on.
            since: Optional start date filter.
            until: Optional end date filter.
            archive_path: Optional secondary path for dated archival snapshot.

        Returns:
            The resolved Path to the primary generated HTML report.
        """
        all_baskets = self._evolution_repo.list_baskets()
        if basket_key:
            selected_baskets = [b for b in all_baskets if b.basket_key == basket_key]
        else:
            selected_baskets = all_baskets

        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, since=since, until=until
        )

        all_cities = sorted({s.city for s in summaries if s.city})
        dates = [s.price_date for s in summaries]
        date_range: Tuple[Optional[date], Optional[date]] = (
            (min(dates), max(dates)) if dates else (None, None)
        )

        trends: Dict[str, Dict[str, List[TrendRow]]] = {}
        city_comparisons: Dict[str, Tuple[Optional[int], List[CityComparisonRow]]] = {}
        store_rankings: Dict[str, List[StoreRankingRow]] = {}
        inflation_drivers: Dict[str, Dict[str, List[ItemInflationDriver]]] = {}

        for b in selected_baskets:
            b_key = b.basket_key
            b_summaries = [s for s in summaries if s.basket_key == b_key]
            if not b_summaries:
                continue

            # 1. Store rankings across the time window
            store_rankings[b_key] = rank_best_stores(b_summaries)

            # 2. City comparison on the latest evaluated date
            latest_b_date = max(s.price_date for s in b_summaries)
            latest_day_summaries = [
                s for s in b_summaries if s.price_date == latest_b_date
            ]
            city_comparisons[b_key] = compare_cities(latest_day_summaries)

            # 3. Trends and Inflation Drivers per city
            trends[b_key] = {}
            inflation_drivers[b_key] = {}

            b_cities = sorted({s.city for s in b_summaries if s.city})
            for city in b_cities:
                city_sums = [
                    s
                    for s in b_summaries
                    if s.city.strip().lower() == city.strip().lower()
                ]
                if not city_sums:
                    continue

                city_sums.sort(key=lambda s: s.price_date)
                trends[b_key][city] = build_trend(city_sums)

                first_sum = city_sums[0]
                last_sum = city_sums[-1]

                first_items = self._evolution_repo.get_item_rows(
                    basket_key=b_key,
                    city=city,
                    since=first_sum.price_date,
                    until=first_sum.price_date,
                )
                last_items = self._evolution_repo.get_item_rows(
                    basket_key=b_key,
                    city=city,
                    since=last_sum.price_date,
                    until=last_sum.price_date,
                )

                drivers = calculate_inflation_drivers(
                    initial_items=first_items,
                    latest_items=last_items,
                    initial_basket_total=first_sum.total_reference_price,
                    latest_basket_total=last_sum.total_reference_price,
                )
                inflation_drivers[b_key][city] = drivers

        report_data = EvolutionReportData(
            generated_at=dt.datetime.now(dt.timezone.utc),
            baskets=selected_baskets,
            cities=all_cities,
            date_range=date_range,
            summaries=summaries,
            trends=trends,
            city_comparisons=city_comparisons,
            store_rankings=store_rankings,
            inflation_drivers=inflation_drivers,
        )

        resolved_output = self._report_renderer.render(report_data, output_path)

        if archive_path is not None:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_renderer.render(report_data, archive_path)
            logger.info("Archived evolution report snapshot saved to %s", archive_path)

        logger.info("Evolution report generated successfully at %s", resolved_output)
        return resolved_output
