import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import List

from sur_en_precios.domain.ports import RawStoragePort


class FileSystemStorageAdapter(RawStoragePort):
    """Storage adapter managing raw landed daily archive files using pathlib.Path only."""

    def __init__(self, raw_base_dir: Path):
        self._raw_base_dir = raw_base_dir.resolve()
        self._raw_base_dir.mkdir(parents=True, exist_ok=True)

    def save_raw_archive(self, content: bytes, filename: str) -> Path:
        """Saves landed byte stream to file using pathlib.Path."""
        destination = self._raw_base_dir / filename
        destination.parent.mkdir(parents=True, exist_ok=True)

        with open(destination, "wb") as f:
            f.write(content)

        return destination

    def store_archive(self, source_archive: Path, target_date: date) -> Path:
        """Stores or copies archive to raw/<target_date>/sepa_<target_date>.zip."""
        date_str = target_date.strftime("%Y-%m-%d")
        target_dir = self._raw_base_dir / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_zip = target_dir / f"sepa_{date_str}.zip"

        source_resolved = source_archive.resolve()
        dest_resolved = dest_zip.resolve()

        if source_resolved != dest_resolved:
            shutil.copy2(source_resolved, dest_resolved)

        return dest_resolved

    def extract_archive(self, archive_path: Path) -> List[Path]:
        """Extracts .zip archive into an extraction subfolder and returns list of extracted file Paths."""
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive file not found at: {archive_path}")

        target_folder = archive_path.parent / archive_path.stem
        target_folder.mkdir(parents=True, exist_ok=True)

        extracted_files: List[Path] = []

        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(target_folder)
            for name in zip_ref.namelist():
                extracted_path = target_folder / name
                if extracted_path.is_file():
                    extracted_files.append(extracted_path)

        return extracted_files
