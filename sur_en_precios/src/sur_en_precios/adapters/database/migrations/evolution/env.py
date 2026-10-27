"""Alembic environment for the evolution database (evolution.sqlite).

The database URL is taken from the Alembic config (set programmatically by
``upgrade_evolution_schema``). When running the ``alembic`` CLI without a URL,
it falls back to the path configured in the Sur en Precios ``config.yaml``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from sur_en_precios.domain.models_evolution import EvolutionBase

config = context.config
target_metadata = EvolutionBase.metadata


def _resolve_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from sur_en_precios.config import read_config

    app_config = read_config()
    return f"sqlite:///{app_config.get_evolution_db_path()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
