import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from sur_en_precios.adapters.harvester import AiohttpScraperAdapter
from sur_en_precios.adapters.logging import setup_application_logging
from sur_en_precios.adapters.storage import FileSystemStorageAdapter
from sur_en_precios.config import read_config
from sur_en_precios.use_cases.harvest_data import HarvestDailyDataUseCase


async def run_harvest(
    workdir_override: Path | None = None,
    target_date_val: date | None = None,
    sepa_url_override: str | None = None,
    local_file_override: Path | None = None,
) -> None:
    """Harvests or extracts SEPA dataset archive for specified date."""
    workdir_path = (
        workdir_override or (Path.home() / "Info" / "sur_en_precios").resolve()
    )
    config = read_config(workdir_override=workdir_path, should_create_override=True)
    logger = setup_application_logging(config)

    storage = FileSystemStorageAdapter(raw_base_dir=config.raw_dir)
    url = sepa_url_override or config.settings.scraper.sepa_url

    scraper = AiohttpScraperAdapter(
        sepa_url=url, timeout_seconds=config.settings.scraper.timeout_seconds
    )

    use_case = HarvestDailyDataUseCase(storage=storage, scraper=scraper, logger=logger)

    try:
        if local_file_override:
            local_path = local_file_override.resolve()
            result = use_case.execute_from_file(local_path)
            data_date = result["data_date"]
            dest_archive = result["archive_path"]
            extracted_files = result["extracted_files"]

            print("\n==================================================")
            print("    SUR EN PRECIOS — LOCAL ARCHIVE EXTRACTED      ")
            print("==================================================")
            print(f" Data Date    : {data_date}")
            print(f" Source File  : {local_path}")
            print(f" Stored Zip   : {dest_archive}")
            print(f" Extracted    : {len(extracted_files)} files")
            print("==================================================")
            print(
                f" Tip: Run ETL for this date using:\n  uv run python -m sur_en_precios.tools.run_etl --date {data_date}\n"
            )
            return

        result = await use_case.execute_from_web(temp_dir=config.temp_dir)
        data_date = result["data_date"]
        dest_archive = result["archive_path"]
        extracted_files = result["extracted_files"]

        print("\n==================================================")
        print("    SUR EN PRECIOS — DATA HARVESTER SUCCESS       ")
        print("==================================================")
        print(f" Data Date    : {data_date}")
        print(f" Source URL   : {url}")
        print(f" Stored Zip   : {dest_archive}")
        print(f" Extracted    : {len(extracted_files)} files")
        print("==================================================")
        print(
            f" Tip: Run ETL for this date using:\n  uv run python -m sur_en_precios.tools.run_etl --date {data_date}\n"
        )

    except Exception as exc:
        logger.error(f"Harvesting failed: {exc}")
        print("\n==================================================", file=sys.stderr)
        print("    SUR EN PRECIOS — DATA HARVESTER FAILED        ", file=sys.stderr)
        print("==================================================", file=sys.stderr)
        print(f" Error        : {exc}", file=sys.stderr)
        print(
            "\nTip: If remote URL timed out, you can provide a direct zip URL or local file:\n"
            "  1. Pass direct URL : uv run python -m sur_en_precios.tools.run_harvest --url <DIRECT_SEPA_ZIP_URL>\n"
            "  2. Pass local ZIP  : uv run python -m sur_en_precios.tools.run_harvest --file <PATH_TO_SEPA_ZIP>\n",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and Harvest SEPA Dataset Archive"
    )
    parser.add_argument("--workdir", help="Path to working directory")
    parser.add_argument("--date", help="Target processing date (YYYY-MM-DD)")
    parser.add_argument("--url", help="Override SEPA dataset archive download URL")
    parser.add_argument(
        "--file", help="Path to a local SEPA zip archive file to extract"
    )

    args = parser.parse_args()

    workdir_path = Path(args.workdir).resolve() if args.workdir else None
    target_date = date.fromisoformat(args.date) if args.date else None
    local_file = Path(args.file) if args.file else None

    asyncio.run(
        run_harvest(
            workdir_override=workdir_path,
            target_date_val=target_date,
            sepa_url_override=args.url,
            local_file_override=local_file,
        )
    )


if __name__ == "__main__":
    main()
