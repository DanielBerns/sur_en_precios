"""SQLAlchemy 2.0 ORM models for the price evolution database (``evolution.sqlite``).

``evolution.sqlite`` is a permanent, append-mostly time-series store that lives
only on the UNPSJB ingestion server. Unlike ``public.sqlite`` (rebuilt daily
with a 7-day rolling window) it is never wiped. Its schema is managed by
Alembic migrations (``adapters/database/migrations/evolution``).
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "BasketCityItemModel",
    "BasketCitySummaryModel",
    "EvolutionBase",
    "EvolutionRunModel",
    "TrackedBasketModel",
]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class EvolutionBase(DeclarativeBase):
    """Declarative base for evolution.sqlite tables."""

    pass


class TrackedBasketModel(EvolutionBase):
    """A benchmark basket whose price evolution is being tracked."""

    __tablename__ = "evolution_baskets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    basket_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    composition_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )

    summaries: Mapped[List[BasketCitySummaryModel]] = relationship(
        back_populates="basket", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TrackedBasket {self.basket_key} '{self.name}'>"


class EvolutionRunModel(EvolutionBase):
    """Audit record of each evaluation run."""

    __tablename__ = "evolution_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    price_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    baskets_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baskets_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BasketCitySummaryModel(EvolutionBase):
    """Daily evaluation of a basket in a city (one row per date/basket/city)."""

    __tablename__ = "evolution_daily_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    basket_id: Mapped[int] = mapped_column(
        ForeignKey("evolution_baskets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("evolution_runs.id", ondelete="SET NULL"), nullable=True
    )
    region: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    composition_hash: Mapped[str] = mapped_column(String(16), nullable=False)

    # Coverage
    requested_items_count: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_items_count: Mapped[int] = mapped_column(Integer, nullable=False)
    active_stores_count: Mapped[int] = mapped_column(Integer, nullable=False)
    complete_stores_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Basket totals (integer ARS); NULL when no item had a price in the city
    total_min_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_reference_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_max_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Single-store totals (only stores carrying every basket item)
    best_store_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    best_store_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    best_store_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    worst_store_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    worst_store_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    worst_store_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Dispersion
    dispersion_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    store_dispersion_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    evaluated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )

    basket: Mapped[TrackedBasketModel] = relationship(back_populates="summaries")
    items: Mapped[List[BasketCityItemModel]] = relationship(
        back_populates="summary", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "price_date", "basket_id", "city", name="uq_summary_date_basket_city"
        ),
        Index("ix_summary_basket_city_date", "basket_id", "city", "price_date"),
    )


class BasketCityItemModel(EvolutionBase):
    """Item-level prices behind a city summary (for inflation-driver analysis)."""

    __tablename__ = "evolution_daily_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    summary_id: Mapped[int] = mapped_column(
        ForeignKey("evolution_daily_summaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ean: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    stores_count: Mapped[int] = mapped_column(Integer, nullable=False)
    min_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reference_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cheapest_store_code: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    summary: Mapped[BasketCitySummaryModel] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("summary_id", "ean", name="uq_item_summary_ean"),
    )
