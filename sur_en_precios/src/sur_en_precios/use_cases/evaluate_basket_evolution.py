"""Use Case for executing basket evolution evaluations against public.sqlite."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from sur_en_precios.adapters.basket_files import load_baskets_from_directory
from sur_en_precios.domain.evolution import (
    BasketEvolutionEvaluator,
    CityBasketEvaluation,
    EvolutionBasketSpec,
    StorePriceObservation,
)
from sur_en_precios.domain.ports import CatalogRepositoryPort, PriceRepositoryPort
from sur_en_precios.domain.ports_evolution import EvolutionRepositoryPort

logger = logging.getLogger(__name__)

__all__ = ["EvaluateBasketEvolutionUseCase", "EvolutionExecutionResult"]


@dataclass
class EvolutionExecutionResult:
    """Summary of the execution of the evolution evaluation pipeline."""

    price_date: Optional[date]
    region: str
    run_id: Optional[int]
    baskets_loaded: int
    baskets_evaluated: int
    baskets_failed: int
    cities_count: int
    evaluations_count: int
    load_errors: List[str] = field(default_factory=list)
    evaluation_errors: List[str] = field(default_factory=list)
    evaluations: Dict[str, List[CityBasketEvaluation]] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.baskets_failed == 0 and len(self.evaluation_errors) == 0


class EvaluateBasketEvolutionUseCase:
    """Coordinates evaluating benchmark baskets across cities of a region."""

    def __init__(
        self,
        catalog_repo: CatalogRepositoryPort,
        price_repo: PriceRepositoryPort,
        evolution_repo: EvolutionRepositoryPort,
    ) -> None:
        self._catalog_repo = catalog_repo
        self._price_repo = price_repo
        self._evolution_repo = evolution_repo

    def execute(
        self,
        region: str,
        target_date: Optional[date] = None,
        cities: Optional[List[str]] = None,
        baskets_dir: Optional[Path] = None,
        basket_specs: Optional[List[EvolutionBasketSpec]] = None,
    ) -> EvolutionExecutionResult:
        """Executes the daily evaluation of all baskets against the price catalog.

        Args:
            region: ISO region code (e.g. 'AR-U').
            target_date: Date to evaluate. If None, queries latest date in public.sqlite.
            cities: List of cities. If None, queries all cities in the target region.
            baskets_dir: Directory containing basket YAML files.
            basket_specs: In-memory basket specs (overrides baskets_dir if provided).
        """
        # 1. Resolve target price date
        resolved_date = target_date or self._price_repo.get_latest_price_date()
        if not resolved_date:
            raise ValueError(
                "No hay fechas de precios disponibles en el catálogo para evaluar."
            )

        # 2. Resolve target cities
        resolved_cities: List[str] = []
        if cities:
            resolved_cities = [c.strip() for c in cities if c.strip()]
        else:
            resolved_cities = self._catalog_repo.get_cities_for_region(region)

        if not resolved_cities:
            raise ValueError(
                f"No se encontraron ciudades activas para la región '{region}'."
            )

        # 3. Load or accept basket specifications
        specs: List[EvolutionBasketSpec] = []
        load_errors: List[str] = []

        if basket_specs is not None:
            specs = list(basket_specs)
        elif baskets_dir is not None:
            load_results = load_baskets_from_directory(baskets_dir)
            for res in load_results:
                if res.ok and res.spec:
                    specs.append(res.spec)
                elif res.error:
                    load_errors.append(f"{res.path.name}: {res.error}")

        if not specs:
            logger.warning(
                "No valid basket specifications available for evolution evaluation.",
                extra={"baskets_dir": str(baskets_dir) if baskets_dir else None},
            )
            return EvolutionExecutionResult(
                price_date=resolved_date,
                region=region,
                run_id=None,
                baskets_loaded=0,
                baskets_evaluated=0,
                baskets_failed=0,
                cities_count=len(resolved_cities),
                evaluations_count=0,
                load_errors=load_errors,
            )

        # 4. Start execution run in evolution repository
        run_id = self._evolution_repo.start_run(region=region, price_date=resolved_date)

        baskets_evaluated = 0
        baskets_failed = 0
        evaluations_count = 0
        evaluation_errors: List[str] = []
        all_evaluations: Dict[str, List[CityBasketEvaluation]] = {}

        try:
            for spec in specs:
                try:
                    basket_id = self._evolution_repo.upsert_basket(spec)
                    eans = [it.ean for it in spec.items]
                    basket_evals: List[CityBasketEvaluation] = []

                    for city in resolved_cities:
                        # Fetch price observations in city for all basket EANs
                        daily_prices = self._price_repo.get_prices_for_basket(
                            city=city, price_date=resolved_date, eans=eans
                        )

                        # Transform into domain observations
                        observations: List[StorePriceObservation] = []
                        for dp in daily_prices:
                            pos = dp.point_of_sale
                            if pos:
                                label = f"{pos.chain_name} {pos.store_name}".strip()
                            else:
                                label = dp.store_code

                            observations.append(
                                StorePriceObservation(
                                    ean=dp.ean,
                                    store_code=dp.store_code,
                                    store_label=label,
                                    price=dp.price,
                                )
                            )

                        # Evaluate city
                        eval_res = BasketEvolutionEvaluator.evaluate_city(
                            city=city,
                            basket=spec,
                            observations=observations,
                        )

                        # Persist evaluation
                        self._evolution_repo.replace_city_evaluation(
                            basket_id=basket_id,
                            run_id=run_id,
                            price_date=resolved_date,
                            region=region,
                            composition_hash=spec.composition_hash,
                            evaluation=eval_res,
                        )

                        basket_evals.append(eval_res)
                        evaluations_count += 1

                    self._evolution_repo.commit()
                    all_evaluations[spec.key] = basket_evals
                    baskets_evaluated += 1

                except Exception as exc:
                    self._evolution_repo.rollback()
                    baskets_failed += 1
                    err_msg = f"Error evaluando canasta '{spec.key}': {exc}"
                    logger.exception(err_msg)
                    evaluation_errors.append(err_msg)

            # 5. Finish run audit
            final_status = "SUCCESS" if baskets_failed == 0 else "PARTIAL_ERROR"
            self._evolution_repo.finish_run(
                run_id=run_id,
                status=final_status,
                baskets_evaluated=baskets_evaluated,
                baskets_failed=baskets_failed,
                message="; ".join(evaluation_errors) if evaluation_errors else None,
            )

        except Exception as exc:
            self._evolution_repo.rollback()
            try:
                self._evolution_repo.finish_run(
                    run_id=run_id,
                    status="FAILED",
                    baskets_evaluated=baskets_evaluated,
                    baskets_failed=baskets_failed + 1,
                    message=str(exc),
                )
            except Exception:
                pass
            raise

        return EvolutionExecutionResult(
            price_date=resolved_date,
            region=region,
            run_id=run_id,
            baskets_loaded=len(specs),
            baskets_evaluated=baskets_evaluated,
            baskets_failed=baskets_failed,
            cities_count=len(resolved_cities),
            evaluations_count=evaluations_count,
            load_errors=load_errors,
            evaluation_errors=evaluation_errors,
            evaluations=all_evaluations,
        )
