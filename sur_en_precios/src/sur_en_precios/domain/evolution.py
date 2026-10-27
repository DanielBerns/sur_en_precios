"""Pure domain core for basket price evolution tracking.

Evaluates benchmark shopping baskets against the regional price catalog and
provides time-series analytics (trend, inter-city comparison, store ranking).

This module has no framework or database dependencies: inputs and outputs are
plain dataclasses so it can be unit tested in isolation.

Price semantics
---------------
All prices are integer Pesos Argentinos (ARS). For a basket item with
``quantity`` *q* and fractional factor *n/d*, the cost of the item line at a
unit price *P* is ``round(P * q * n / d)``. Basket totals are sums of line
costs, so they are consistent with ``BasketOptimizerService``.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "BasketEvolutionEvaluator",
    "CityBasketEvaluation",
    "CityComparisonRow",
    "EvolutionBasketItem",
    "EvolutionBasketSpec",
    "EvolutionSummaryRecord",
    "ItemEvaluation",
    "StoreRankingRow",
    "StorePriceObservation",
    "TrendRow",
    "compare_cities",
    "geometric_mean",
    "pct_change",
    "rank_best_stores",
    "build_trend",
]


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvolutionBasketItem:
    """A single tracked line of a benchmark basket."""

    ean: str
    quantity: int = 1
    numerator: int = 1
    denominator: int = 1
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ean:
            raise ValueError("Basket item EAN cannot be empty")
        if self.quantity <= 0:
            raise ValueError(f"Invalid quantity {self.quantity} for EAN {self.ean}")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError(
                f"Invalid factor {self.numerator}/{self.denominator} for EAN {self.ean}"
            )

    def line_cost(self, unit_price: int) -> int:
        """Cost of this basket line at the given unit price (integer ARS)."""
        return round(unit_price * self.quantity * self.numerator / self.denominator)


@dataclass(frozen=True)
class EvolutionBasketSpec:
    """A benchmark basket definition loaded from a downloaded basket file."""

    key: str
    name: str
    items: Tuple[EvolutionBasketItem, ...]
    source_file: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Basket key cannot be empty")
        if not self.items:
            raise ValueError(f"Basket '{self.key}' has no selected items")
        eans = [it.ean for it in self.items]
        if len(eans) != len(set(eans)):
            raise ValueError(f"Basket '{self.key}' contains duplicated EANs")

    @property
    def composition_hash(self) -> str:
        """Stable fingerprint of the basket composition.

        Two evaluations are only directly comparable over time when they share
        the same composition hash (same EANs, quantities and factors).
        """
        canonical = "|".join(
            f"{it.ean}:{it.quantity}:{it.numerator}:{it.denominator}"
            for it in sorted(self.items, key=lambda i: i.ean)
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StorePriceObservation:
    """Latest observed price of an article in a store of the evaluated city."""

    ean: str
    store_code: str
    store_label: str
    price: int


@dataclass
class ItemEvaluation:
    """City-level price statistics for a single basket line."""

    ean: str
    name: Optional[str]
    quantity: int
    numerator: int
    denominator: int
    stores_count: int = 0
    min_price: Optional[int] = None
    reference_price: Optional[int] = None
    max_price: Optional[int] = None
    cheapest_store_code: Optional[str] = None

    @property
    def is_matched(self) -> bool:
        return self.stores_count > 0


@dataclass
class CityBasketEvaluation:
    """Evaluation of a basket in a single city on a single price date."""

    city: str
    requested_items_count: int
    matched_items_count: int
    active_stores_count: int
    complete_stores_count: int
    total_min_price: Optional[int]
    total_reference_price: Optional[int]
    total_max_price: Optional[int]
    best_store_code: Optional[str] = None
    best_store_label: Optional[str] = None
    best_store_total: Optional[int] = None
    worst_store_code: Optional[str] = None
    worst_store_label: Optional[str] = None
    worst_store_total: Optional[int] = None
    dispersion_pct: Optional[float] = None
    store_dispersion_pct: Optional[float] = None
    items: List[ItemEvaluation] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return (
            self.requested_items_count > 0
            and self.matched_items_count == self.requested_items_count
        )

    @property
    def coverage_pct(self) -> float:
        if self.requested_items_count == 0:
            return 0.0
        return round(100.0 * self.matched_items_count / self.requested_items_count, 1)


@dataclass(frozen=True)
class EvolutionSummaryRecord:
    """Persisted city summary read back from the evolution store (read model)."""

    price_date: date
    basket_key: str
    basket_name: str
    region: str
    city: str
    composition_hash: str
    requested_items_count: int
    matched_items_count: int
    active_stores_count: int
    complete_stores_count: int
    total_min_price: Optional[int]
    total_reference_price: Optional[int]
    total_max_price: Optional[int]
    best_store_code: Optional[str]
    best_store_label: Optional[str]
    best_store_total: Optional[int]
    worst_store_label: Optional[str]
    worst_store_total: Optional[int]
    dispersion_pct: Optional[float]
    store_dispersion_pct: Optional[float]

    @property
    def is_complete(self) -> bool:
        return (
            self.requested_items_count > 0
            and self.matched_items_count == self.requested_items_count
        )


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def geometric_mean(values: Iterable[int]) -> Optional[int]:
    """Geometric mean of strictly positive values, rounded to integer ARS."""
    positives = [v for v in values if v > 0]
    if not positives:
        return None
    log_sum = sum(math.log(v) for v in positives)
    return round(math.exp(log_sum / len(positives)))


def pct_change(new: Optional[int], old: Optional[int]) -> Optional[float]:
    """Percentage change from ``old`` to ``new`` (None when undefined)."""
    if new is None or old is None or old <= 0:
        return None
    return round(100.0 * (new - old) / old, 2)


def _spread_pct(high: Optional[int], low: Optional[int]) -> Optional[float]:
    if high is None or low is None or low <= 0:
        return None
    return round(100.0 * (high - low) / low, 2)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class BasketEvolutionEvaluator:
    """Computes min / reference / max / single-store basket totals for a city."""

    @staticmethod
    def evaluate_city(
        city: str,
        basket: EvolutionBasketSpec,
        observations: Sequence[StorePriceObservation],
    ) -> CityBasketEvaluation:
        """Evaluates ``basket`` against the price ``observations`` of one city.

        * ``total_min_price``: every item bought at its cheapest store
          (multi-store optimum).
        * ``total_reference_price``: every item at its geometric-mean price
          across the city's stores (the project's *Reference Price*).
        * ``total_max_price``: every item at its most expensive store.
        * ``best/worst_store_total``: cheapest / most expensive single store
          that carries *all* basket items (None if no store is complete).

        Totals only include matched items (items with at least one price in
        the city); check ``is_complete`` before comparing across cities/days.
        """
        basket_eans = {it.ean for it in basket.items}

        # (ean -> store_code -> price) and store labels; ignore invalid prices.
        prices: Dict[str, Dict[str, int]] = defaultdict(dict)
        labels: Dict[str, str] = {}
        for obs in observations:
            if obs.ean not in basket_eans or obs.price <= 0:
                continue
            prices[obs.ean][obs.store_code] = obs.price
            labels[obs.store_code] = obs.store_label

        item_evals: List[ItemEvaluation] = []
        total_min = total_ref = total_max = 0
        matched = 0

        for item in basket.items:
            store_prices = prices.get(item.ean, {})
            ev = ItemEvaluation(
                ean=item.ean,
                name=item.name,
                quantity=item.quantity,
                numerator=item.numerator,
                denominator=item.denominator,
                stores_count=len(store_prices),
            )
            if store_prices:
                matched += 1
                cheapest_code = min(store_prices, key=lambda c: (store_prices[c], c))
                min_price = store_prices[cheapest_code]
                max_price = max(store_prices.values())
                # Non-empty and strictly positive, so the mean is always defined.
                ref_price = geometric_mean(store_prices.values()) or min_price
                ev.min_price = min_price
                ev.max_price = max_price
                ev.reference_price = ref_price
                ev.cheapest_store_code = cheapest_code
                total_min += item.line_cost(min_price)
                total_ref += item.line_cost(ref_price)
                total_max += item.line_cost(max_price)
            item_evals.append(ev)

        # Single-store totals over stores that carry every basket item.
        active_stores = {code for sp in prices.values() for code in sp}
        store_totals: Dict[str, int] = {}
        for code in active_stores:
            if all(code in prices.get(it.ean, {}) for it in basket.items):
                store_totals[code] = sum(
                    it.line_cost(prices[it.ean][code]) for it in basket.items
                )

        best_code = worst_code = None
        if store_totals:
            best_code = min(store_totals, key=lambda c: (store_totals[c], c))
            worst_code = max(store_totals, key=lambda c: (store_totals[c], c))

        has_prices = matched > 0
        evaluation = CityBasketEvaluation(
            city=city,
            requested_items_count=len(basket.items),
            matched_items_count=matched,
            active_stores_count=len(active_stores),
            complete_stores_count=len(store_totals),
            total_min_price=total_min if has_prices else None,
            total_reference_price=total_ref if has_prices else None,
            total_max_price=total_max if has_prices else None,
            best_store_code=best_code,
            best_store_label=labels.get(best_code) if best_code else None,
            best_store_total=store_totals.get(best_code) if best_code else None,
            worst_store_code=worst_code,
            worst_store_label=labels.get(worst_code) if worst_code else None,
            worst_store_total=store_totals.get(worst_code) if worst_code else None,
            items=item_evals,
        )
        evaluation.dispersion_pct = _spread_pct(
            evaluation.total_max_price, evaluation.total_min_price
        )
        evaluation.store_dispersion_pct = _spread_pct(
            evaluation.worst_store_total, evaluation.best_store_total
        )
        return evaluation


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendRow:
    price_date: date
    record: EvolutionSummaryRecord
    change_prev_pct: Optional[float]
    change_base_pct: Optional[float]
    comparable_with_prev: bool


def build_trend(records: Sequence[EvolutionSummaryRecord]) -> List[TrendRow]:
    """Builds a reference-price trend for one basket in one city.

    Percentage changes are only computed between evaluations that share the
    same composition hash and the same matched-item count; otherwise the
    difference would reflect coverage changes rather than price changes, and
    the row is flagged as not comparable.
    """
    ordered = sorted(records, key=lambda r: r.price_date)
    rows: List[TrendRow] = []
    base: Optional[EvolutionSummaryRecord] = None
    prev: Optional[EvolutionSummaryRecord] = None
    for rec in ordered:
        comparable = prev is not None and _comparable(prev, rec)
        if base is None or not _comparable(base, rec):
            base = rec
        rows.append(
            TrendRow(
                price_date=rec.price_date,
                record=rec,
                change_prev_pct=(
                    pct_change(rec.total_reference_price, prev.total_reference_price)
                    if comparable and prev is not None
                    else None
                ),
                change_base_pct=pct_change(
                    rec.total_reference_price, base.total_reference_price
                ),
                comparable_with_prev=comparable,
            )
        )
        prev = rec
    return rows


def _comparable(a: EvolutionSummaryRecord, b: EvolutionSummaryRecord) -> bool:
    return (
        a.composition_hash == b.composition_hash
        and a.matched_items_count == b.matched_items_count
    )


@dataclass(frozen=True)
class CityComparisonRow:
    record: EvolutionSummaryRecord
    gap_vs_regional_pct: Optional[float]
    rank: int


def compare_cities(
    records: Sequence[EvolutionSummaryRecord],
) -> Tuple[Optional[int], List[CityComparisonRow]]:
    """Compares one basket across the cities of a region for a single date.

    The regional benchmark is the geometric mean of the reference totals of
    the cities where the basket is complete. Incomplete cities are listed
    after complete ones, without a gap value.
    """
    complete = [
        r for r in records if r.is_complete and r.total_reference_price is not None
    ]
    regional = geometric_mean(
        r.total_reference_price for r in complete if r.total_reference_price
    )
    complete_sorted = sorted(complete, key=lambda r: r.total_reference_price or 0)
    incomplete = sorted((r for r in records if r not in complete), key=lambda r: r.city)
    rows: List[CityComparisonRow] = []
    for idx, rec in enumerate(complete_sorted, start=1):
        rows.append(
            CityComparisonRow(
                record=rec,
                gap_vs_regional_pct=pct_change(rec.total_reference_price, regional),
                rank=idx,
            )
        )
    for rec in incomplete:
        rows.append(CityComparisonRow(record=rec, gap_vs_regional_pct=None, rank=0))
    return regional, rows


@dataclass(frozen=True)
class StoreRankingRow:
    city: str
    store_label: str
    days_best: int
    days_evaluated: int

    @property
    def share_pct(self) -> float:
        if self.days_evaluated == 0:
            return 0.0
        return round(100.0 * self.days_best / self.days_evaluated, 1)


def rank_best_stores(
    records: Sequence[EvolutionSummaryRecord],
) -> List[StoreRankingRow]:
    """Counts how often each store was the cheapest complete store, per city."""
    days_per_city: Counter[str] = Counter()
    wins: Counter[Tuple[str, str]] = Counter()
    for rec in records:
        days_per_city[rec.city] += 1
        if rec.best_store_label:
            wins[(rec.city, rec.best_store_label)] += 1
    rows = [
        StoreRankingRow(
            city=city,
            store_label=label,
            days_best=count,
            days_evaluated=days_per_city[city],
        )
        for (city, label), count in wins.items()
    ]
    rows.sort(key=lambda r: (r.city, -r.days_best, r.store_label))
    return rows
