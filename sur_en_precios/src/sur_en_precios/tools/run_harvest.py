import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from sur_en_precios.adapters.harvester import AiohttpScraperAdapter
from sur_en_precios.adapters.logging import setup_application_logging
from sur_en_precios.adapters.storage import FileSystemStorageAdapter
from sur_en_precios.config import read_config
from sur_en_precios.use_cases.harvest_data import HarvestDailyDataUseCase


async def run_harvest(
    workdir_override: Optional[Path] = None,
    should_create_override: Optional[bool] = None,
    sepa_url_override: Optional[str] = None,
    local_file_override: Optional[Path] = None,
    target_date_override: Optional[date] = None,
    force_override: bool = False,
    limit_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Harvests SEPA dataset archives: downloads webpage, searches for new zip files, and downloads them."""
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
    scraper_settings = config.get_scraper_settings()

    storage = FileSystemStorageAdapter(raw_base_dir=config.raw_dir)
    url = sepa_url_override or scraper_settings.sepa_url

    local_file = local_file_override or (
        Path(scraper_settings.local_archive_file).resolve()
        if scraper_settings.local_archive_file
        else None
    )

    scraper = AiohttpScraperAdapter(
        sepa_url=url, timeout_seconds=scraper_settings.timeout_seconds
    )
    use_case = HarvestDailyDataUseCase(storage=storage, scraper=scraper, logger=logger)

    try:
        # Offline mode: process local file if provided
        if local_file:
            result = use_case.execute_from_file(local_file)
            data_date = result["data_date"]
            dest_archive = result["archive_path"]
            extracted_files = result["extracted_files"]

            print("\n==================================================")
            print("    SUR EN PRECIOS — LOCAL ARCHIVE EXTRACTED      ")
            print("==================================================")
            print(f" Data Date    : {data_date}")
            print(f" Source File  : {local_file}")
            print(f" Stored Zip   : {dest_archive}")
            print(f" Extracted    : {len(extracted_files)} files")
            print("==================================================")
            print(
                " Tip: Run ETL for this date using:\n  uv run python -m sur_en_precios.tools.run_etl\n"
            )
            return result

        # Online mode: download webpage, search for new zip files, and download them
        print("\n==================================================")
        print("    SUR EN PRECIOS — HARVESTING FROM SEPA PORTAL  ")
        print("==================================================")
        print(f" Portal URL   : {url}")
        print(f" Raw Base Dir : {config.raw_dir}")
        if target_date_override:
            print(f" Target Date  : {target_date_override}")
        print("==================================================")

        discovered = await use_case.discover_web_archives(page_url=url)
        print(f"\n Discovered {len(discovered)} SEPA archive(s) on portal:")

        new_archives = []
        for item in discovered:
            d_val = item.get("date")
            d_str = d_val.strftime("%Y-%m-%d") if d_val else "unknown"
            already_exists = False
            if d_val:
                existing_file = config.raw_dir / d_str / f"sepa_{d_str}.zip"
                already_exists = (
                    existing_file.exists() and existing_file.stat().st_size > 0
                )

            status_tag = (
                "[ALREADY STORED]"
                if (already_exists and not force_override)
                else "[NEW]"
            )
            if not already_exists or force_override:
                if target_date_override is None or d_val == target_date_override:
                    new_archives.append(item)

            print(f"   • {item.get('name', 'SEPA')}: {d_str} {status_tag}")

        if not new_archives:
            print("\n No new SEPA zip files found to download.")
            print(
                " (All archives available on the webpage are already stored in raw storage)"
            )
            print(" Tip: Use --force to re-download existing archives.\n")
            return {
                "downloaded": [],
                "new_count": 0,
                "total_found": len(discovered),
                "data_date": None,
                "archive_path": None,
                "extracted_files": [],
            }

        download_target_count = (
            len(new_archives)
            if limit_override is None
            else min(len(new_archives), limit_override)
        )
        print(f"\n Downloading {download_target_count} new archive(s)...")
        results = await use_case.harvest_new_web_archives(
            temp_dir=config.temp_dir,
            raw_base_dir=config.raw_dir,
            target_date=target_date_override,
            force=force_override,
            limit=limit_override,
        )

        print("\n==================================================")
        print("    SUR EN PRECIOS — DATA HARVESTER SUCCESS       ")
        print("==================================================")
        print(f" Downloaded   : {len(results)} new archive(s)")
        for res in results:
            print(
                f"   • Date: {res['data_date']} | Stored: {res['archive_path'].name} | Extracted: {len(res['extracted_files'])} files"
            )
        print("==================================================")
        print(
            " Tip: Run ETL for the latest date using:\n  uv run python -m sur_en_precios.tools.run_etl\n"
        )

        latest_res = results[-1] if results else {}
        return {
            "downloaded": results,
            "new_count": len(results),
            "total_found": len(discovered),
            "data_date": latest_res.get("data_date"),
            "archive_path": latest_res.get("archive_path"),
            "extracted_files": latest_res.get("extracted_files", []),
        }

    except Exception as exc:
        logger.error(f"Harvesting failed: {exc}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and Harvest SEPA Dataset Archive (parameters configured in config.yaml)"
    )
    parser.add_argument("--workdir", help="Path to working directory")

    args = parser.parse_args()

    workdir_path = Path(args.workdir).resolve() if args.workdir else None

    try:
        asyncio.run(
            run_harvest(
                workdir_override=workdir_path,
                should_create_override=False,
            )
        )
    except Exception as exc:
        print("\n==================================================", file=sys.stderr)
        print("    SUR EN PRECIOS — DATA HARVESTER FAILED        ", file=sys.stderr)
        print("==================================================", file=sys.stderr)
        print(f" Error: {exc}", file=sys.stderr)
        print(
            "\nTip: Check URL or local archive configuration in config.yaml.\n",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
