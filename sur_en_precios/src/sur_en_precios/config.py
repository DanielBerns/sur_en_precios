import argparse
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


class AppSettings(BaseModel):
    name: str = "Sur en Precios"
    region: str = "AR-B"
    debug: bool = False


class DatabaseSettings(BaseModel):
    # Databases stored outside code in working directory data folder
    public_db_filename: str = "public.sqlite"
    user_db_filename: str = "user_data.sqlite"
    control_db_filename: str = "control.sqlite"


class ScraperSettings(BaseModel):
    sepa_url: str = "https://datos.produccion.gob.ar/dataset/sepa-precios"
    raw_storage_dir: str = "data/raw"
    timeout_seconds: int = 120
    target_date: str | None = None
    local_archive_file: str | None = None


class LoggingSettings(BaseModel):
    level: str = "INFO"
    log_dir: str = "logs"
    max_bytes: int = 10_485_760  # 10MB
    backup_count: int = 5


class EtlSettings(BaseModel):
    temp_dir: str = "data/tmp"
    insert_batch_size: int = 10_000
    target_date: str | None = None


class LogAnalyzerSettings(BaseModel):
    level: str | None = None
    search: str | None = None
    date: str | None = None
    limit: int = 50
    summary: bool = False


class SyncSettings(BaseModel):
    sync_to_web: bool = False
    server_url: str = "https://surenprecios.pythonanywhere.com"
    api_token: str = "sur_precios_sync_secret_token_change_in_production"
    chunk_size_bytes: int = 2_097_152  # 2MB chunks
    timeout_seconds: int = 900  # 15 minutes
    staging_dir: str = "data/tmp/sync"


class AppConfig(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    etl: EtlSettings = Field(default_factory=EtlSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    log_analyzer: LogAnalyzerSettings = Field(default_factory=LogAnalyzerSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)


class Config:
    """Central configuration manager for Sur en Precios."""

    def __init__(self, settings: AppConfig, workdir: Path):
        self._settings = settings
        self._workdir = workdir

    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def data_dir(self) -> Path:
        path = self._workdir / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def raw_dir(self) -> Path:
        path = self._workdir / self._settings.scraper.raw_storage_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def temp_dir(self) -> Path:
        path = self._workdir / self._settings.etl.temp_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_dir(self) -> Path:
        path = self._workdir / self._settings.logging.log_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_public_db_path(self) -> Path:
        return self.data_dir / self._settings.database.public_db_filename

    def get_user_db_path(self) -> Path:
        return self.data_dir / self._settings.database.user_db_filename

    def get_control_db_path(self) -> Path:
        return self.data_dir / self._settings.database.control_db_filename

    def get_app_name(self) -> str:
        return self._settings.app.name

    def get_region(self) -> str:
        return self._settings.app.region

    def get_log_level(self) -> str:
        return self._settings.logging.level

    def get_etl_settings(self) -> EtlSettings:
        return self._settings.etl

    def get_scraper_settings(self) -> ScraperSettings:
        return self._settings.scraper

    def get_log_analyzer_settings(self) -> LogAnalyzerSettings:
        return self._settings.log_analyzer

    def get_sync_settings(self) -> SyncSettings:
        return self._settings.sync

    @property
    def sync_staging_dir(self) -> Path:
        path = self._workdir / self._settings.sync.staging_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def settings(self) -> AppConfig:
        return self._settings


def resolve_working_directory() -> tuple[Path, bool]:
    """Resolves working directory via CLI --workdir, env var, or default ~/Info/sur_en_precios."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workdir", help="Path to working directory")
    parser.add_argument(
        "--create", action="store_true", help="Create default config if missing"
    )
    args, _ = parser.parse_known_args()

    workdir_str = os.environ.get("WORKING_DIRECTORY")
    if args.workdir:
        workdir_str = args.workdir

    if workdir_str:
        workdir_path = Path(workdir_str).expanduser().resolve()
    else:
        workdir_path = (Path.home() / "Info" / "sur_en_precios").resolve()

    return workdir_path, bool(args.create)


def read_config(
    workdir_override: Path | None = None, should_create_override: bool | None = None
) -> Config:
    """Reads, parses, and validates config.yaml located in the working directory."""
    if workdir_override is not None:
        workdir_path = workdir_override
        should_create = (
            should_create_override if should_create_override is not None else False
        )
    else:
        workdir_path, should_create = resolve_working_directory()

    config_path = workdir_path / "config.yaml"

    if not config_path.exists():
        if should_create:
            default_config = AppConfig()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(default_config.model_dump(), f, default_flow_style=False)
        else:
            raise FileNotFoundError(
                f"Configuration file not found at {config_path}. Use --create flag to generate default."
            )

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    try:
        app_config = AppConfig(**data)
        config_obj = Config(app_config, workdir_path)
        if should_create:
            _ = config_obj.data_dir
            _ = config_obj.raw_dir
            _ = config_obj.log_dir
        return config_obj
    except ValidationError as err:
        raise ValueError(
            f"Invalid configuration format in {config_path}: {err}"
        ) from err
