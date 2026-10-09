from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from sur_en_precios.domain.ports import ScraperPort


class AiohttpScraperAdapter(ScraperPort):
    """Asynchronous HTTP scraper adapter using aiohttp to download daily SEPA archives."""

    def __init__(self, sepa_url: str, timeout_seconds: int = 120):
        self._sepa_url = sepa_url
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def fetch_daily_dataset(self, target_dir: Path) -> Path:
        """Downloads daily SEPA dataset archive into target_dir using aiohttp and pathlib.Path."""
        target_dir.mkdir(parents=True, exist_ok=True)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = target_dir / f"sepa_{today_str}.zip"

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.get(self._sepa_url) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"Failed to download SEPA dataset from {self._sepa_url}. HTTP status: {response.status}"
                    )

                content = await response.read()

        with open(file_path, "wb") as f:
            f.write(content)

        return file_path
