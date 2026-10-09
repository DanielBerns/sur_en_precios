import logging
from pathlib import Path
from typing import Dict, List

from sur_en_precios.domain.ports import RawStoragePort, ScraperPort


class HarvestDailyDataUseCase:
    """Use case for harvesting daily SEPA dataset archive."""

    def __init__(
        self,
        scraper: ScraperPort,
        storage: RawStoragePort,
        logger: logging.Logger | None = None,
    ):
        self._scraper = scraper
        self._storage = storage
        self._logger = logger or logging.getLogger("sur_en_precios")

    async def execute(self, target_dir: Path) -> Dict[str, Path | List[Path]]:
        """Executes daily harvesting workflow."""
        self._logger.info(
            "Starting daily SEPA dataset harvesting workflow...",
            extra={"target_dir": str(target_dir)},
        )

        archive_path = await self._scraper.fetch_daily_dataset(target_dir)
        extracted_files = self._storage.extract_archive(archive_path)

        self._logger.info(
            "Completed SEPA dataset harvesting successfully.",
            extra={
                "archive_path": str(archive_path),
                "extracted_count": len(extracted_files),
            },
        )

        return {
            "archive_path": archive_path,
            "extracted_files": extracted_files,
        }
