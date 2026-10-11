import argparse
import re
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import (
    ArticleCode,
    DailyProductMetricModel,
    PointOfSale,
    Price,
)
from sur_en_precios.adapters.logging import setup_application_logging
from sur_en_precios.adapters.sepa_archive import ZipSepaDatasetAdapter
from sur_en_precios.config import read_config
from sur_en_precios.use_cases.process_region import ProcessAndPublishRegionUseCase


def find_latest_raw_date(raw_dir: Path) -> Optional[date]:
    """Finds the most recent YYYY-MM-DD raw date directory containing dataset archives."""
    if not raw_dir.exists():
        return None

    date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dataset_adapter = ZipSepaDatasetAdapter()
    valid_dates: list[date] = []

    for path in raw_dir.iterdir():
        if path.is_dir() and date_regex.match(path.name):
            if dataset_adapter.list_chain_archives(path):
                try:
                    valid_dates.append(date.fromisoformat(path.name))
                except ValueError:
                    pass

    return max(valid_dates) if valid_dates else None


def create_sample_sepa_data(extracted_dir: Path) -> None:
    """Generates valid sample SEPA CSVs following Anexo II metadata specifications."""
    extracted_dir.mkdir(parents=True, exist_ok=True)

    sucursales_csv = extracted_dir / "sucursales.csv"
    sucursales_csv.write_text(
        "id_comercio|id_bandera|id_sucursal|sucursales_nombre|sucursales_tipo|sucursales_calle|sucursales_numero|sucursales_latitud|sucursales_longitud|sucursales_observaciones|sucursales_barrio|sucursales_codigo_postal|sucursales_localidad|sucursales_provincia\n"
        "100|1|s1|Carrefour Central|Hipermercado|Av. Colón|250|-38.7183|-62.2662||Centro|8000|Bahía Blanca|AR-B\n"
        "100|1|s2|Vea Sucursal 1|Supermercado|Calle Donado|120|-38.7201|-62.2610||Centro|8000|Bahía Blanca|AR-B\n"
        "100|1|s3|Cooperativa Obrera|Supermercado|Av. Alem|450|-38.7145|-62.2589||Palihue|8000|Bahía Blanca|AR-B\n",
        encoding="utf-8",
    )

    productos_csv = extracted_dir / "productos.csv"
    productos_csv.write_text(
        "id_comercio|id_bandera|id_sucursal|id_producto|productos_ean|productos_descripcion|productos_cantidad_presentacion|productos_unidad_medida_presentacion|productos_marca|productos_precio_lista|productos_precio_referencia|productos_cantidad_referencia|productos_unidad_medida_referencia|productos_precio_unitario_promo1|productos_leyenda_promo1|productos_precio_unitario_promo2|productos_leyenda_promo2\n"
        "100|1|s1|7790001001|1|Leche Entera 1L|1|l|La Serenísima|1200.00|1200.00|1|l|||||\n"
        "100|1|s2|7790001001|1|Leche Entera 1L|1|l|La Serenísima|1150.00|1150.00|1|l|||||\n"
        "100|1|s3|7790001001|1|Leche Entera 1L|1|l|La Serenísima|1220.00|1220.00|1|l|||||\n"
        "100|1|s1|7790002002|1|Pan Lactal 500g|500|g|Bimbo|2400.00|4800.00|1|kg|||||\n"
        "100|1|s2|7790002002|1|Pan Lactal 500g|500|g|Bimbo|2250.00|4500.00|1|kg|||||\n"
        "100|1|s3|7790002002|1|Pan Lactal 500g|500|g|Bimbo|2300.00|4600.00|1|kg|||||\n"
        "100|1|s1|7790003003|1|Aceite Oliva Aerosol 120ml|120|ml|Freir|3500.00|29166.00|1|l|||||\n"
        "100|1|s2|7790003003|1|Aceite Oliva Aerosol 120ml|120|ml|Freir|3800.00|31666.00|1|l|||||\n"
        "100|1|s3|7790003003|1|Aceite Oliva Aerosol 120ml|120|ml|Freir|3450.00|28750.00|1|l|||||\n",
        encoding="utf-8",
    )


