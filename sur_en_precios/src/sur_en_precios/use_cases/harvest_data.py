import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from sur_en_precios.adapters.sepa_archive import ZipSepaDatasetAdapter
from sur_en_precios.domain.ports import RawStoragePort, ScraperPort, SepaDatasetPort


class HarvestDailyDataUseCase:
    """Use case for harvesting daily SEPA dataset archives from remote web or local files."""

    def __init__(
        self,
        storage: RawStoragePort,
        scraper: Optional[ScraperPort] = None,
        sepa_dataset_adapter: Optional[SepaDatasetPort] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._storage = storage
        self._scraper = scraper
        self._sepa_dataset = sepa_dataset_adapter or ZipSepaDatasetAdapter()
        self._logger = logger or logging.getLogger("sur_en_precios")

    def execute_from_file(self, local_file: Path) -> Dict[str, Any]:
        """Harvests a local SEPA zip archive file into raw storage."""
        if not local_file.exists():
            raise FileNotFoundError(f"Local file not found at: {local_file}")

        self._logger.info(
            "Harvesting local SEPA dataset archive file...",
            extra={"local_file": str(local_file)},
        )

        data_date = self._sepa_dataset.infer_data_date(local_file)
        dest_archive = self._storage.store_archive(local_file, data_date)
        extracted_files = self._storage.extract_archive(dest_archive)

        self._logger.info(
            "Completed local SEPA dataset harvesting successfully.",
            extra={
                "data_date": str(data_date),
                "archive_path": str(dest_archive),
                "extracted_count": len(extracted_files),
            },
        )

        return {
            "data_date": data_date,
            "archive_path": dest_archive,
            "extracted_files": extracted_files,
        }

    async def discover_web_archives(
        self, page_url: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Discovers dataset archives available on the remote SEPA portal."""
        if not self._scraper:
            raise RuntimeError("Scraper adapter is required for web harvesting.")

        if hasattr(self._scraper, "discover_dataset_archives"):
            archives = await self._scraper.discover_dataset_archives(page_url)

            def sort_key(item: Dict[str, Any]) -> tuple:
                d = item.get("date")
                return (1 if d is not None else 0, d or date.min)

            return sorted(archives, key=sort_key, reverse=True)

        return []

    async def harvest_new_web_archives(
        self,
        temp_dir: Path,
        raw_base_dir: Optional[Path] = None,
        target_date: Optional[date] = None,
        force: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Searches the SEPA portal webpage for new zip files and downloads them automatically.

        A file is considered new if its archive does not already exist in raw_base_dir
        for that date (unless force=True).
        """
        if not self._scraper:
            raise RuntimeError("Scraper adapter is required for web harvesting.")

        self._logger.info(
            "Scanning SEPA portal webpage for dataset archives...",
            extra={"temp_dir": str(temp_dir), "target_date": str(target_date)},
        )

        discovered = await self.discover_web_archives()
        base_dir = raw_base_dir or getattr(self._storage, "_raw_base_dir", None)

        # Filter by target date if specified
        if target_date is not None:
            discovered = [
                item for item in discovered if item.get("date") == target_date
            ]
            if not discovered:
                self._logger.warning(
                    f"No SEPA archive found on portal for target date: {target_date}"
                )

        harvested_results: List[Dict[str, Any]] = []

        for item in discovered:
            if limit is not None and len(harvested_results) >= limit:
                break

            item_date = item.get("date")
            item_url = item["url"]
            item_name = item.get("name") or Path(item_url).name

            # Check if archive already exists locally in raw storage
            if item_date is not None and base_dir is not None:
                date_str = item_date.strftime("%Y-%m-%d")
                existing_archive = base_dir / date_str / f"sepa_{date_str}.zip"
                if (
                    existing_archive.exists()
                    and existing_archive.stat().st_size > 0
                    and not force
                ):
                    self._logger.info(
                        f"SEPA archive for {date_str} already exists in raw storage, skipping.",
                        extra={"date": date_str, "url": item_url},
                    )
                    continue

            self._logger.info(
                f"Downloading new SEPA archive: {item_name} ({item_date or 'unknown date'})...",
                extra={"url": item_url, "date": str(item_date)},
            )

            # Download archive into temp_dir
            if hasattr(self._scraper, "download_file"):
                downloaded_zip = await self._scraper.download_file(item_url, temp_dir)
            else:
                downloaded_zip = await self._scraper.fetch_daily_dataset(temp_dir)

            try:
                try:
                    data_date = self._sepa_dataset.infer_data_date(downloaded_zip)
                except Exception:
                    data_date = item_date or date.today()

                # Second check if date was previously unknown
                if item_date is None and base_dir is not None and not force:
                    date_str = data_date.strftime("%Y-%m-%d")
                    existing_archive = base_dir / date_str / f"sepa_{date_str}.zip"
                    if (
                        existing_archive.exists()
                        and existing_archive.stat().st_size > 0
                    ):
                        self._logger.info(
                            f"Inferred date {date_str} already exists in raw storage, skipping.",
                            extra={"date": date_str, "url": item_url},
                        )
                        continue

                dest_archive = self._storage.store_archive(downloaded_zip, data_date)
                extracted_files = self._storage.extract_archive(dest_archive)

                self._logger.info(
                    f"Successfully harvested SEPA dataset for {data_date}.",
                    extra={
                        "data_date": str(data_date),
                        "archive_path": str(dest_archive),
                        "extracted_count": len(extracted_files),
                        "url": item_url,
                    },
                )

                harvested_results.append(
                    {
                        "data_date": data_date,
                        "archive_path": dest_archive,
                        "extracted_files": extracted_files,
                        "url": item_url,
                        "name": item_name,
                    }
                )

            finally:
                if downloaded_zip.exists():
                    downloaded_zip.unlink()

        return harvested_results

    async def execute_from_web(
        self,
        temp_dir: Path,
        target_date: Optional[date] = None,
        download_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Downloads daily SEPA dataset archive from web into raw storage."""
        if not self._scraper:
            raise RuntimeError("Scraper adapter is required for web harvesting.")

        self._logger.info(
            "Starting remote SEPA dataset web harvest...",
            extra={"temp_dir": str(temp_dir)},
        )

        if download_url and hasattr(self._scraper, "download_file"):
            downloaded_zip = await self._scraper.download_file(download_url, temp_dir)
        elif hasattr(self._scraper, "discover_dataset_archives"):
            results = await self.harvest_new_web_archives(
                temp_dir=temp_dir,
                target_date=target_date,
                force=True,
                limit=1,
            )
            if results:
                return results[0]
            downloaded_zip = await self._scraper.fetch_daily_dataset(temp_dir)
        else:
            downloaded_zip = await self._scraper.fetch_daily_dataset(temp_dir)

        try:
            try:
                data_date = self._sepa_dataset.infer_data_date(downloaded_zip)
            except Exception:
                data_date = target_date or date.today()

            dest_archive = self._storage.store_archive(downloaded_zip, data_date)
            extracted_files = self._storage.extract_archive(dest_archive)
        finally:
            if downloaded_zip.exists():
                downloaded_zip.unlink()

        self._logger.info(
            "Completed remote SEPA dataset web harvest successfully.",
            extra={
                "data_date": str(data_date),
                "archive_path": str(dest_archive),
                "extracted_count": len(extracted_files),
            },
        )

        return {
            "data_date": data_date,
            "archive_path": dest_archive,
            "extracted_files": extracted_files,
        }

    async def execute(self, target_dir: Path) -> Dict[str, Any]:
        """Backwards compatibility wrapper for web harvest into target_dir."""
        if self._scraper:
            downloaded = await self._scraper.fetch_daily_dataset(target_dir)
            extracted = self._storage.extract_archive(downloaded)
            return {
                "archive_path": downloaded,
                "extracted_files": extracted,
            }
        raise RuntimeError("No scraper configured.")
