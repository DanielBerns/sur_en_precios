from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.domain.models import ListItem
from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase
from sur_en_precios.use_cases.process_region import ProcessAndPublishRegionUseCase


def test_process_and_publish_region_use_case(tmp_path: Path) -> None:
    # Build sample mock SEPA CSV files
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()

    sucursales_csv = extracted_dir / "sucursales.csv"
    sucursales_csv.write_text(
        "id_sucursal|sucursales_nombre|sucursales_localidad|sucursales_calle|sucursales_latitud|sucursales_longitud|sucursales_provincia\n"
        "s1|Sucursal 1|Bahía Blanca|Av. Colon 100|-38.71|-62.26|AR-B\n",
        encoding="utf-8",
    )

    productos_csv = extracted_dir / "productos.csv"
    productos_csv.write_text(
        "id_producto|productos_descripcion|productos_marca|id_sucursal|productos_precio_lista\n"
        "779001|Aceite Oliva 120ml|Freir|s1|1250.00\n",
        encoding="utf-8",
    )

    output_db = tmp_path / "data" / "public.sqlite"
    today = date(2026, 10, 9)

    use_case = ProcessAndPublishRegionUseCase(target_region="AR-B")
    use_case.execute(extracted_dir, output_db, today)

    assert output_db.exists()

    # Verify generated public.sqlite via repositories
    engine = create_engine(f"sqlite:///{output_db}")
    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        price_repo = SqlAlchemyPriceRepository(session)

        product = cat_repo.get_product_by_ean("779001")
        assert product is not None
        assert product.name == "Aceite Oliva 120ml"

        stores = cat_repo.get_stores_by_city("Bahía Blanca")
        assert len(stores) == 1

        # Test Optimize Basket Use Case against generated DB
        opt_use_case = OptimizeBasketUseCase(cat_repo, price_repo)
        result = opt_use_case.execute(
            "Bahía Blanca", today, [ListItem(ean="779001", quantity=1)]
        )

        assert result.best_single_store is not None
        assert result.best_single_store.total_price == 1250
