import io
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sur_en_precios.adapters.harvester import (
    AiohttpScraperAdapter,
    extract_sepa_zip_resources,
)
from sur_en_precios.adapters.storage import FileSystemStorageAdapter
from sur_en_precios.tools.run_harvest import run_harvest
from sur_en_precios.use_cases.harvest_data import HarvestDailyDataUseCase

SAMPLE_CKAN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <script type="application/ld+json">
    {
        "@context": "http://schema.org/",
        "@graph": [
            {
                "@type": "schema:DataDownload",
                "schema:name": "Lunes",
                "schema:description": "Precios SEPA Minoristas lunes, 2026-10-12",
                "schema:encodingFormat": "ZIP",
                "schema:contentSize": 323992464,
                "schema:url": "https://datos.produccion.gob.ar/dataset/resource/1/download/sepa_lunes.zip"
            },
            {
                "@type": "schema:DataDownload",
                "schema:name": "Martes",
                "schema:description": "Precios SEPA Minoristas martes, 2026-10-13",
                "schema:encodingFormat": "ZIP",
                "schema:contentSize": 309719021,
                "schema:url": "https://datos.produccion.gob.ar/dataset/resource/2/download/sepa_martes.zip"
            },
            {
                "@type": "schema:DataDownload",
                "schema:name": "Provincias",
                "schema:description": "Excel maestro",
                "schema:encodingFormat": "XLSX",
                "schema:url": "https://datos.produccion.gob.ar/dataset/resource/3/download/maestro.xlsx"
            }
        ]
    }
    </script>
</head>
<body>
    <div class="pkg-container">
        <div class="pkg-actions">
            <a href="https://datos.produccion.gob.ar/dataset/resource/1/download/sepa_lunes.zip"><button>DESCARGAR</button></a>
        </div>
        <div class="package-info">
            <h3>Lunes</h3>
            <p>Precios SEPA Minoristas lunes, 2026-10-12</p>
        </div>
    </div>
    <div class="pkg-container">
        <div class="pkg-actions">
            <a href="https://datos.produccion.gob.ar/dataset/resource/4/download/sepa_domingo.zip"><button>DESCARGAR</button></a>
        </div>
        <div class="package-info">
            <h3>Domingo</h3>
            <p>Precios SEPA Minoristas domingo, 2026-10-11</p>
        </div>
    </div>
    <div class="raw-fallback">
        <a href="/dataset/resource/5/download/sepa_sabado_2026-10-10.zip">Descargar Sabado</a>
    </div>
</body>
</html>
"""


def create_test_zip_bytes(data_date_str: str) -> bytes:
    """Creates in-memory zip bytes containing a SEPA-like inner folder and CSV."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{data_date_str}/comercio.csv", "id_comercio|id_bandera\n1|1\n")
        zf.writestr(
            f"{data_date_str}/sucursales.csv", "id_comercio|id_sucursal\n1|s1\n"
        )
    return buf.getvalue()


