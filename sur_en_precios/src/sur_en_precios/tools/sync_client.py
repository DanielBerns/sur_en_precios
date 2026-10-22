"""Client tool for streaming compressed public.sqlite chunks from UNPSJB to PythonAnywhere."""

import asyncio
import gzip
import hashlib
import json
import logging
import math
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.config import Config, read_config
from sur_en_precios.web.control_app.app import ControlBase, ScraperLogModel

logger = logging.getLogger("sur_en_precios.tools.sync_client")


def _record_client_log(
    control_db_path: Path,
    status: str,
    duration_ms: int,
    file_size_bytes: int = 0,
    error_message: Optional[str] = None,
) -> None:
    """Logs client upload telemetry into local control.sqlite on the UNPSJB computer."""
    try:
        engine = create_engine(f"sqlite:///{control_db_path}")
        ControlBase.metadata.create_all(engine)
        with Session(engine) as session:
            log_entry = ScraperLogModel(
                job_name="unpsjb_sync_upload",
                status=status,
                file_size_bytes=file_size_bytes,
                duration_ms=duration_ms,
                error_message=error_message,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(log_entry)
            session.commit()
    except Exception as exc:
        logger.error("Failed recording client sync log to control db: %s", exc)


async def sync_catalog_to_web(config: Config) -> Dict[str, Any]:
    """Compresses public.sqlite and uploads it in chunks to the public web server."""
    sync_settings = config.get_sync_settings()
    if not sync_settings.sync_to_web:
        logger.info("sync_to_web is disabled in config.yaml. Skipping sync.")
        return {"status": "SKIPPED", "message": "sync_to_web is disabled"}

    start_time = time.perf_counter()
    public_db_path = config.get_public_db_path()

    if not public_db_path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de base de datos en: {public_db_path}"
        )

    # 1. Local SQLite integrity check before starting
    logger.info("Verificando integridad local de %s...", public_db_path.name)
    with sqlite3.connect(str(public_db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        check_res = cursor.fetchone()
        if not check_res or check_res[0] != "ok":
            raise ValueError(f"Fallo de integridad local en SQLite: {check_res}")

    # 2. Pre-flight check: compute local uncompressed database SHA-256 and verify remote status
    hasher_db = hashlib.sha256()
    with open(public_db_path, "rb") as f_db:
        while chunk := f_db.read(64 * 1024):
            hasher_db.update(chunk)
    local_db_sha256 = hasher_db.hexdigest().lower()

    server_url = sync_settings.server_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {sync_settings.api_token}",
    }

    try:
        async with aiohttp.ClientSession(
            headers=headers, timeout=aiohttp.ClientTimeout(total=20)
        ) as status_session:
            async with status_session.get(f"{server_url}/api/admin/sync/status") as resp:
                if resp.status == 200:
                    status_data = await resp.json()
                    remote_sha256 = str(status_data.get("db_sha256", "")).lower()
                    if remote_sha256 and remote_sha256 == local_db_sha256:
                        logger.info(
                            "El catálogo en PythonAnywhere ya coincide exactamente con la versión local (SHA-256: %s). Sincronización omitida.",
                            local_db_sha256[:12],
                        )
                        print(
                            f"\n[INFO] La base de datos en PythonAnywhere ya está actualizada (SHA-256: {local_db_sha256[:12]}). Sincronización omitida."
                        )
                        return {
                            "status": "SKIPPED_IDENTICAL_HASH",
                            "message": "Database on remote server already matches local SHA-256.",
                            "sha256": local_db_sha256,
                        }
    except Exception as precheck_exc:
        logger.warning(
            "No se pudo consultar el estado previo de PythonAnywhere: %s",
            precheck_exc,
        )

    # 3. Compress public.sqlite into local temporary gzip archive
    outgoing_gz = config.temp_dir / "sync_outgoing.sqlite.gz"
    logger.info("Comprimiendo %s a %s...", public_db_path.name, outgoing_gz.name)

    with (
        open(public_db_path, "rb") as f_in,
        gzip.open(outgoing_gz, "wb", compresslevel=6) as f_out,
    ):
        shutil.copyfileobj(f_in, f_out, length=64 * 1024)

    # 3. Calculate SHA-256 and chunk requirements
    hasher = hashlib.sha256()
    with open(outgoing_gz, "rb") as f_gz:
        while chunk := f_gz.read(64 * 1024):
            hasher.update(chunk)
    target_sha256 = hasher.hexdigest().lower()
    gz_size = outgoing_gz.stat().st_size

    chunk_size = sync_settings.chunk_size_bytes
    total_chunks = max(1, math.ceil(gz_size / chunk_size))

    logger.info(
        "Archivo comprimido listo: %d bytes en %d chunks (SHA-256: %s)",
        gz_size,
        total_chunks,
        target_sha256[:12],
    )

    server_url = sync_settings.server_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {sync_settings.api_token}",
    }

    timeout = aiohttp.ClientTimeout(total=sync_settings.timeout_seconds)

    upload_id: Optional[str] = None

    try:
        async with aiohttp.ClientSession(
            headers=headers, timeout=timeout
        ) as session:
            # Step A: POST /start
            start_payload = {
                "filename": "public.sqlite.gz",
                "expected_chunks": total_chunks,
                "expected_size_bytes": gz_size,
                "sha256": target_sha256,
                "uncompressed_size_bytes": public_db_path.stat().st_size,
            }
            logger.info("Iniciando sesión de subida en %s...", server_url)
            async with session.post(
                f"{server_url}/api/admin/sync/start", json=start_payload
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise RuntimeError(
                        f"Error al iniciar subida ({resp.status}): {text}"
                    )
                start_data = await resp.json()
                upload_id = start_data["upload_id"]

            logger.info(
                "Sesión iniciada con éxito. Upload ID: %s. Subiendo fragmentos...",
                upload_id,
            )

            # Step B: PUT chunks with retries
            with open(outgoing_gz, "rb") as f_gz:
                for chunk_idx in range(total_chunks):
                    f_gz.seek(chunk_idx * chunk_size)
                    chunk_bytes = f_gz.read(chunk_size)

                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        try:
                            chunk_headers = {
                                "Content-Type": "application/octet-stream"
                            }
                            async with session.put(
                                f"{server_url}/api/admin/sync/chunk/{upload_id}/{chunk_idx}",
                                data=chunk_bytes,
                                headers=chunk_headers,
                            ) as chunk_resp:
                                if chunk_resp.status == 200:
                                    logger.info(
                                        "Chunk %d/%d transferido con éxito (%d bytes).",
                                        chunk_idx + 1,
                                        total_chunks,
                                        len(chunk_bytes),
                                    )
                                    break
                                else:
                                    err_text = await chunk_resp.text()
                                    raise RuntimeError(
                                        f"HTTP {chunk_resp.status}: {err_text}"
                                    )
                        except Exception as chunk_exc:
                            logger.warning(
                                "Fallo en chunk %d (intento %d/%d): %s",
                                chunk_idx,
                                attempt,
                                max_retries,
                                chunk_exc,
                            )
                            if attempt == max_retries:
                                raise RuntimeError(
                                    f"No se pudo transferir el fragmento {chunk_idx} tras {max_retries} intentos: {chunk_exc}"
                                ) from chunk_exc
                            await asyncio.sleep(2**attempt)

            # Step C: POST /finish
            logger.info(
                "Todos los fragmentos transferidos. Solicitando ensamblado y descompresión..."
            )
            async with session.post(
                f"{server_url}/api/admin/sync/finish/{upload_id}"
            ) as finish_resp:
                if finish_resp.status != 200:
                    text = await finish_resp.text()
                    raise RuntimeError(
                        f"Fallo en finalización ({finish_resp.status}): {text}"
                    )
                finish_data = await finish_resp.json()

        total_ms = int((time.perf_counter() - start_time) * 1000)
        _record_client_log(
            control_db_path=config.get_control_db_path(),
            status="SUCCESS",
            duration_ms=total_ms,
            file_size_bytes=gz_size,
        )
        logger.info(
            "Sincronización remota completada con éxito en %d ms.", total_ms
        )
        return {
            "status": "SUCCESS",
            "duration_ms": total_ms,
            "bytes_transferred": gz_size,
            "upload_id": upload_id,
            "server_response": finish_data,
        }

    except Exception as exc:
        total_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Error durante la sincronización: %s", exc)

        # Attempt to abort session on server if we have an upload_id
        if upload_id:
            try:
                async with aiohttp.ClientSession(
                    headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as abort_session:
                    await abort_session.post(
                        f"{server_url}/api/admin/sync/abort/{upload_id}"
                    )
            except Exception:
                pass

        _record_client_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR",
            duration_ms=total_ms,
            file_size_bytes=gz_size,
            error_message=str(exc),
        )
        raise

    finally:
        if outgoing_gz.exists():
            try:
                outgoing_gz.unlink()
            except Exception:
                pass


def run_sync_catalog_to_web(
    workdir_override: Optional[Path] = None,
) -> Dict[str, Any]:
    """Synchronous entry point for running the catalog sync."""
    config = read_config(workdir_override=workdir_override, should_create_override=False)
    return asyncio.run(sync_catalog_to_web(config))
