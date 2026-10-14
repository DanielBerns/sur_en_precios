import asyncio
import json
import logging
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from sur_en_precios.domain.ports import ScraperPort

logger = logging.getLogger("sur_en_precios.harvester")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; SurEnPreciosHarvester/0.1.0; "
    "+https://github.com/DanielBerns/sur_en_precios)"
)


def extract_sepa_zip_resources(
    html: str,
    base_url: str = "https://datos.produccion.gob.ar/dataset/sepa-precios",
) -> List[Dict[str, Any]]:
    """Extracts SEPA zip dataset download URLs and metadata from HTML/JSON-LD.

    Parses schema.org JSON-LD definitions first, then falls back to CKAN HTML
    package container structures and generic zip anchors.
    """
    resources: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    # 1. Parse JSON-LD metadata
    json_ld_matches = re.finditer(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for script_match in json_ld_matches:
        try:
            data = json.loads(script_match.group(1))
            graph = data.get("@graph", [data]) if isinstance(data, dict) else data
            if not isinstance(graph, list):
                graph = [graph]

            for item in graph:
                if not isinstance(item, dict):
                    continue

                raw_url = item.get("schema:url") or item.get("url")
                if not raw_url:
                    continue

                resolved_url = urllib.parse.urljoin(base_url, str(raw_url))
                is_zip = (
                    str(item.get("schema:encodingFormat", "")).upper() == "ZIP"
                    or str(item.get("encodingFormat", "")).upper() == "ZIP"
                    or resolved_url.lower().endswith(".zip")
                    or ".zip" in resolved_url.lower()
                )

                if is_zip and resolved_url not in seen_urls:
                    name = str(item.get("schema:name") or item.get("name") or "")
                    desc = str(
                        item.get("schema:description") or item.get("description") or ""
                    )
                    date_val: Optional[date] = None

                    for text_candidate in (desc, name, resolved_url):
                        m = re.search(r"(\d{4}-\d{2}-\d{2})", text_candidate)
                        if m:
                            try:
                                date_val = date.fromisoformat(m.group(1))
                                break
                            except ValueError:
                                pass

                    size_val: Optional[int] = None
                    raw_size = item.get("schema:contentSize") or item.get("contentSize")
                    if raw_size is not None:
                        try:
                            size_val = int(raw_size)
                        except (ValueError, TypeError):
                            pass

                    seen_urls.add(resolved_url)
                    resources.append(
                        {
                            "url": resolved_url,
                            "name": name,
                            "description": desc,
                            "date": date_val,
                            "size": size_val,
                        }
                    )
        except Exception as exc:
            logger.debug("Failed parsing JSON-LD script block: %s", exc)

    # 2. Parse CKAN package-container blocks
    container_matches = re.finditer(
        r"<div\s+class=[\"']pkg-container[\"'].*?(?=<div\s+class=[\"']pkg-container[\"']|$)",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    for block_match in container_matches:
        block = block_match.group(0)
        url_match = re.search(
            r"href=[\"']([^\"']+\.zip[^\"']*)[\"']", block, re.IGNORECASE
        )
        if not url_match:
            continue

        resolved_url = urllib.parse.urljoin(base_url, url_match.group(1))
        if resolved_url in seen_urls:
            continue

        title_match = re.search(r"<h3>(.*?)</h3>", block, re.DOTALL | re.IGNORECASE)
        desc_match = re.search(r"<p>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", block)

        date_val = None
        if date_match:
            try:
                date_val = date.fromisoformat(date_match.group(1))
            except ValueError:
                pass

        name = title_match.group(1).strip() if title_match else Path(resolved_url).name
        desc = desc_match.group(1).strip() if desc_match else ""

        seen_urls.add(resolved_url)
        resources.append(
            {
                "url": resolved_url,
                "name": name,
                "description": desc,
                "date": date_val,
                "size": None,
            }
        )

    # 3. Fallback: Parse any anchor tags linking to .zip files
    anchor_matches = re.finditer(
        r"<a[^>]+href=[\"']([^\"']+\.zip(?:[?#][^\"']*)?)[\"'][^>]*>",
        html,
        re.IGNORECASE,
    )
    for a_match in anchor_matches:
        raw_href = a_match.group(1)
        resolved_url = urllib.parse.urljoin(base_url, raw_href)
        if resolved_url in seen_urls:
            continue

        date_val = None
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", resolved_url)
        if date_match:
            try:
                date_val = date.fromisoformat(date_match.group(1))
            except ValueError:
                pass

        seen_urls.add(resolved_url)
        resources.append(
            {
                "url": resolved_url,
                "name": Path(urllib.parse.urlparse(resolved_url).path).name,
                "description": "",
                "date": date_val,
                "size": None,
            }
        )

    return resources


class AiohttpScraperAdapter(ScraperPort):
    """Asynchronous HTTP scraper adapter using aiohttp to discover and download daily SEPA archives."""

    def __init__(
        self,
        sepa_url: str,
        timeout_seconds: int = 120,
        user_agent: Optional[str] = None,
    ):
        self._sepa_url = sepa_url
        self._timeout = aiohttp.ClientTimeout(
            total=None, sock_read=timeout_seconds, connect=30.0
        )
        self._headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}

    async def fetch_webpage(self, url: Optional[str] = None) -> str:
        """Fetches the webpage HTML content asynchronously."""
        target_url = url or self._sepa_url
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout, headers=self._headers
            ) as session:
                async with session.get(target_url, allow_redirects=True) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to fetch webpage from {target_url}. HTTP status: {response.status}"
                        )
                    return await response.text()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            raise RuntimeError(
                f"Network error while fetching webpage from '{target_url}': {exc}"
            ) from exc

    async def discover_dataset_archives(
        self, url: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Discovers dataset archive resources available on the portal webpage."""
        target_url = url or self._sepa_url
        if target_url.lower().endswith(".zip"):
            date_val = None
            m = re.search(r"(\d{4}-\d{2}-\d{2})", target_url)
            if m:
                try:
                    date_val = date.fromisoformat(m.group(1))
                except ValueError:
                    pass
            return [
                {
                    "url": target_url,
                    "name": Path(urllib.parse.urlparse(target_url).path).name,
                    "description": "",
                    "date": date_val,
                    "size": None,
                }
            ]

        html = await self.fetch_webpage(target_url)
        return extract_sepa_zip_resources(html, base_url=target_url)

    async def download_file(
        self, file_url: str, target_dir: Path, filename: Optional[str] = None
    ) -> Path:
        """Downloads a specific remote file into target_dir."""
        target_dir.mkdir(parents=True, exist_ok=True)
        if filename:
            file_path = target_dir / filename
        else:
            url_path = urllib.parse.urlparse(file_url).path
            name = Path(url_path).name or "sepa_download.zip"
            if not name.endswith(".zip"):
                name = f"{name}.zip"
            file_path = target_dir / name

        temp_path = file_path.with_suffix(".download")

        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout, headers=self._headers
            ) as session:
                async with session.get(file_url, allow_redirects=True) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download file from {file_url}. HTTP status: {response.status}"
                        )

                    with open(temp_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(65536):
                            f.write(chunk)

            if file_path.exists():
                file_path.unlink()
            temp_path.rename(file_path)

        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(
                f"Network timeout or error while downloading file from '{file_url}': {exc}"
            ) from exc
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        return file_path

    async def fetch_daily_dataset(self, target_dir: Path) -> Path:
        """Downloads the latest daily SEPA dataset archive into target_dir."""
        # If sepa_url points directly to a zip file, download directly
        if self._sepa_url.lower().endswith(".zip"):
            return await self.download_file(self._sepa_url, target_dir)

        # Otherwise discover archives from portal webpage
        archives = await self.discover_dataset_archives()
        if not archives:
            raise RuntimeError(
                f"No SEPA zip archive files found on portal webpage: {self._sepa_url}"
            )

        # Sort archives: prioritized by date descending if available
        def sort_key(item: Dict[str, Any]) -> tuple:
            d = item.get("date")
            return (1 if d is not None else 0, d or date.min)

        sorted_archives = sorted(archives, key=sort_key, reverse=True)
        chosen = sorted_archives[0]

        return await self.download_file(chosen["url"], target_dir)
