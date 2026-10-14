import io
import zipfile
from datetime import date
from pathlib import Path

from sur_en_precios.adapters.sepa_archive import ZipSepaDatasetAdapter
from sur_en_precios.adapters.storage import FileSystemStorageAdapter
from sur_en_precios.config import read_config
from sur_en_precios.tools.run_etl import run_etl_pipeline
from sur_en_precios.use_cases.harvest_data import HarvestDailyDataUseCase


def create_mock_inner_zip(
    chain_id: str,
    bandera_id: str,
    chain_name: str,
    stores_data: list[tuple[str, str, str, str]],  # sucursal_id, name, city, prov
    products_data: list[
        tuple[str, str, str, str, str]
    ],  # sucursal_id, ean, name, brand, price
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # comercio.csv
        comercio_content = (
            f"\ufeffid_comercio|id_bandera|comercio_cuit|comercio_razon_social|comercio_bandera_nombre|comercio_bandera_url|comercio_ultima_actualizacion|comercio_version_sepa\n"
            f"{chain_id}|{bandera_id}|3000000000|EMPRESA SA|{chain_name}|http://example.com|2026-10-01T00:00:00-03:00|1.0\n"
            f"Última actualización: 2026-10-01T00:00:00-03:00\n"
        )
        zf.writestr("comercio.csv", comercio_content.encode("utf-8"))

        # sucursales.csv
        suc_lines = [
            "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_tipo|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_observaciones|sucursales_barrio|sucursales_codigo_postal|sucursales_localidad|sucursales_provincia"
        ]
        for suc_id, s_name, city, prov in stores_data:
            suc_lines.append(
                f"{chain_id}|{bandera_id}|{suc_id}|{s_name}|Supermercado|Av. Principal|100|-43.25|-65.31|||9100|{city}|{prov}"
            )
        suc_lines.append("Última actualización: 2026-10-01T00:00:00-03:00\n")
        zf.writestr("sucursales.csv", "\n".join(suc_lines).encode("utf-8"))

        # productos.csv
        prod_lines = [
            "id_comercio|id_bandera|id_sucursal|id_producto|productos_ean|productos_descripcion|productos_cantidad_presentacion|productos_unidad_medida_presentacion|productos_marca|productos_precio_lista|productos_precio_referencia|productos_cantidad_referencia|productos_unidad_medida_referencia|productos_precio_unitario_promo1|productos_leyenda_promo1|productos_precio_unitario_promo2|productos_leyenda_promo2"
        ]
        for suc_id, ean, p_name, brand, price in products_data:
            prod_lines.append(
                f"{chain_id}|{bandera_id}|{suc_id}|{ean}|1|{p_name}|500|grm|{brand}|{price}|{price}|1|kgm||||"
            )
        prod_lines.append("Última actualización: 2026-10-01T00:00:00-03:00\n")
        zf.writestr("productos.csv", "\n".join(prod_lines).encode("utf-8"))

    return buffer.getvalue()


def create_mock_outer_zip(target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)

    inner_1 = create_mock_inner_zip(
        chain_id="1",
        bandera_id="1",
        chain_name="Carrefour",
        stores_data=[("100", "Carrefour Trelew", "Trelew", "AR-U")],
        products_data=[("100", "779001001", "Aceite Oliva 500ml", "Natura", "3000.00")],
    )

    inner_2 = create_mock_inner_zip(
        chain_id="2",
        bandera_id="1",
        chain_name="La Anonima",
        stores_data=[
            ("100", "La Anonima Trelew", "Trelew", "AR-U"),  # Colliding sucursal_id 100
            ("200", "La Anonima CABA", "Buenos Aires", "AR-C"),  # Non-target region
        ],
        products_data=[
            ("100", "779001001", "Aceite Oliva 500ml", "Natura", "3200.00"),
            (
                "200",
                "779001001",
                "Aceite Oliva 500ml",
                "Natura",
                "3100.00",
            ),  # AR-C price
        ],
    )

    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "2026-10-01/sepa_1_comercio-sepa-1_2026-10-01_09-00-00.zip", inner_1
        )
        zf.writestr(
            "2026-10-01/sepa_2_comercio-sepa-2_2026-10-01_09-00-00.zip", inner_2
        )

    return target_path


def test_sepa_archive_harvest_and_etl_pipeline(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    config = read_config(workdir_override=workdir, should_create_override=True)

    sample_zip = tmp_path / "sepa_jueves.zip"
    create_mock_outer_zip(sample_zip)

    # 1. Test Date Inference
    adapter = ZipSepaDatasetAdapter()
    inferred_date = adapter.infer_data_date(sample_zip)
    assert inferred_date == date(2026, 10, 1)

    # 2. Test Harvest Use Case
    storage = FileSystemStorageAdapter(raw_base_dir=config.raw_dir)
    use_case = HarvestDailyDataUseCase(storage=storage)
    result = use_case.execute_from_file(sample_zip)

    assert result["data_date"] == date(2026, 10, 1)
    stored_archive: Path = result["archive_path"]
    assert stored_archive.exists()
    assert stored_archive.name == "sepa_2026-10-01.zip"

    # 3. Test Regional ETL pipeline
    db_path = run_etl_pipeline(
        workdir_override=workdir,
        region="AR-U",
        process_date_val=date(2026, 10, 1),
        create_sample_if_missing=False,
    )
    assert db_path.exists()

    # Query DB to verify contents
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from sur_en_precios.domain.models_public import (
        ArticleMetric,
        ArticleNumber,
        Price,
        Store,
    )

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        stores = session.execute(select(Store)).scalars().all()
        # Should contain 2 stores in AR-U (1-1-100 and 2-1-100), store 2-1-200 (AR-C) excluded
        assert len(stores) == 2
        store_ids = {s.code for s in stores}
        assert store_ids == {"1-1-100", "2-1-100"}
        chain_names = {s.chain_name for s in stores}
        assert chain_names == {"Carrefour", "La Anonima"}

        products = session.execute(select(ArticleNumber)).scalars().all()
        assert len(products) == 1
        assert products[0].ean == "779001001"

        prices = session.execute(select(Price)).scalars().all()
        # Should contain 2 prices (from AR-U stores 1-1-100 and 2-1-100)
        assert len(prices) == 2
        price_store_ids = {p.store_code for p in prices}
        assert price_store_ids == {"1-1-100", "2-1-100"}

        metrics = session.execute(select(ArticleMetric)).scalars().all()
        assert len(metrics) == 1
        # Geometric mean of 3000 and 3200 = round(sqrt(3000 * 3200)) = 3098
        assert metrics[0].reference_price == 3098
        assert metrics[0].city_name == "Trelew"

    # 4. Test Idempotence: Re-run ETL for same date
    _ = run_etl_pipeline(
        workdir_override=workdir,
        region="AR-U",
        process_date_val=date(2026, 10, 1),
        create_sample_if_missing=False,
    )

    with Session(engine) as session:
        prices = session.execute(select(Price)).scalars().all()
        assert len(prices) == 2
        metrics = session.execute(select(ArticleMetric)).scalars().all()
        assert len(metrics) == 1
