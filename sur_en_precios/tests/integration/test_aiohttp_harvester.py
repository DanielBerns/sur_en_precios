from pathlib import Path

from sur_en_precios.adapters.harvester import AiohttpScraperAdapter
from sur_en_precios.adapters.storage import FileSystemStorageAdapter


def test_storage_adapter_save_and_extract(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    storage = FileSystemStorageAdapter(raw_dir)

    # Test file saving using pathlib.Path
    file_path = storage.save_raw_archive(b"mock sepa archive content", "test_sepa.zip")
    assert file_path.exists()
    assert file_path.parent == raw_dir


def test_harvester_instantiation() -> None:
    harvester = AiohttpScraperAdapter(
        sepa_url="https://datos.produccion.gob.ar/dataset/sepa-precios"
    )
    assert harvester._sepa_url == "https://datos.produccion.gob.ar/dataset/sepa-precios"