def test_storage_adapter_save_and_extract(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    storage = FileSystemStorageAdapter(raw_dir)

    file_path = storage.save_raw_archive(b"mock sepa archive content", "test_sepa.zip")
    assert file_path.exists()
    assert file_path.parent == raw_dir


def test_harvester_instantiation() -> None:
    harvester = AiohttpScraperAdapter(
        sepa_url="https://datos.produccion.gob.ar/dataset/sepa-precios"
    )
    assert harvester._sepa_url == "https://datos.produccion.gob.ar/dataset/sepa-precios"


def test_extract_sepa_zip_resources() -> None:
    resources = extract_sepa_zip_resources(
        SAMPLE_CKAN_HTML,
        base_url="https://datos.produccion.gob.ar/dataset/sepa-precios",
    )

    # Must extract the 4 zip files and exclude maestro.xlsx
    assert len(resources) == 4
    urls = [r["url"] for r in resources]
    assert (
        "https://datos.produccion.gob.ar/dataset/resource/1/download/sepa_lunes.zip"
        in urls
    )
    assert (
        "https://datos.produccion.gob.ar/dataset/resource/2/download/sepa_martes.zip"
        in urls
    )
    assert (
        "https://datos.produccion.gob.ar/dataset/resource/4/download/sepa_domingo.zip"
        in urls
    )
    assert (
        "https://datos.produccion.gob.ar/dataset/resource/5/download/sepa_sabado_2026-10-10.zip"
        in urls
    )

    # Dates must be inferred accurately
    dates = {r["name"]: r["date"] for r in resources}
    assert dates["Lunes"] == date(2026, 10, 12)
    assert dates["Martes"] == date(2026, 10, 13)
    assert dates["Domingo"] == date(2026, 10, 11)


def test_harvest_new_web_archives_downloads_only_new(tmp_path: Path) -> None:
    async def _test() -> None:
        raw_dir = tmp_path / "data" / "raw"
        temp_dir = tmp_path / "data" / "tmp"
        raw_dir.mkdir(parents=True)
        temp_dir.mkdir(parents=True)

        # Pre-populate Lunes (2026-10-12) as ALREADY stored in raw_dir
        lunes_dir = raw_dir / "2026-10-12"
        lunes_dir.mkdir(parents=True)
        (lunes_dir / "sepa_2026-10-12.zip").write_bytes(
            create_test_zip_bytes("2026-10-12")
        )

        storage = FileSystemStorageAdapter(raw_dir)
        scraper = AiohttpScraperAdapter(
            sepa_url="https://datos.produccion.gob.ar/dataset/sepa-precios"
        )

        # Mock fetch_webpage and download_file
        scraper.fetch_webpage = AsyncMock(return_value=SAMPLE_CKAN_HTML)  # type: ignore

        async def mock_download_file(
            file_url: str, target_dir: Path, filename: str | None = None
        ) -> Path:
            target_dir.mkdir(parents=True, exist_ok=True)
            if "martes" in file_url:
                d_str = "2026-10-13"
            elif "domingo" in file_url:
                d_str = "2026-10-11"
            else:
                d_str = "2026-10-10"
            dest = target_dir / f"download_{d_str}.zip"
            dest.write_bytes(create_test_zip_bytes(d_str))
            return dest

        scraper.download_file = AsyncMock(side_effect=mock_download_file)  # type: ignore

        use_case = HarvestDailyDataUseCase(storage=storage, scraper=scraper)

        # First run: should download 3 new files (Martes, Domingo, Sabado), skipping Lunes
        results = await use_case.harvest_new_web_archives(
            temp_dir=temp_dir, raw_base_dir=raw_dir
        )

        assert len(results) == 3
        harvested_dates = {r["data_date"] for r in results}
        assert date(2026, 10, 12) not in harvested_dates
        assert date(2026, 10, 13) in harvested_dates
        assert date(2026, 10, 11) in harvested_dates
        assert date(2026, 10, 10) in harvested_dates

        # Verify archives are properly stored and extracted
        assert (raw_dir / "2026-10-13" / "sepa_2026-10-13.zip").exists()
        assert (raw_dir / "2026-10-11" / "sepa_2026-10-11.zip").exists()
        assert (raw_dir / "2026-10-10" / "sepa_2026-10-10.zip").exists()

        # Second run: everything is now stored, so 0 new files should be downloaded
        results_second = await use_case.harvest_new_web_archives(
            temp_dir=temp_dir, raw_base_dir=raw_dir
        )
        assert len(results_second) == 0

    import asyncio

    asyncio.run(_test())


def test_run_harvest_end_to_end_flow(tmp_path: Path) -> None:
    async def _test() -> None:
        workdir = tmp_path / "workdir"

        async def mock_download_file(
            file_url: str, target_dir: Path, filename: str | None = None
        ) -> Path:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / "temp_download.zip"
            dest.write_bytes(create_test_zip_bytes("2026-10-13"))
            return dest

        with (
            patch.object(
                AiohttpScraperAdapter, "fetch_webpage", new_callable=AsyncMock
            ) as mock_webpage,
            patch.object(
                AiohttpScraperAdapter, "download_file", new_callable=AsyncMock
            ) as mock_download,
        ):
            mock_webpage.return_value = SAMPLE_CKAN_HTML
            mock_download.side_effect = mock_download_file

            # Run harvest targeting 2026-10-13 specifically
            result = await run_harvest(
                workdir_override=workdir,
                should_create_override=True,
                target_date_override=date(2026, 10, 13),
            )

            assert result["new_count"] == 1
            assert result["data_date"] == date(2026, 10, 13)
            assert Path(result["archive_path"]).exists()
            assert len(result["extracted_files"]) >= 2

    import asyncio

    asyncio.run(_test())
