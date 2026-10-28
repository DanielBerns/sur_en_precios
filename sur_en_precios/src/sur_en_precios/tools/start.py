"""Workdir initialization tool for Sur en Precios.

Creates config.yaml, sets up required directories, and initializes SQLite databases.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine

from sur_en_precios.adapters.database.evolution_db import upgrade_evolution_schema
from sur_en_precios.config import (
    AppConfig,
    Config,
    read_config,
    resolve_working_directory,
)
from sur_en_precios.domain.models_public import PublicBase
from sur_en_precios.web.control_app.app import ControlBase
from sur_en_precios.web.public_app.database import init_user_db

logger = logging.getLogger(__name__)

__all__ = [
    "init_workdir",
    "main",
]


def init_workdir(workdir: Path | str | None = None) -> Config:
    """Initializes working directory, creates config.yaml, directories, and SQLite databases."""
    if workdir is not None:
        workdir_path = Path(workdir).expanduser().resolve()
    else:
        workdir_path = resolve_working_directory()

    workdir_path.mkdir(parents=True, exist_ok=True)

    # 1. Create config.yaml if it does not already exist
    config_path = workdir_path / "config.yaml"
    if not config_path.exists():
        default_config = AppConfig()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(default_config.model_dump(), f, default_flow_style=False)
        logger.info("Created default configuration at %s", config_path)
    else:
        logger.info("Existing configuration found at %s", config_path)

    # 2. Read and parse configuration
    config = read_config(workdir_override=workdir_path, should_create_override=True)

    # 3. Create required directories
    directories = [
        config.data_dir,
        config.raw_dir,
        config.temp_dir,
        config.log_dir,
        config.baskets_dir,
        config.sync_staging_dir,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    logger.info("Verified/created workdir directories")

    # 4. Initialize SQLite databases
    # 4.1 Public catalog database (public.sqlite)
    public_db_path = config.get_public_db_path()
    public_engine = create_engine(f"sqlite:///{public_db_path}")
    try:
        PublicBase.metadata.create_all(public_engine)
    finally:
        public_engine.dispose()
    logger.info("Initialized public database at %s", public_db_path)

    # 4.2 User accounts and saved baskets database (user_data.sqlite)
    user_db_path = config.get_user_db_path()
    user_engine = create_engine(f"sqlite:///{user_db_path}")
    try:
        init_user_db(user_engine)
    finally:
        user_engine.dispose()
    logger.info("Initialized user database at %s", user_db_path)

    # 4.3 Scraper logging and control database (control.sqlite)
    control_db_path = config.get_control_db_path()
    control_engine = create_engine(f"sqlite:///{control_db_path}")
    try:
        ControlBase.metadata.create_all(control_engine)
    finally:
        control_engine.dispose()
    logger.info("Initialized control database at %s", control_db_path)

    # 4.4 Evolution tracking database (evolution.sqlite via Alembic)
    evolution_db_path = config.get_evolution_db_path()
    upgrade_evolution_schema(evolution_db_path)
    logger.info("Initialized evolution database at %s", evolution_db_path)

    # 5. User-facing summary output
    print("==================================================")
    print("     SUR EN PRECIOS — WORKDIR INITIALIZED         ")
    print("==================================================")
    print(f" Working Directory : {workdir_path}")
    print(f" Config File       : {config_path}")
    print(" Directories       :")
    print(f"   • Data          : {config.data_dir}")
    print(f"   • Raw Storage   : {config.raw_dir}")
    print(f"   • Temp Storage  : {config.temp_dir}")
    print(f"   • Logs          : {config.log_dir}")
    print(f"   • Baskets       : {config.baskets_dir}")
    print(f"   • Staging       : {config.sync_staging_dir}")
    print(" Databases Initialized:")
    print(f"   • Public DB     : {public_db_path.name}")
    print(f"   • User Data DB  : {user_db_path.name}")
    print(f"   • Control DB    : {control_db_path.name}")
    print(f"   • Evolution DB  : {evolution_db_path.name}")
    print("==================================================")
    print(" Workdir initialization completed successfully.\n")

    return config


def main() -> None:
    """CLI entrypoint for sur_en_precios.tools.start."""
    parser = argparse.ArgumentParser(
        description="Initialize Sur en Precios working directory, default config.yaml, directories, and SQLite databases."
    )
    parser.add_argument(
        "--workdir",
        "-w",
        help="Path to working directory (defaults to WORKING_DIRECTORY environment variable or ~/Info/sur_en_precios)",
    )
    args = parser.parse_args()

    workdir_path = (
        Path(args.workdir).expanduser().resolve() if args.workdir else None
    )

    try:
        init_workdir(workdir=workdir_path)
    except Exception as exc:
        logger.exception("Failed to initialize workdir: %s", exc)
        print(f"\n[ERROR] Initialization failed: {exc}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
