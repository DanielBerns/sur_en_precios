"""Orchestrator tool to run the daily supermarket price harvest and ETL pipeline.

Executed on the UNPSJB ingestion server to produce public.sqlite for upload to the web host.
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.config import read_config
from sur_en_precios.tools.run_etl import run_etl_pipeline
from sur_en_precios.tools.run_harvest import run_harvest
from sur_en_precios.tools.sync_client import sync_catalog_to_web
from sur_en_precios.web.control_app.app import ControlBase, ScraperLogModel

logger = logging.getLogger("sur_en_precios.daily_update")


def record_update_log(
    control_db_path: Path,
    status: str,
    duration_ms: int,
    file_size_bytes: int = 0,
    error_message: Optional[str] = None,
) -> None:
    """Logs the update execution status into control.sqlite."""
    try:
        engine = create_engine(f"sqlite:///{control_db_path}")
        ControlBase.metadata.create_all(engine)
        with Session(engine) as session:
            log_entry = ScraperLogModel(
                job_name="daily_database_update",
                status=status,
                file_size_bytes=file_size_bytes,
                duration_ms=duration_ms,
                error_message=error_message,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(log_entry)
            session.commit()
    except Exception as exc:
        logger.error("Failed to record update log to control db: %s", exc)


def run_daily_update_sync(
    workdir_override: Optional[Path] = None,
    force_harvest: bool = False,
) -> Dict[str, Any]:
    """Synchronous orchestrator for daily harvest and regional ETL."""
    start_time = time.perf_counter()
    config = read_config(workdir_override=workdir_override, should_create_override=True)
    control_db_path = config.get_control_db_path()

    harvest_result: Dict[str, Any] = {}
    error_msg: Optional[str] = None
    status = "SUCCESS"

    try:
        # Step 1: Harvest daily SEPA archives
        print("\n[1/2] Iniciando recolección de archivos SEPA...")
        harvest_result = asyncio.run(
            run_harvest(
                workdir_override=config.workdir,
                force_override=force_harvest,
            )
        )

        public_db = config.get_public_db_path()
        new_count = harvest_result.get("new_count", 0)
        if (
            new_count == 0
            and not force_harvest
            and public_db.exists()
            and public_db.stat().st_size > 0
        ):
            print(
                "\n[INFO] No hay nuevos archivos SEPA y el catálogo local ya existe. Omitiendo ETL local."
            )
        else:
            # Step 2: Run Regional ETL to update public.sqlite
            print("\n[2/3] Procesando datos regionales y actualizando catálogo...")
            run_etl_pipeline(
                workdir_override=config.workdir,
                should_create_override=False,
            )

        # Step 3: Synchronize with public web server if enabled in config.yaml.
        # Runs even when local ETL was skipped so previously failed remote syncs self-heal;
        # sync_catalog_to_web skips immediately when remote SHA-256 already matches.
        if (
            config.get_sync_settings().sync_to_web
            and public_db.exists()
            and public_db.stat().st_size > 0
        ):
            print("\n[3/3] Sincronizando catálogo con el servidor público...")
            sync_res = asyncio.run(sync_catalog_to_web(config))
            print(f"Sincronización remota finalizada: {sync_res.get('status')}")

    except Exception as exc:
        status = "ERROR"
        error_msg = str(exc)
        print(f"\nERROR en actualización diaria: {exc}", file=sys.stderr)

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    total_bytes = 0
    if harvest_result and "extracted_files" in harvest_result:
        total_bytes = sum(
            f.stat().st_size for f in harvest_result["extracted_files"] if f.exists()
        )

    record_update_log(
        control_db_path=control_db_path,
        status=status,
        duration_ms=duration_ms,
        file_size_bytes=total_bytes,
        error_message=error_msg,
    )

    return {
        "status": status,
        "duration_ms": duration_ms,
        "error_message": error_msg,
        "harvest": harvest_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ejecuta la actualización diaria de artículos y precios (Harvest + ETL) en el servidor de ingesta UNPSJB."
    )
    parser.add_argument(
        "--workdir", help="Directorio de trabajo (por defecto ~/Info/sur_en_precios)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fuerza la descarga de archivos aunque ya existan",
    )

    args = parser.parse_args()
    workdir_path = Path(args.workdir).resolve() if args.workdir else None

    result = run_daily_update_sync(
        workdir_override=workdir_path,
        force_harvest=args.force,
    )

    if result["status"] != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
