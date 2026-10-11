import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

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

    async def execute_from_web(self, temp_dir: Path) -> Dict[str, Any]:
        """Downloads daily SEPA dataset archive from web into raw storage."""
        if not self._scraper:
            raise RuntimeError("Scraper adapter is required for web harvesting.")

        self._logger.info(
            "Starting remote SEPA dataset web harvest...",
            extra={"temp_dir": str(temp_dir)},
        )

        downloaded_zip = await self._scraper.fetch_daily_dataset(temp_dir)
        try:
            try:
                data_date = self._sepa_dataset.infer_data_date(downloaded_zip)
            except Exception:
                data_date = date.today()

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
