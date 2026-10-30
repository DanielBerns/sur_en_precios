"""Use Case for querying, analyzing and reporting basket price evolution."""

from __future__ import annotations

import logging
from datetime import date
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
    EvolutionRepositoryPort,
    TrackedBasketInfo,
)

logger = logging.getLogger(__name__)

__all__ = ["AnalyzeBasketEvolutionUseCase"]


class AnalyzeBasketEvolutionUseCase:
    """Provides high-level analytics over the historical price evolution store."""

    def __init__(self, evolution_repo: EvolutionRepositoryPort) -> None:
        self._evolution_repo = evolution_repo

    def list_tracked_baskets(self) -> List[TrackedBasketInfo]:
        """Lists all benchmark baskets tracked in the evolution database."""
        return self._evolution_repo.list_baskets()

    def get_trend(
        self,
        basket_key: str,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[TrendRow]:
        """Calculates historical inflation trend rows for a basket in a city."""
        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, city=city, since=since, until=until
        )
        return build_trend(summaries)

    def compare_cities_on_date(
        self,
        basket_key: str,
        target_date: Optional[date] = None,
    ) -> Tuple[Optional[int], List[CityComparisonRow]]:
        """Compares a basket's cost across cities of the region on a given date.

        If target_date is None, defaults to the latest evaluated date for the basket.
        """
        resolved_date = target_date or self._evolution_repo.get_latest_date(basket_key)
        if not resolved_date:
            return None, []

        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, since=resolved_date, until=resolved_date
        )
        return compare_cities(summaries)

    def rank_stores(
        self,
        basket_key: str,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[StoreRankingRow]:
        """Ranks stores by frequency of offering the cheapest complete basket."""
        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, city=city, since=since, until=until
        )
        return rank_best_stores(summaries)

    def export_summaries(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        """Returns flat dictionaries representing daily summaries for tabular export."""
        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, city=city, since=since, until=until
        )
        rows: List[Dict[str, object]] = []
        for s in summaries:
            rows.append(
                {
                    "price_date": s.price_date.isoformat(),
                    "basket_key": s.basket_key,
                    "basket_name": s.basket_name,
                    "region": s.region,
                    "city": s.city,
                    "composition_hash": s.composition_hash,
                    "requested_items": s.requested_items_count,
                    "matched_items": s.matched_items_count,
                    "active_stores": s.active_stores_count,
                    "complete_stores": s.complete_stores_count,
                    "total_min_price": s.total_min_price,
                    "total_reference_price": s.total_reference_price,
                    "total_max_price": s.total_max_price,
                    "best_store_code": s.best_store_code,
                    "best_store_label": s.best_store_label,
                    "best_store_total": s.best_store_total,
                    "worst_store_label": s.worst_store_label,
                    "worst_store_total": s.worst_store_total,
                    "dispersion_pct": s.dispersion_pct,
                    "store_dispersion_pct": s.store_dispersion_pct,
                    "is_complete": s.is_complete,
                }
            )
        return rows

    def get_inflation_drivers(
        self,
        basket_key: str,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[ItemInflationDriver]:
        """Calculates item-level inflation drivers between the earliest and latest date in range."""
        summaries = self._evolution_repo.get_summaries(
            basket_key=basket_key, city=city, since=since, until=until
        )
        if not summaries:
            return []

        target_city = city or summaries[0].city
        city_summaries = [
            s
            for s in summaries
            if s.city.strip().lower() == target_city.strip().lower()
        ]
        if not city_summaries:
            return []

        city_summaries.sort(key=lambda s: s.price_date)
        first_summary = city_summaries[0]
        latest_summary = city_summaries[-1]

        first_items = self._evolution_repo.get_item_rows(
            basket_key=basket_key,
            city=target_city,
            since=first_summary.price_date,
            until=first_summary.price_date,
        )
        latest_items = self._evolution_repo.get_item_rows(
            basket_key=basket_key,
            city=target_city,
            since=latest_summary.price_date,
            until=latest_summary.price_date,
        )

        return calculate_inflation_drivers(
            initial_items=first_items,
            latest_items=latest_items,
            initial_basket_total=first_summary.total_reference_price,
            latest_basket_total=latest_summary.total_reference_price,
        )

    def export_items(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        """Returns flat dictionaries of item-level price observations."""
        return self._evolution_repo.get_item_rows(
            basket_key=basket_key, city=city, since=since, until=until
        )
