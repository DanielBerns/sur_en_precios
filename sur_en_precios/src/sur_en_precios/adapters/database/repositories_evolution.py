"""SQLAlchemy 2.0 implementation of the evolution repository port."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import date
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sur_en_precios.domain.evolution import (
    CityBasketEvaluation,
    EvolutionBasketSpec,
    EvolutionSummaryRecord,
)
from sur_en_precios.domain.models_evolution import (
    BasketCityItemModel,
    BasketCitySummaryModel,
    EvolutionRunModel,
    TrackedBasketModel,
)
from sur_en_precios.domain.ports_evolution import (
    EvolutionRepositoryPort,
    TrackedBasketInfo,
)

logger = logging.getLogger(__name__)

__all__ = ["SqlAlchemyEvolutionRepository"]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SqlAlchemyEvolutionRepository(EvolutionRepositoryPort):
    """Evolution store backed by an Alembic-managed SQLite database."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- runs ---------------------------------------------------------------

    def start_run(self, region: str, price_date: Optional[date]) -> int:
        run = EvolutionRunModel(
            region=region,
            price_date=price_date,
            status="RUNNING",
            baskets_evaluated=0,
            baskets_failed=0,
            started_at=_utcnow(),
        )
        self._session.add(run)
        self._session.commit()
        return run.id

    def finish_run(
        self,
        run_id: int,
        status: str,
        baskets_evaluated: int,
        baskets_failed: int,
        message: Optional[str] = None,
    ) -> None:
        run = self._session.get(EvolutionRunModel, run_id)
        if run is None:
            raise LookupError(f"Evolution run {run_id} not found")
        run.status = status
        run.baskets_evaluated = baskets_evaluated
        run.baskets_failed = baskets_failed
        run.message = message
        run.finished_at = _utcnow()
        self._session.commit()

    # -- writes -------------------------------------------------------------

    def upsert_basket(self, spec: EvolutionBasketSpec) -> int:
        model = self._session.scalars(
            select(TrackedBasketModel).where(TrackedBasketModel.basket_key == spec.key)
        ).first()
        now = _utcnow()
        if model is None:
            model = TrackedBasketModel(
                basket_key=spec.key,
                first_seen_at=now,
                name=spec.name,
                source_file=spec.source_file,
                composition_hash=spec.composition_hash,
                items_count=len(spec.items),
                last_seen_at=now,
            )
            self._session.add(model)
        else:
            if model.composition_hash != spec.composition_hash:
                logger.warning(
                    "Basket composition changed",
                    extra={
                        "basket_key": spec.key,
                        "old_hash": model.composition_hash,
                        "new_hash": spec.composition_hash,
                    },
                )
            model.name = spec.name
            model.source_file = spec.source_file
            model.composition_hash = spec.composition_hash
            model.items_count = len(spec.items)
            model.last_seen_at = now
        self._session.flush()
        return model.id

    def replace_city_evaluation(
        self,
        basket_id: int,
        run_id: Optional[int],
        price_date: date,
        region: str,
        composition_hash: str,
        evaluation: CityBasketEvaluation,
    ) -> None:
        existing = self._session.scalars(
            select(BasketCitySummaryModel).where(
                BasketCitySummaryModel.price_date == price_date,
                BasketCitySummaryModel.basket_id == basket_id,
                BasketCitySummaryModel.city == evaluation.city,
            )
        ).first()
        if existing is not None:
            self._session.delete(existing)
            self._session.flush()

        summary = BasketCitySummaryModel(
            price_date=price_date,
            basket_id=basket_id,
            run_id=run_id,
            region=region,
            city=evaluation.city,
            composition_hash=composition_hash,
            requested_items_count=evaluation.requested_items_count,
            matched_items_count=evaluation.matched_items_count,
            active_stores_count=evaluation.active_stores_count,
            complete_stores_count=evaluation.complete_stores_count,
            total_min_price=evaluation.total_min_price,
            total_reference_price=evaluation.total_reference_price,
            total_max_price=evaluation.total_max_price,
            best_store_code=evaluation.best_store_code,
            best_store_label=evaluation.best_store_label,
            best_store_total=evaluation.best_store_total,
            worst_store_code=evaluation.worst_store_code,
            worst_store_label=evaluation.worst_store_label,
            worst_store_total=evaluation.worst_store_total,
            dispersion_pct=evaluation.dispersion_pct,
            store_dispersion_pct=evaluation.store_dispersion_pct,
            evaluated_at=_utcnow(),
            items=[
                BasketCityItemModel(
                    ean=it.ean,
                    product_name=(it.name or None),
                    quantity=it.quantity,
                    numerator=it.numerator,
                    denominator=it.denominator,
                    stores_count=it.stores_count,
                    min_price=it.min_price,
                    reference_price=it.reference_price,
                    max_price=it.max_price,
                    cheapest_store_code=it.cheapest_store_code,
                )
                for it in evaluation.items
            ],
        )
        self._session.add(summary)
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    # -- reads --------------------------------------------------------------

    def list_baskets(self) -> List[TrackedBasketInfo]:
        stats = (
            select(
                BasketCitySummaryModel.basket_id,
                func.min(BasketCitySummaryModel.price_date).label("first_date"),
                func.max(BasketCitySummaryModel.price_date).label("last_date"),
                func.count(BasketCitySummaryModel.id).label("n"),
            )
            .group_by(BasketCitySummaryModel.basket_id)
            .subquery()
        )
        stmt = (
            select(
                TrackedBasketModel,
                stats.c.first_date,
                stats.c.last_date,
                stats.c.n,
            )
            .outerjoin(stats, stats.c.basket_id == TrackedBasketModel.id)
            .order_by(TrackedBasketModel.basket_key)
        )
        result: List[TrackedBasketInfo] = []
        for basket, first_date, last_date, n in self._session.execute(stmt).all():
            result.append(
                TrackedBasketInfo(
                    basket_key=basket.basket_key,
                    name=basket.name,
                    items_count=basket.items_count,
                    composition_hash=basket.composition_hash,
                    source_file=basket.source_file,
                    first_date=first_date,
                    last_date=last_date,
                    evaluations_count=int(n or 0),
                )
            )
        return result

    def get_summaries(
        self,
        basket_key: Optional[str] = None,
        city: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[EvolutionSummaryRecord]:
        stmt = select(BasketCitySummaryModel, TrackedBasketModel).join(
            TrackedBasketModel,
            BasketCitySummaryModel.basket_id == TrackedBasketModel.id,
        )
        if basket_key:
            stmt = stmt.where(TrackedBasketModel.basket_key == basket_key)
        if city:
            stmt = stmt.where(
                func.lower(BasketCitySummaryModel.city) == city.strip().lower()
            )
        if since:
            stmt = stmt.where(BasketCitySummaryModel.price_date >= since)
        if until:
            stmt = stmt.where(BasketCitySummaryModel.price_date <= until)
        stmt = stmt.order_by(
            TrackedBasketModel.basket_key,
            BasketCitySummaryModel.city,
            BasketCitySummaryModel.price_date,
        )
        return [
            EvolutionSummaryRecord(
                price_date=s.price_date,
                basket_key=b.basket_key,
                basket_name=b.name,
                region=s.region,
                city=s.city,
                composition_hash=s.composition_hash,
                requested_items_count=s.requested_items_count,
                matched_items_count=s.matched_items_count,
                active_stores_count=s.active_stores_count,
                complete_stores_count=s.complete_stores_count,
                total_min_price=s.total_min_price,
                total_reference_price=s.total_reference_price,
                total_max_price=s.total_max_price,
                best_store_code=s.best_store_code,
                best_store_label=s.best_store_label,
                best_store_total=s.best_store_total,
                worst_store_label=s.worst_store_label,
                worst_store_total=s.worst_store_total,
                dispersion_pct=s.dispersion_pct,
                store_dispersion_pct=s.store_dispersion_pct,
            )
            for s, b in self._session.execute(stmt).all()
        ]

    def get_latest_date(self, basket_key: str) -> Optional[date]:
        stmt = (
            select(func.max(BasketCitySummaryModel.price_date))
            .join(
                TrackedBasketModel,
                BasketCitySummaryModel.basket_id == TrackedBasketModel.id,
            )
            .where(TrackedBasketModel.basket_key == basket_key)
        )
        return self._session.scalar(stmt)

    def get_item_rows(
        self,
        basket_key: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[dict[str, object]]:
        """Flat item-level rows for CSV/JSON export."""
        stmt = (
            select(BasketCityItemModel, BasketCitySummaryModel, TrackedBasketModel)
            .join(
                BasketCitySummaryModel,
                BasketCityItemModel.summary_id == BasketCitySummaryModel.id,
            )
            .join(
                TrackedBasketModel,
                BasketCitySummaryModel.basket_id == TrackedBasketModel.id,
            )
        )
        if basket_key:
            stmt = stmt.where(TrackedBasketModel.basket_key == basket_key)
        if since:
            stmt = stmt.where(BasketCitySummaryModel.price_date >= since)
        if until:
            stmt = stmt.where(BasketCitySummaryModel.price_date <= until)
        stmt = stmt.order_by(
            TrackedBasketModel.basket_key,
            BasketCitySummaryModel.city,
            BasketCitySummaryModel.price_date,
            BasketCityItemModel.ean,
        )
        return [
            {
                "price_date": s.price_date.isoformat(),
                "basket_key": b.basket_key,
                "basket_name": b.name,
                "region": s.region,
                "city": s.city,
                "ean": i.ean,
                "product_name": i.product_name,
                "quantity": i.quantity,
                "numerator": i.numerator,
                "denominator": i.denominator,
                "stores_count": i.stores_count,
                "min_price": i.min_price,
                "reference_price": i.reference_price,
                "max_price": i.max_price,
                "cheapest_store_code": i.cheapest_store_code,
            }
            for i, s, b in self._session.execute(stmt).all()
        ]
