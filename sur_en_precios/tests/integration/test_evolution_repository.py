"""Integration tests for the SQLAlchemy 2.0 evolution repository and Alembic migrations."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.evolution_db import (
    create_evolution_engine,
    upgrade_evolution_schema,
)
from sur_en_precios.adapters.database.repositories_evolution import (
    SqlAlchemyEvolutionRepository,
)
from sur_en_precios.domain.evolution import (
    CityBasketEvaluation,
    EvolutionBasketItem,
    EvolutionBasketSpec,
    ItemEvaluation,
)


def test_evolution_repository_lifecycle_and_idempotency(tmp_path: Path) -> None:
    db_file = tmp_path / "evolution_test.sqlite"

    # 1. Run migrations to construct schema
    upgrade_evolution_schema(db_file)

    # 2. Connect via engine and session
    engine = create_evolution_engine(db_file)
    with Session(engine) as session:
        repo = SqlAlchemyEvolutionRepository(session)

        # Start an audit run
        run_id = repo.start_run(region="AR-U", price_date=date(2026, 10, 27))
        assert run_id > 0

        # Upsert benchmark basket
        item = EvolutionBasketItem(ean="779001", quantity=2, name="Milk")
        spec = EvolutionBasketSpec(key="cba", name="Canasta Básica", items=(item,))
        basket_id = repo.upsert_basket(spec)
        assert basket_id > 0

        # Record city evaluation
        eval_item = ItemEvaluation(
            ean="779001",
            name="Milk",
            quantity=2,
            numerator=1,
            denominator=1,
            stores_count=2,
            min_price=100,
            reference_price=110,
            max_price=120,
            cheapest_store_code="s1",
        )
        city_eval = CityBasketEvaluation(
            city="Trelew",
            requested_items_count=1,
            matched_items_count=1,
            active_stores_count=2,
            complete_stores_count=2,
            total_min_price=200,
            total_reference_price=220,
            total_max_price=240,
            best_store_code="s1",
            best_store_label="Carrefour",
            best_store_total=200,
            worst_store_code="s2",
            worst_store_label="Vea",
            worst_store_total=240,
            dispersion_pct=20.0,
            store_dispersion_pct=20.0,
            items=[eval_item],
        )

        repo.replace_city_evaluation(
            basket_id=basket_id,
            run_id=run_id,
            price_date=date(2026, 10, 27),
            region="AR-U",
            composition_hash=spec.composition_hash,
            evaluation=city_eval,
        )
        repo.commit()

        # Idempotency check: Re-run with updated prices on the same day/city
        city_eval.total_reference_price = 230
        repo.replace_city_evaluation(
            basket_id=basket_id,
            run_id=run_id,
            price_date=date(2026, 10, 27),
            region="AR-U",
            composition_hash=spec.composition_hash,
            evaluation=city_eval,
        )
        repo.commit()

        # Finish run audit
        repo.finish_run(run_id, status="SUCCESS", baskets_evaluated=1, baskets_failed=0)

        # Verify summary read back
        summaries = repo.get_summaries(basket_key="cba", city="Trelew")
        assert len(summaries) == 1
        assert summaries[0].total_reference_price == 230
        assert summaries[0].city == "Trelew"
        assert summaries[0].is_complete is True

        # Verify tracked baskets listing
        baskets_list = repo.list_baskets()
        assert len(baskets_list) == 1
        assert baskets_list[0].basket_key == "cba"
        assert baskets_list[0].evaluations_count == 1
        assert baskets_list[0].first_date == date(2026, 10, 27)

        # Verify item-level rows
        item_rows = repo.get_item_rows(basket_key="cba")
        assert len(item_rows) == 1
        assert item_rows[0]["ean"] == "779001"
        assert item_rows[0]["min_price"] == 100
