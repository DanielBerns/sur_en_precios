import re
import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import List

from sur_en_precios.domain.ports import SepaDatasetPort


class SepaArchiveError(Exception):
    """Exception raised when processing a SEPA archive fails."""

    pass


class ZipSepaDatasetAdapter(SepaDatasetPort):
    """Adapter for reading and extracting SEPA dataset zip archives."""

    DATE_FOLDER_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2})/")
    DATE_FILENAME_REGEX = re.compile(r"(\d{4}-\d{2}-\d{2})")

    def infer_data_date(self, archive_path: Path) -> date:
        """Infers the price date (YYYY-MM-DD) from archive contents or filename."""
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive file not found: {archive_path}")

        if archive_path.is_file() and archive_path.suffix == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for name in zf.namelist():
                        match = self.DATE_FOLDER_REGEX.match(name)
                        if match:
                            return date.fromisoformat(match.group(1))

                    for name in zf.namelist():
                        match = self.DATE_FILENAME_REGEX.search(name)
                        if match:
                            return date.fromisoformat(match.group(1))
            except zipfile.BadZipFile as exc:
                raise SepaArchiveError(f"Corrupt zip archive: {archive_path}") from exc

        # Fallback to archive filename
        match = self.DATE_FILENAME_REGEX.search(archive_path.name)
        if match:
            return date.fromisoformat(match.group(1))

        raise ValueError(f"Could not infer data date from archive: {archive_path}")

    def list_chain_archives(self, raw_date_dir: Path) -> List[Path]:
        """Lists all inner chain archive files or directories within a raw date folder."""
        if not raw_date_dir.exists():
            return []

        chain_files: List[Path] = []

        # Search recursively for zip files matching chain pattern
        for path in sorted(raw_date_dir.rglob("*.zip")):
            if "sepa_" in path.name and "comercio" in path.name:
                chain_files.append(path)

        # If no inner zips found, check if there are subdirectories with CSVs or top-level CSVs
        if not chain_files:
            for sub_dir in sorted(raw_date_dir.rglob("*")):
                if sub_dir.is_dir() and (
                    (sub_dir / "sucursales.csv").exists()
                    or (sub_dir / "productos.csv").exists()
                ):
                    chain_files.append(sub_dir)

            # Fallback for flat CSV directory structure
            if not chain_files and (
                (raw_date_dir / "sucursales.csv").exists()
                or (raw_date_dir / "productos.csv").exists()
            ):
                chain_files.append(raw_date_dir)

        return chain_files

    def extract_member(
        self, chain_archive: Path, member_name: str, dest_dir: Path
    ) -> Path:
        """Extracts a specific CSV member from a chain archive or directory into dest_dir."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        target_path = dest_dir / member_name

        if chain_archive.is_dir():
            src_file = chain_archive / member_name
            if not src_file.exists():
                raise FileNotFoundError(
                    f"Member '{member_name}' not found in directory: {chain_archive}"
                )
            if src_file != target_path:
                shutil.copy(src_file, target_path)
            return target_path

        if chain_archive.is_file() and chain_archive.suffix == ".zip":
            try:
                with zipfile.ZipFile(chain_archive, "r") as zf:
                    matched_name = None
                    for name in zf.namelist():
                        if Path(name).name.lower() == member_name.lower():
                            matched_name = name
                            break

                    if not matched_name:
                        raise FileNotFoundError(
                            f"Member '{member_name}' not found in zip archive: {chain_archive}"
                        )

                    with (
                        zf.open(matched_name, "r") as src,
                        open(target_path, "wb") as dst,
                    ):
                        shutil.copyfileobj(src, dst)
                    return target_path

            except zipfile.BadZipFile as exc:
                raise SepaArchiveError(
                    f"Bad zip file when reading member '{member_name}' from {chain_archive}"
                ) from exc

        raise FileNotFoundError(
            f"Chain archive path invalid or member missing: {chain_archive}"
        )
