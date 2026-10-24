from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.domain.models_public import PublicBase
from sur_en_precios.domain.models_user import BasketItem
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase
from sur_en_precios.use_cases.process_region import ProcessAndPublishRegionUseCase


def test_process_and_publish_region_use_case(tmp_path: Path) -> None:
    # Build sample mock SEPA CSV files
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()

    sucursales_csv = extracted_dir / "sucursales.csv"
    sucursales_csv.write_text(
        "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_localidad|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_provincia\n"
        "100|1|s1|Sucursal 1|Bahía Blanca|Av. Colon|100|-38.71|-62.26|AR-B\n",
        encoding="utf-8",
    )

    productos_csv = extracted_dir / "productos.csv"
    productos_csv.write_text(
        "id_comercio|id_bandera|id_sucursal|id_producto|productos_descripcion|productos_marca|productos_precio_lista\n"
        "100|1|s1|779001|Aceite Oliva 120ml|Freir|1250.00\n",
        encoding="utf-8",
    )

    output_db = tmp_path / "data" / "public.sqlite"
    today = date(2026, 10, 9)

    use_case = ProcessAndPublishRegionUseCase(target_region="AR-B")
    use_case.execute(extracted_dir, output_db, today)

    assert output_db.exists()

    # Verify generated public.sqlite via repositories
    engine = create_engine(f"sqlite:///{output_db}")
    assert set(inspect(engine).get_table_names()) == set(PublicBase.metadata.tables)
    assert not any("fts" in t for t in inspect(engine).get_table_names())
    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        price_repo = SqlAlchemyPriceRepository(session)

        product = cat_repo.get_article_by_ean("779001")
        assert product is not None
        assert "Aceite Oliva" in product.name
        assert product.brand_name == "Freir"

        stores = cat_repo.get_stores_by_city("Bahía Blanca")
        assert len(stores) >= 1
        assert any(s.code == "100-1-s1" for s in stores)

        # Test Optimize Basket Use Case against generated DB
        opt_use_case = OptimizeBasketUseCase(cat_repo, price_repo)
        result = opt_use_case.execute(
            "Bahía Blanca", today, [BasketItem(ean="779001", quantity=1)]
        )

        assert result.best_single_store is not None
        assert result.best_single_store.total_price == 1250


def test_process_region_prunes_legacy_orphan_stores(tmp_path: Path) -> None:
    from sur_en_precios.domain.models_public import PointOfSale

    output_db = tmp_path / "data" / "public.sqlite"
    output_db.parent.mkdir(parents=True)
    engine = create_engine(f"sqlite:///{output_db}")
    PublicBase.metadata.create_all(engine)

    # Pre-populate DB with a legacy unpriced AR-B store (mimicking old hermes_clean.db seeding)
    with Session(engine) as session:
        session.add(
            PointOfSale(
                code="(10-1-292)(hipermercado carrefour)",
                brand_name="Carrefour",
                branch_name="25 De Mayo",
                city="25 De Mayo",
                province="Buenos Aires",
                province_code="AR-B",
            )
        )
        session.commit()

    extracted_dir = tmp_path / "extracted_aru"
    extracted_dir.mkdir()
    (extracted_dir / "sucursales.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_localidad|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_provincia\n"
        "9|2|15|Sucursal Centro|Comodoro Rivadavia|San Martin|500|-45.86|-67.48|AR-U\n",
        encoding="utf-8",
    )
    (extracted_dir / "productos.csv").write_text(
        "id_comercio|id_bandera|id_sucursal|id_producto|productos_descripcion|productos_marca|productos_precio_lista\n"
        "9|2|15|7790895000430|Gaseosa Cola 1.5L|Coca-Cola|2500.00\n",
        encoding="utf-8",
    )

    use_case = ProcessAndPublishRegionUseCase(
        target_region="AR-U", master_db_path=tmp_path / "nonexistent_hermes.db"
    )
    use_case.execute(extracted_dir, output_db, date(2026, 10, 24))

    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        assert cat_repo.get_cities_for_region("AR-U") == ["Comodoro Rivadavia"]
        assert cat_repo.get_cities_for_region("AR-B") == ["Comodoro Rivadavia"]
        assert cat_repo.get_stores_by_city("25 De Mayo") == []
