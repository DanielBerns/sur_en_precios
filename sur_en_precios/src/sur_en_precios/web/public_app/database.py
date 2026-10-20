import logging
from contextlib import contextmanager
from typing import Generator

from flask import current_app
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
    SqlAlchemyUserRepository,
)
from sur_en_precios.domain.models_user import User, UserBase

logger = logging.getLogger("sur_en_precios.public_app.database")


def init_user_db(engine: Engine) -> None:
    """Initializes user database tables using SQLAlchemy 2.0 with safe column checks."""
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            conn.exec_driver_sql("PRAGMA journal_mode = WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout = 5000")

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
    """Yields a managed SQLAlchemy session for the public catalog database."""
    session_factory: sessionmaker[Session] = current_app.extensions[
        "public_session_factory"
    ]
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
