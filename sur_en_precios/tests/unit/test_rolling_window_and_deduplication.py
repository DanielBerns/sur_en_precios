from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    PublicBase,
)
from sur_en_precios.domain.models_user import BasketItem
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase
from sur_en_precios.use_cases.process_region import ProcessAndPublishRegionUseCase


def test_price_repo_window_pruning_and_deduplication() -> None:
    engine = create_engine("sqlite:///:memory:")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        price_repo = SqlAlchemyPriceRepository(session)
        cat_repo = SqlAlchemyCatalogRepository(session)

        # Seed stores
        s1 = PointOfSale(
            code="S1",
            brand_name="Super A",
            city="Comodoro Rivadavia",
            province="Chubut",
        )
        s2 = PointOfSale(
            code="S2",
            brand_name="Super B",
            city="Comodoro Rivadavia",
            province="Chubut",
        )
        cat_repo.save_stores([s1, s2])

        # Seed articles
        art1 = Article(ean="779001", name="Leche 1L", brand_name="Serenisima")
        art2 = Article(ean="779002", name="Pan 500g", brand_name="Bimbo")
        cat_repo.save_articles([art1, art2])

        # Historical prices:
        # Day 1 (Oct 10 - very old, > 7 days from Oct 21)
        # Day 2 (Oct 18 - 3 days ago, within 7 days)
        # Day 3 (Oct 21 - today)
        prices = [
            # EAN 779001 at S1: Oct 10 (old), Oct 18 (intermediate), Oct 21 (latest)
            DailyPrice(
                date=date(2026, 10, 10), ean="779001", store_code="S1", price=900
            ),
            DailyPrice(
                date=date(2026, 10, 18), ean="779001", store_code="S1", price=1000
            ),
            DailyPrice(
                date=date(2026, 10, 21), ean="779001", store_code="S1", price=1100
            ),
            # EAN 779001 at S2: only reported on Oct 19 (within 7 days, store S2 didn't report today)
            DailyPrice(
                date=date(2026, 10, 19), ean="779001", store_code="S2", price=1050
            ),
            # EAN 779002 at S1: only reported on Oct 10 (older than 7 days)
            DailyPrice(
                date=date(2026, 10, 10), ean="779002", store_code="S1", price=800
            ),
        ]
        price_repo.save_prices(prices)

        # 1. Prune records older than 7-day cutoff (cutoff: Oct 15 for Oct 21)
        cutoff_date = date(2026, 10, 15)
        purged = price_repo.delete_prices_before_date(cutoff_date)
        assert purged == 2  # The two Oct 10 prices

        # Check remaining
        remaining = session.execute(
            select(
                DailyPrice.date, DailyPrice.ean, DailyPrice.store_code, DailyPrice.price
            )
        ).all()
        assert len(remaining) == 3

        # 2. Deduplicate keeping latest
        # EAN 779001 at S1 still has Oct 18 ($1000) and Oct 21 ($1100)
        deduped = price_repo.deduplicate_prices_keep_latest()
        assert deduped == 1

        final_prices = session.execute(
            select(
                DailyPrice.date, DailyPrice.ean, DailyPrice.store_code, DailyPrice.price
            )
        ).all()
        assert len(final_prices) == 2

        # Verify S1 has Oct 21 ($1100) and S2 has Oct 19 ($1050)
        price_dict = {(p[1], p[2]): (p[0], p[3]) for p in final_prices}
        assert price_dict[("779001", "S1")] == (date(2026, 10, 21), 1100)
        assert price_dict[("779001", "S2")] == (date(2026, 10, 19), 1050)

        # 3. Test get_prices_for_basket returns both S1 ($1100) and S2 ($1050) for basket optimization
        basket_prices = price_repo.get_prices_for_basket(
            city="Comodoro Rivadavia",
            price_date=date(2026, 10, 21),
            eans=["779001"],
        )
        assert len(basket_prices) == 2
        store_prices_map = {bp.store_code: bp.price for bp in basket_prices}
        assert store_prices_map["S1"] == 1100
        assert store_prices_map["S2"] == 1050

        # 4. Test get_article_price_stats returns store observations from both stores
        stats = price_repo.get_article_price_stats(
            ean="779001", city="Comodoro Rivadavia"
        )
        assert stats is not None
        assert stats.stores_count == 2
        assert stats.min_price == 1050
        assert stats.max_price == 1100
        assert stats.date == date(2026, 10, 21)


