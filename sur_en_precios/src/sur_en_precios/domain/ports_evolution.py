"""Driven port for the basket price evolution store (``evolution.sqlite``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sur_en_precios.domain.evolution import (
    CityBasketEvaluation,
    CityComparisonRow,
    EvolutionBasketSpec,
    EvolutionSummaryRecord,
    ItemInflationDriver,
    StoreRankingRow,
    TrendRow,
)

__all__ = [
    "EvolutionReportData",
    "EvolutionReportRendererPort",
    "EvolutionRepositoryPort",
    "TrackedBasketInfo",
]


class TrackedBasketInfo:
    """Lightweight read model describing a tracked basket."""

    def __init__(
        self,
        basket_key: str,
        name: str,
        items_count: int,
        composition_hash: str,
        source_file: Optional[str],
        first_date: Optional[date],
        last_date: Optional[date],
        evaluations_count: int,
    ) -> None:
        self.basket_key = basket_key
        self.name = name
        self.items_count = items_count
        self.composition_hash = composition_hash
        self.source_file = source_file
        self.first_date = first_date
        self.last_date = last_date
        self.evaluations_count = evaluations_count


class EvolutionRepositoryPort(ABC):
    """Persistence operations for basket evolution tracking."""

    @abstractmethod
    def start_run(self, region: str, price_date: Optional[date]) -> int:
        """Creates a run audit record and returns its id."""

    @abstractmethod
    def finish_run(
        self,
        run_id: int,
        status: str,
        baskets_evaluated: int,
        baskets_failed: int,
        message: Optional[str] = None,
    ) -> None:
        """Closes a run audit record."""

    @abstractmethod
    def upsert_basket(self, spec: EvolutionBasketSpec) -> int:
        """Registers or refreshes a tracked basket and returns its id."""

    @abstractmethod
    def replace_city_evaluation(
        self,
        basket_id: int,
        run_id: Optional[int],
        price_date: date,
        region: str,
        composition_hash: str,
        evaluation: CityBasketEvaluation,
    ) -> None:
        """Stores an evaluation, replacing any previous one for the same
        (price_date, basket, city) so re-runs are idempotent."""

    @abstractmethod
    def commit(self) -> None:
        """Commits pending changes."""

    @abstractmethod
    def rollback(self) -> None:
        """Discards pending changes."""

    @abstractmethod
    def list_baskets(self) -> List[TrackedBasketInfo]:
        """Lists tracked baskets with their evaluated date range."""

    @abstractmethod
    def get_summaries(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[EvolutionSummaryRecord]:
        """Returns city summaries ordered by (basket, city, date)."""

    @abstractmethod
    def get_latest_date(self, basket_key: str) -> Optional[date]:
        """Latest evaluated price date for a basket."""

    @abstractmethod
    def get_item_rows(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        """Flat item-level rows (one per date/basket/city/EAN) for export and analysis."""


@dataclass(frozen=True)
class EvolutionReportData:
    """Consolidated read-only data payload for rendering basket evolution reports."""

    generated_at: datetime
    baskets: List[TrackedBasketInfo]
    cities: List[str]
    date_range: Tuple[Optional[date], Optional[date]]
    summaries: List[EvolutionSummaryRecord]
    trends: Dict[str, Dict[str, List[TrendRow]]]  # basket_key -> city -> List[TrendRow]
    city_comparisons: Dict[
        str, Tuple[Optional[int], List[CityComparisonRow]]
    ]  # basket_key -> (regional_ref, comparisons)
    store_rankings: Dict[
        str, List[StoreRankingRow]
    ]  # basket_key -> List[StoreRankingRow]
    inflation_drivers: Dict[
        str, Dict[str, List[ItemInflationDriver]]
    ]  # basket_key -> city -> List[ItemInflationDriver]


class EvolutionReportRendererPort(ABC):
    """Driven port for rendering basket evolution reports to persistent artifacts."""

    @abstractmethod
    def render(self, data: EvolutionReportData, output_path: Path) -> Path:
        """Renders report data to the specified output path and returns the resolved path."""
