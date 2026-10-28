import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from sur_en_precios.adapters.logging import setup_application_logging
from sur_en_precios.adapters.sepa_archive import ZipSepaDatasetAdapter
from sur_en_precios.config import read_config
from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
)


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


def run_etl_pipeline(
    workdir_override: Path | None = None,
    should_create_override: bool | None = None,
    region: str | None = None,
    process_date_value: date | None = None,
    process_date_val: date | None = None,
    create_sample_if_missing: bool | None = None,
) -> Path:
    """Runs the regional ETL pipeline and updates public.sqlite database."""
    workdir_path = (
        workdir_override or (Path.home() / "Info" / "sur_en_precios").resolve()
    )
    should_create = (
        should_create_override if should_create_override is not None else False
    )
    config = read_config(
        workdir_override=workdir_path, should_create_override=should_create
    )
    logger = setup_application_logging(config)
    etl_settings = config.get_etl_settings()

    target_region = region or config.get_region()

    configured_date = None
    if etl_settings.target_date:
        try:
            configured_date = date.fromisoformat(etl_settings.target_date)
        except ValueError:
            logger.warning(
                f"Invalid date format in config etl.target_date: '{etl_settings.target_date}'"
            )

    target_date = (
        process_date_val
        or process_date_value
        or configured_date
        or find_latest_raw_date(config.raw_dir)
    )
    if not target_date:
        raise FileNotFoundError(
            f"No harvested SEPA dataset found in {config.raw_dir}.\n"
            f"Please harvest data first using:\n"
            f"  uv run python -m sur_en_precios.tools.run_harvest"
        )
    date_str = target_date.strftime("%Y-%m-%d")

    raw_date_dir = config.raw_dir / date_str
    dataset_adapter = ZipSepaDatasetAdapter()
    chain_archives = dataset_adapter.list_chain_archives(raw_date_dir)

    if not chain_archives:
        raise FileNotFoundError(
            f"No SEPA raw dataset found in {raw_date_dir}.\n"
            f"Please harvest data first using:\n"
            f"  uv run python -m sur_en_precios.tools.run_harvest"
        )

    output_db_path = config.get_public_db_path()

    from sur_en_precios.use_cases.process_region import (
        ProcessAndPublishRegionUseCase,
    )

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
        articles_cnt = session.execute(select(func.count(Article.id))).scalar_one()
        price_cnt = session.execute(
            select(func.count())
            .select_from(DailyPrice)
            .where(DailyPrice.date == target_date)
        ).scalar_one()
        active_prices_cnt = session.execute(
            select(func.count()).select_from(DailyPrice)
        ).scalar_one()
        metric_cnt = session.execute(
            select(func.count())
            .select_from(DailyProductMetric)
            .where(DailyProductMetric.date == target_date)
        ).scalar_one()
        city_breakdown = session.execute(
            select(DailyProductMetric.city, func.count())
            .where(DailyProductMetric.date == target_date)
            .group_by(DailyProductMetric.city)
            .order_by(DailyProductMetric.city)
        ).all()

    print("\n==================================================")
    print("      SUR EN PRECIOS — ETL PIPELINE SUCCESS       ")
    print("==================================================")
    print(f" Region Target     : {target_region}")
    print(f" Date Processed    : {date_str}")
    print(f" Database Output   : {output_db_path}")
    print(f" Stores Ingested   : {store_cnt}")
    print(f" Catalog Articles  : {articles_cnt}")
    print(f" Prices (Date)     : {price_cnt}")
    print(f" Active Prices (7d): {active_prices_cnt}")
    print(f" Reference Prices  : {metric_cnt}")
    if city_breakdown:
        print(" City Breakdown    :")
        for city_name, count_val in city_breakdown:
            print(f"   • {city_name}: {count_val} reference prices")
    print("==================================================\n")

    return output_db_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Sur en Precios Regional ETL Pipeline"
    )
    parser.add_argument("--workdir", help="Path to working directory")

    args = parser.parse_args()

    workdir_path = Path(args.workdir).resolve() if args.workdir else None
    try:
        run_etl_pipeline(
            workdir_override=workdir_path,
            should_create_override=False,
        )
    except Exception as exc:
        try:
            config = read_config(
                workdir_override=workdir_path, should_create_override=False
            )
            logger = setup_application_logging(config)
            logger.error("ETL pipeline execution failed: %s", exc)
        except Exception:
            pass
        print(
            f"\n[ERROR] ETL Pipeline execution failed: {exc}\n",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
