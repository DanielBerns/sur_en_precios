"""Integration tests for EvaluateBasketEvolutionUseCase and AnalyzeBasketEvolutionUseCase."""

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.evolution_db import (
    create_evolution_engine,
    upgrade_evolution_schema,
)
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.adapters.database.repositories_evolution import (
    SqlAlchemyEvolutionRepository,
)
from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    PointOfSale,
    PublicBase,
)
from sur_en_precios.use_cases.analyze_basket_evolution import (
    AnalyzeBasketEvolutionUseCase,
)
from sur_en_precios.use_cases.evaluate_basket_evolution import (
    EvaluateBasketEvolutionUseCase,
)


def test_evaluate_and_analyze_evolution_pipeline(tmp_path: Path) -> None:
    # 1. Setup Public Catalog Database with sample data
    pub_db_file = tmp_path / "public.sqlite"
    pub_engine = create_engine(f"sqlite:///{pub_db_file}")
    PublicBase.metadata.create_all(pub_engine)

    eval_date = date(2026, 10, 27)

    with Session(pub_engine) as session:
        # Stores in two cities
        s1 = PointOfSale(
            code="CR_01",
            city="Comodoro Rivadavia",
            province_code="AR-U",
            brand_name="Carrefour",
            branch_name="Hiper",
        )
        s2 = PointOfSale(
            code="CR_02",
            city="Comodoro Rivadavia",
            province_code="AR-U",
            brand_name="La Anónima",
            branch_name="Centro",
        )
        s3 = PointOfSale(
            code="TW_01",
            city="Trelew",
            province_code="AR-U",
            brand_name="Vea",
            branch_name="Sucursal 1",
        )
        session.add_all([s1, s2, s3])

        # Articles
        a1 = Article(ean="779001", name="Leche 1L", clean_description="Leche 1L")
        a2 = Article(ean="779002", name="Pan 1kg", clean_description="Pan 1kg")
        session.add_all([a1, a2])
        session.flush()

        # Prices on eval_date
        # Comodoro:
        #   s1: Leche=$100, Pan=$200 -> Total=$300 (Best single store in CR)
        #   s2: Leche=$120, Pan=$220 -> Total=$340
        # Trelew:
        #   s3: Leche=$90, Pan=$180 -> Total=$270 (Cheaper in Trelew!)
        session.add_all(
            [
                DailyPrice(date=eval_date, ean="779001", store_code="CR_01", price=100),
                DailyPrice(date=eval_date, ean="779002", store_code="CR_01", price=200),
                DailyPrice(date=eval_date, ean="779001", store_code="CR_02", price=120),
                DailyPrice(date=eval_date, ean="779002", store_code="CR_02", price=220),
                DailyPrice(date=eval_date, ean="779001", store_code="TW_01", price=90),
                DailyPrice(date=eval_date, ean="779002", store_code="TW_01", price=180),
            ]
        )
        session.commit()

    # 2. Setup Evolution Database
    evo_db_file = tmp_path / "evolution.sqlite"
    upgrade_evolution_schema(evo_db_file)
    evo_engine = create_evolution_engine(evo_db_file)

    # 3. Create Sample Basket YAML
    baskets_dir = tmp_path / "baskets"
    baskets_dir.mkdir(parents=True, exist_ok=True)
    basket_yaml = """version: "1.0"
basket:
  name: "Canasta Básica Test"
  uuid: "cba-test-01"
  items:
    - ean: "779001"
      quantity: 1
      selected: true
    - ean: "779002"
      quantity: 1
      selected: true
"""
    (baskets_dir / "cba.yaml").write_text(basket_yaml, encoding="utf-8")

    # 4. Execute Evaluation
    with Session(pub_engine) as pub_session, Session(evo_engine) as evo_session:
        cat_repo = SqlAlchemyCatalogRepository(pub_session)
        price_repo = SqlAlchemyPriceRepository(pub_session)
        evo_repo = SqlAlchemyEvolutionRepository(evo_session)

        use_case = EvaluateBasketEvolutionUseCase(
            catalog_repo=cat_repo,
            price_repo=price_repo,
            evolution_repo=evo_repo,
        )

        res = use_case.execute(
            region="AR-U",
            target_date=eval_date,
            baskets_dir=baskets_dir,
        )

        assert res.is_success is True
        assert res.baskets_evaluated == 1
        assert res.cities_count == 2
        assert res.evaluations_count == 2

    # 5. Analyze Results
    with Session(evo_engine) as evo_session:
        evo_repo = SqlAlchemyEvolutionRepository(evo_session)
        analyzer = AnalyzeBasketEvolutionUseCase(evo_repo)

        # Check Trend
        trend = analyzer.get_trend(basket_key="cba-test-01", city="Comodoro Rivadavia")
        assert len(trend) == 1
        assert trend[0].record.total_min_price == 300  # min(100) + min(200)
        assert trend[0].record.best_store_code == "CR_01"

        # Check City Comparison on eval_date
        reg_mean, comparison = analyzer.compare_cities_on_date(
            basket_key="cba-test-01", target_date=eval_date
        )
        assert reg_mean is not None
        assert len(comparison) == 2
        # Trelew ($270) should be ranked #1 cheaper than Comodoro ($300+ ref)
        assert comparison[0].record.city == "Trelew"
        assert comparison[0].rank == 1
        assert comparison[1].record.city == "Comodoro Rivadavia"
        assert comparison[1].rank == 2