def test_process_region_multi_day_window_and_metrics(tmp_path: Path) -> None:
    output_db = tmp_path / "data" / "public.sqlite"
    use_case = ProcessAndPublishRegionUseCase(target_region="AR-U", window_days=7)

    # --- Day 1: 2026-10-18 ---
    day1_dir = tmp_path / "raw" / "2026-10-18"
    day1_dir.mkdir(parents=True)
    (day1_dir / "sucursales.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_localidad|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_provincia\n"
        "1|1|s1|Sucursal 1|Comodoro Rivadavia|San Martin|100|-45.86|-67.48|AR-U\n"
        "2|1|s2|Sucursal 2|Comodoro Rivadavia|Rivadavia|200|-45.86|-67.48|AR-U\n",
        encoding="utf-8",
    )
    (day1_dir / "productos.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|id_producto|productos_descripcion|productos_marca|productos_precio_lista\n"
        "1|1|s1|779123|Arroz Gallo Oro 1kg|Gallo|1000.00\n"
        "2|1|s2|779123|Arroz Gallo Oro 1kg|Gallo|1100.00\n",
        encoding="utf-8",
    )

    use_case.execute(day1_dir, output_db, date(2026, 10, 18))

    engine = create_engine(f"sqlite:///{output_db}")
    with Session(engine) as session:
        prices_cnt = session.scalar(select(func.count()).select_from(DailyPrice))
        assert prices_cnt == 2

    # --- Day 2: 2026-10-21 (3 days later) ---
    # Store s1 updates price to $1200.
    # Store s2 had no feed or was unchanged (omitted from today's feed).
    day2_dir = tmp_path / "raw" / "2026-10-21"
    day2_dir.mkdir(parents=True)
    (day2_dir / "sucursales.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_localidad|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_provincia\n"
        "1|1|s1|Sucursal 1|Comodoro Rivadavia|San Martin|100|-45.86|-67.48|AR-U\n",
        encoding="utf-8",
    )
    (day2_dir / "productos.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|id_producto|productos_descripcion|productos_marca|productos_precio_lista\n"
        "1|1|s1|779123|Arroz Gallo Oro 1kg|Gallo|1200.00\n",
        encoding="utf-8",
    )

    use_case.execute(day2_dir, output_db, date(2026, 10, 21))

    with Session(engine) as session:
        price_repo = SqlAlchemyPriceRepository(session)
        cat_repo = SqlAlchemyCatalogRepository(session)

        # Total prices should still be 2 (s1 updated to $1200 on Oct 21, s2 preserved at $1100 from Oct 18)
        all_dp = session.execute(
            select(DailyPrice.date, DailyPrice.store_code, DailyPrice.price)
        ).all()
        assert len(all_dp) == 2

        prices_by_store = {row[1]: (row[0], row[2]) for row in all_dp}
        assert prices_by_store["1-1-s1"] == (date(2026, 10, 21), 1200)
        assert prices_by_store["2-1-s2"] == (date(2026, 10, 18), 1100)

        # Reference price metric for Oct 21 should be calculated using BOTH stores ($1100 and $1200)
        metrics = session.execute(select(DailyProductMetric)).scalars().all()
        assert len(metrics) == 1
        m = metrics[0]
        assert m.date == date(2026, 10, 21)
        assert m.ean == "779123"
        assert m.min_price == 1100
        assert m.max_price == 1200
        assert (
            m.median_price == 1149
        )  # Reference Price (Geometric Mean of 1100 and 1200: sqrt(1.32M) = 1149)

        # Basket optimization works with both stores available
        opt = OptimizeBasketUseCase(cat_repo, price_repo)
        res = opt.execute(
            "Comodoro Rivadavia",
            date(2026, 10, 21),
            [BasketItem(ean="779123", quantity=1)],
        )
        assert res.best_single_store is not None
        assert res.best_single_store.store.code == "2-1-s2"
        assert res.best_single_store.total_price == 1100
