from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from flask import current_app
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.domain.models_public import PublicBase
from sur_en_precios.domain.models_user import User, UserBase
from sur_en_precios.web.public_app.catalog_slots import (
    VALID_SLOTS,
    build_readonly_immutable_uri,
    resolve_active_public_db,
)

logger = logging.getLogger("sur_en_precios.public_app.database")


def build_public_engine(db_path: Path, slot: Optional[str]) -> Engine:
    """Creates a NullPool SQLAlchemy engine for the resolved public catalog database.

    Active Red/Green slots are opened in read-only immutable URI mode to eliminate
    NFS POSIX fcntl lock contention across uWSGI workers. Legacy/local fallback
    databases use standard SQLite connections and initialize empty schemas only if new.
    """
    if slot in VALID_SLOTS:
        uri = build_readonly_immutable_uri(db_path)

        def _connect_readonly() -> sqlite3.Connection:
            return sqlite3.connect(
                uri,
                uri=True,
                timeout=30.0,
                check_same_thread=False,
            )

        return create_engine(
            "sqlite://",
            creator=_connect_readonly,
            poolclass=NullPool,
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    need_schema_init = not db_path.exists() or db_path.stat().st_size == 0
    engine = create_engine(
        f"sqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={"timeout": 30.0},
    )
    if need_schema_init:
        PublicBase.metadata.create_all(engine)
    return engine


def ensure_public_session_factory(app: Any) -> sessionmaker[Session]:
    """Ensures the current worker's SQLAlchemy session factory points to the active Red/Green slot."""
    config = app.config["APP_CONFIG"]
    active_path, active_slot = resolve_active_public_db(config)
    inode = active_path.stat().st_ino if active_path.exists() else 0
    desired_key = (active_path, active_slot, inode)

    current_key = app.extensions.get("public_db_bound_key")
    existing_factory: Optional[sessionmaker[Session]] = app.extensions.get(
        "public_session_factory"
    )

    if current_key == desired_key and existing_factory is not None:
        return existing_factory

    old_engine: Optional[Engine] = app.extensions.get("public_engine")
    if old_engine is not None:
        try:
            old_engine.dispose()
        except Exception:
            pass

    new_engine = build_public_engine(active_path, active_slot)
    new_factory = sessionmaker(bind=new_engine, autoflush=False, expire_on_commit=False)

    # Re-stat in case legacy schema creation materialized a new file inode
    final_inode = active_path.stat().st_ino if active_path.exists() else 0
    app.config["PUBLIC_ENGINE"] = new_engine
    app.extensions["public_engine"] = new_engine
    app.extensions["public_session_factory"] = new_factory
    app.extensions["public_db_bound_key"] = (active_path, active_slot, final_inode)

    if current_key is not None:
        logger.info(
            "Worker rebound public catalog engine to %s (slot=%s)",
            active_path.name,
            active_slot or "legacy",
        )

    return new_factory


def init_user_db(engine: Engine) -> None:
    """Initializes user database tables using SQLAlchemy 2.0 with safe column checks."""
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            conn.exec_driver_sql("PRAGMA busy_timeout = 30000")
            conn.exec_driver_sql("PRAGMA journal_mode = DELETE")

            # Verify and adapt basket_items schema if existing
            res = conn.exec_driver_sql("PRAGMA table_info(basket_items)").fetchall()
            existing_cols = {row[1] for row in res}
            if existing_cols:
                if "selected" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN selected BOOLEAN NOT NULL DEFAULT 1"
                    )
                if "numerator" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN numerator INTEGER NOT NULL DEFAULT 1"
                    )
                if "denominator" not in existing_cols:
                    conn.exec_driver_sql(
                        "ALTER TABLE basket_items ADD COLUMN denominator INTEGER NOT NULL DEFAULT 1"
                    )

            # Verify and adapt baskets schema if existing
            res_b = conn.exec_driver_sql("PRAGMA table_info(baskets)").fetchall()
            existing_b = {row[1] for row in res_b}
            if existing_b:
                if "is_public" not in existing_b:
                    conn.exec_driver_sql(
                        "ALTER TABLE baskets ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0"
                    )
                if "uuid" not in existing_b:
                    conn.exec_driver_sql(
                        "ALTER TABLE baskets ADD COLUMN uuid VARCHAR(36)"
                    )

            # Verify and adapt users schema if existing
            res_u = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
            existing_u = {row[1] for row in res_u}
            if existing_u:
                if "username" not in existing_u:
                    conn.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN username VARCHAR(50)"
                    )
                    conn.exec_driver_sql(
                        "UPDATE users SET username = email WHERE username IS NULL"
                    )
                if "is_admin" not in existing_u:
                    conn.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"
                    )
                if "is_active" not in existing_u:
                    conn.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
                    )
                if "last_login_at" not in existing_u:
                    conn.exec_driver_sql(
                        "ALTER TABLE users ADD COLUMN last_login_at DATETIME"
                    )
    except Exception as exc:
        logger.warning("Could not set pragmas or verify schema: %s", exc)

    UserBase.metadata.create_all(engine)


def get_or_create_demo_user(user_repo: SqlAlchemyUserRepository) -> User:
    """Retrieves or creates default demo user for public sessions or testing."""
    user = user_repo.get_user_by_username("demo@surenprecios.ar")
    if not user:
        user = user_repo.create_user(
            username="demo@surenprecios.ar", password_hash="dummy_hash", is_admin=False
        )
    return user


@contextmanager
def get_public_session() -> Generator[Session, None, None]:
    """Yields a managed SQLAlchemy session for the active public catalog database."""
    session_factory = ensure_public_session_factory(current_app)
    with session_factory() as session:
        yield session


@contextmanager
def get_user_session() -> Generator[Session, None, None]:
    """Yields a managed SQLAlchemy session for the user database."""
    session_factory: sessionmaker[Session] = current_app.extensions[
        "user_session_factory"
    ]
    with session_factory() as session:
        yield session


def get_catalog_repository(session: Session) -> SqlAlchemyCatalogRepository:
    """Factory creating catalog repository bound to session."""
    return SqlAlchemyCatalogRepository(session)


def get_price_repository(session: Session) -> SqlAlchemyPriceRepository:
    """Factory creating price repository bound to session."""
    return SqlAlchemyPriceRepository(session)


def get_user_repository(session: Session) -> SqlAlchemyUserRepository:
    """Factory creating user repository bound to session."""
    return SqlAlchemyUserRepository(session)
