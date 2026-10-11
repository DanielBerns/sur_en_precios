import asyncio
from pathlib import Path

import aiohttp

from sur_en_precios.domain.ports import ScraperPort


class AiohttpScraperAdapter(ScraperPort):
    """Asynchronous HTTP scraper adapter using aiohttp to download daily SEPA archives."""

    def __init__(self, sepa_url: str, timeout_seconds: int = 120):
        self._sepa_url = sepa_url
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=30.0)

    async def fetch_daily_dataset(self, target_dir: Path) -> Path:
        """Downloads daily SEPA dataset archive into target_dir using aiohttp and pathlib.Path."""
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "sepa_download.zip"

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(
                    self._sepa_url, allow_redirects=True
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download SEPA dataset from {self._sepa_url}. HTTP status: {response.status}"
                        )

                    with open(file_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(65536):
                            f.write(chunk)

        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            raise RuntimeError(
                f"Network timeout or error while downloading SEPA dataset from '{self._sepa_url}': {exc}"
            ) from exc

        return file_path