def run_etl_pipeline(
    workdir_override: Path | None = None,
    region: str | None = None,
    process_date_val: date | None = None,
    create_sample_if_missing: bool | None = None,
) -> Path:
    """Runs the regional ETL pipeline and updates public.sqlite database."""
    workdir_path = (
        workdir_override or (Path.home() / "Info" / "sur_en_precios").resolve()
    )
    config = read_config(workdir_override=workdir_path, should_create_override=True)
    logger = setup_application_logging(config)
    etl_settings = config.get_etl_settings()

    target_region = region or config.get_region()
    target_date = (
        process_date_val or find_latest_raw_date(config.raw_dir) or date.today()
    )
    date_str = target_date.strftime("%Y-%m-%d")

    raw_date_dir = config.raw_dir / date_str
    dataset_adapter = ZipSepaDatasetAdapter()
    chain_archives = dataset_adapter.list_chain_archives(raw_date_dir)

    should_sample = (
        create_sample_if_missing
        if create_sample_if_missing is not None
        else etl_settings.generate_sample_data
    )

    if not chain_archives:
        if should_sample:
            logger.info(
                "Raw SEPA archives missing. Generating sample SEPA data...",
                extra={"dir": str(raw_date_dir / "sepa")},
            )
            create_sample_sepa_data(raw_date_dir / "sepa")
            raw_date_dir = raw_date_dir / "sepa"
        else:
            raise FileNotFoundError(
                f"No SEPA raw dataset found in {raw_date_dir}.\n"
                f"Please harvest data first using:\n"
                f"  uv run python -m sur_en_precios.tools.run_harvest --file <PATH_TO_SEPA_ZIP>"
            )

    output_db_path = config.get_public_db_path()

    use_case = ProcessAndPublishRegionUseCase(
        target_region=target_region,
        sepa_dataset_adapter=dataset_adapter,
        batch_size=etl_settings.insert_batch_size,
        temp_dir=config.temp_dir,
        logger=logger,
    )
    use_case.execute(raw_date_dir, output_db_path, target_date)

    # Output Summary Statistics for target date
    engine = create_engine(f"sqlite:///{output_db_path}")
    with Session(engine) as session:
        store_cnt = session.execute(select(func.count(PointOfSale.id))).scalar_one()
        prod_cnt = session.execute(select(func.count(ArticleCode.id))).scalar_one()
        price_cnt = session.execute(select(func.count(Price.id))).scalar_one()
        metric_cnt = session.execute(
            select(func.count(DailyProductMetricModel.reference_price)).where(
                DailyProductMetricModel.date == target_date
            )
        ).scalar_one()

    print("\n==================================================")
    print("      SUR EN PRECIOS — ETL PIPELINE SUCCESS       ")
    print("==================================================")
    print(f" Region Target     : {target_region}")
    print(f" Date Processed    : {date_str}")
    print(f" Database Output   : {output_db_path}")
    print(f" Stores Ingested   : {store_cnt}")
    print(f" Products Ingested : {prod_cnt}")
    print(f" Price Records     : {price_cnt}")
    print(f" Reference Prices  : {metric_cnt}")
    print("==================================================\n")

    return output_db_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Sur en Precios Regional ETL Pipeline"
    )
    parser.add_argument("--workdir", help="Path to working directory")
    parser.add_argument("--region", help="Target region code (e.g. AR-U, AR-B)")
    parser.add_argument("--date", help="Target processing date (YYYY-MM-DD)")

    args = parser.parse_args()

    workdir_path = Path(args.workdir).resolve() if args.workdir else None
    target_date = date.fromisoformat(args.date) if args.date else None

    run_etl_pipeline(
        workdir_override=workdir_path, region=args.region, process_date_val=target_date
    )


if __name__ == "__main__":
    main()
