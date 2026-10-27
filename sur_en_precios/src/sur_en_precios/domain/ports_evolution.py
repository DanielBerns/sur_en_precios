"""Driven port for the basket price evolution store (``evolution.sqlite``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

from sur_en_precios.domain.evolution import (
    CityBasketEvaluation,
    EvolutionBasketSpec,
    EvolutionSummaryRecord,
)

__all__ = ["EvolutionRepositoryPort", "TrackedBasketInfo"]


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
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        """Flat item-level rows (one per date/basket/city/EAN) for export."""
