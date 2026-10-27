"""Engine factory and Alembic schema management for ``evolution.sqlite``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event

logger = logging.getLogger(__name__)

__all__ = [
    "EVOLUTION_MIGRATIONS_DIR",
    "build_alembic_config",
    "create_evolution_engine",
    "upgrade_evolution_schema",
]

EVOLUTION_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations" / "evolution"


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{Path(db_path).expanduser().resolve()}"


def create_evolution_engine(db_path: Path) -> Engine:
    """Creates a SQLAlchemy engine for evolution.sqlite with project pragmas.

    Uses rollback-journal mode (consistent with the other mutable databases),
    foreign key enforcement and a busy timeout for concurrent CLI usage.
    """
    resolved = Path(db_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(_sqlite_url(resolved))

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode = DELETE")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.close()

    return engine


def build_alembic_config(db_path: Path) -> AlembicConfig:
    """Builds an in-memory Alembic config targeting the given database."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(EVOLUTION_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _sqlite_url(db_path))
    return cfg


def upgrade_evolution_schema(db_path: Path) -> None:
    """Applies all pending Alembic migrations (``alembic upgrade head``)."""
    resolved = Path(db_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Upgrading evolution schema", extra={"db_path": str(resolved)})
    command.upgrade(build_alembic_config(resolved), "head")
