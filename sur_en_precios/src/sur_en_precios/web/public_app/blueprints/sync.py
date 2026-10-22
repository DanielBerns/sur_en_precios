"""Sync Blueprint for reserved machine-to-machine database updates from UNPSJB."""

import gzip
import hashlib
import json
import logging
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.config import Config
from sur_en_precios.web.control_app.app import ControlBase, ScraperLogModel
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    is_maintenance_mode,
    set_maintenance_mode,
)
from sur_en_precios.web.public_app.security import sync_api_required

logger = logging.getLogger("sur_en_precios.public_app.sync")

sync_bp = Blueprint("sync", __name__, url_prefix="/api/admin/sync")


def _record_sync_log(
    control_db_path: Path,
    status: str,
    duration_ms: int,
    file_size_bytes: int = 0,
    error_message: str | None = None,
) -> None:
    """Logs the incoming sync execution status into control.sqlite."""
    try:
        engine = create_engine(f"sqlite:///{control_db_path}")
        ControlBase.metadata.create_all(engine)
        with Session(engine) as session:
            log_entry = ScraperLogModel(
                job_name="unpsjb_sync_received",
                status=status,
                file_size_bytes=file_size_bytes,
                duration_ms=duration_ms,
                error_message=error_message,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(log_entry)
            session.commit()
    except Exception as exc:
        logger.error("Failed recording sync log to control db: %s", exc)


@sync_bp.route("/status", methods=["GET"])
@sync_api_required
def sync_status():
    """Returns current server status, disk information, and maintenance state."""
    config: Config = current_app.config["APP_CONFIG"]
    public_db = config.get_public_db_path()

    db_exists = public_db.exists()
    db_size = public_db.stat().st_size if db_exists else 0

    return jsonify(
        {
            "status": "online",
            "maintenance_mode": is_maintenance_mode(config),
            "database_exists": db_exists,
            "database_size_bytes": db_size,
            "chunk_size_bytes": config.get_sync_settings().chunk_size_bytes,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )


@sync_bp.route("/start", methods=["POST"])
@sync_api_required
def sync_start():
    """Initiates an atomic sync session.

    Enters maintenance mode (HTTP 503 for all regular traffic), disposes
    connections to public.sqlite, and deletes existing catalog files to reclaim
    storage immediately.
    """
    config: Config = current_app.config["APP_CONFIG"]
    payload: Dict[str, Any] = request.get_json(silent=True) or {}

    expected_chunks = int(payload.get("expected_chunks", 1))
    expected_size_bytes = int(payload.get("expected_size_bytes", 0))
    target_sha256 = str(payload.get("sha256", "")).strip().lower()

    if expected_chunks <= 0:
        return jsonify({"error": "expected_chunks debe ser mayor a 0"}), 400

    upload_id = uuid.uuid4().hex

    # 1. Activate maintenance mode
    set_maintenance_mode(
        config, reason="Sincronización de catálogo UNPSJB en progreso"
    )

    # 2. Dispose SQLAlchemy engine pool
    public_engine = current_app.extensions.get("public_engine")
    if public_engine:
        try:
            public_engine.dispose()
            logger.info("Disposed SQLAlchemy public_engine connection pool.")
        except Exception as exc:
            logger.warning("Error disposing public_engine: %s", exc)

    # 3. Delete old public.sqlite and WAL/SHM artifacts to free disk space immediately
    public_db_path = config.get_public_db_path()
    for ext in ("", "-wal", "-shm"):
        f = public_db_path.parent / (public_db_path.name + ext)
        if f.exists():
            try:
                f.unlink()
                logger.info("Deleted catalog file to free space: %s", f.name)
            except Exception as exc:
                logger.warning("Could not unlink %s: %s", f, exc)

    # 4. Prepare staging directory and session manifest
    staging_dir = config.sync_staging_dir / upload_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "upload_id": upload_id,
        "filename": payload.get("filename", "public.sqlite.gz"),
        "expected_chunks": expected_chunks,
        "expected_size_bytes": expected_size_bytes,
        "sha256": target_sha256,
        "started_at": time.time(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(staging_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info(
        "Sync session started: upload_id=%s, expected_chunks=%d, size=%d bytes",
        upload_id,
        expected_chunks,
        expected_size_bytes,
    )

    return (
        jsonify(
            {
                "status": "ready",
                "upload_id": upload_id,
                "chunk_size_bytes": config.get_sync_settings().chunk_size_bytes,
                "message": "Servidor listo en modo mantenimiento. Almacenamiento previo liberado.",
            }
        ),
        201,
    )


@sync_bp.route("/chunk/<upload_id>/<int:chunk_idx>", methods=["PUT"])
@sync_api_required
def sync_chunk(upload_id: str, chunk_idx: int):
    """Receives and writes an individual binary chunk into the staging directory."""
    config: Config = current_app.config["APP_CONFIG"]
    staging_dir = config.sync_staging_dir / upload_id

    if not staging_dir.exists() or not (staging_dir / "meta.json").exists():
        return jsonify({"error": "Sesión de subida inexistente o expirada"}), 404

    chunk_data = request.get_data()
    if not chunk_data:
        return jsonify({"error": "Chunk vacío o sin datos"}), 400

    chunk_path = staging_dir / f"chunk_{chunk_idx:05d}.part"
    with open(chunk_path, "wb") as f:
        f.write(chunk_data)

    return jsonify(
        {
            "status": "chunk_received",
            "upload_id": upload_id,
            "chunk_index": chunk_idx,
            "bytes_received": len(chunk_data),
        }
    )


@sync_bp.route("/finish/<upload_id>", methods=["POST"])
@sync_api_required
def sync_finish(upload_id: str):
    """Assembles chunks, validates SHA-256, decompresses in-place, verifies SQLite integrity, and restores normal service."""
    start_time = time.perf_counter()
    config: Config = current_app.config["APP_CONFIG"]
    staging_dir = config.sync_staging_dir / upload_id
    meta_path = staging_dir / "meta.json"

    if not staging_dir.exists() or not meta_path.exists():
        return jsonify({"error": "Sesión de subida inexistente o expirada"}), 404

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    expected_chunks = meta["expected_chunks"]
    expected_sha256 = meta.get("sha256", "")

    # 1. Verify all chunk parts exist
    for idx in range(expected_chunks):
        part_file = staging_dir / f"chunk_{idx:05d}.part"
        if not part_file.exists():
            return (
                jsonify(
                    {
                        "error": f"Falta el fragmento {idx} de {expected_chunks} para completar el archivo"
                    }
                ),
                400,
            )

    # 2. Stream assemble chunks into incoming.sqlite.gz, unlinking parts as we go
    archive_path = staging_dir / "incoming.sqlite.gz"
    hasher = hashlib.sha256()

    with open(archive_path, "wb") as out_archive:
        for idx in range(expected_chunks):
            part_file = staging_dir / f"chunk_{idx:05d}.part"
            with open(part_file, "rb") as in_part:
                while True:
                    buffer = in_part.read(64 * 1024)
                    if not buffer:
                        break
                    hasher.update(buffer)
                    out_archive.write(buffer)
            # Reclaim disk space immediately by deleting each part after appending
            try:
                part_file.unlink()
            except Exception:
                pass

    calculated_sha256 = hasher.hexdigest().lower()
    if expected_sha256 and calculated_sha256 != expected_sha256:
        logger.error(
            "Checksum mismatch: expected %s, got %s",
            expected_sha256,
            calculated_sha256,
        )
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_CHECKSUM",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message="Checksum SHA-256 no coincide",
        )
        return (
            jsonify(
                {
                    "error": "Error de verificación de integridad (SHA-256 no coincide)"
                }
            ),
            400,
        )

    # 3. Stream decompression directly to public.sqlite
    public_db_path = config.get_public_db_path()
    try:
        with (
            gzip.open(archive_path, "rb") as gz_in,
            open(public_db_path, "wb") as db_out,
        ):
            shutil.copyfileobj(gz_in, db_out, length=64 * 1024)
    except Exception as exc:
        logger.error("Decompression failed: %s", exc)
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_DECOMPRESS",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message=str(exc),
        )
        return (
            jsonify({"error": f"Fallo al descomprimir la base de datos: {exc}"}),
            500,
        )

    # 4. Immediately delete the gzipped archive
    try:
        archive_path.unlink()
    except Exception:
        pass

    # 5. Run SQLite integrity check on the fresh database
    try:
        with sqlite3.connect(str(public_db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            integrity_result = cursor.fetchone()
            if not integrity_result or integrity_result[0] != "ok":
                raise ValueError(
                    f"PRAGMA integrity_check failed: {integrity_result}"
                )

            # Apply production pragmas (WAL mode and busy timeout)
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 5000;")
    except Exception as exc:
        logger.error("SQLite integrity check failed: %s", exc)
        if public_db_path.exists():
            public_db_path.unlink()
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_SQLITE_INTEGRITY",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message=str(exc),
        )
        return (
            jsonify(
                {
                    "error": f"Fallo de integridad de SQLite en base recibida: {exc}"
                }
            ),
            500,
        )

    # 6. Dispose connection pool again so SQLAlchemy re-binds cleanly
    public_engine = current_app.extensions.get("public_engine")
    if public_engine:
        try:
            public_engine.dispose()
        except Exception:
            pass

    # 7. Clean up staging directory
    shutil.rmtree(staging_dir, ignore_errors=True)

    # 8. Deactivate maintenance mode
    clear_maintenance_mode(config)

    total_duration_ms = int((time.perf_counter() - start_time) * 1000)
    final_size = public_db_path.stat().st_size

    _record_sync_log(
        control_db_path=config.get_control_db_path(),
        status="SUCCESS",
        duration_ms=total_duration_ms,
        file_size_bytes=final_size,
    )

    logger.info(
        "Sync completed successfully in %d ms (size: %d bytes)",
        total_duration_ms,
        final_size,
    )

    return jsonify(
        {
            "status": "success",
            "message": "Base de datos public.sqlite actualizada e indexada exitosamente.",
            "duration_ms": total_duration_ms,
            "database_size_bytes": final_size,
        }
    )


@sync_bp.route("/abort/<upload_id>", methods=["POST"])
@sync_api_required
def sync_abort(upload_id: str):
    """Aborts a sync session and cleans up temporary files."""
    config: Config = current_app.config["APP_CONFIG"]
    staging_dir = config.sync_staging_dir / upload_id

    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)

    clear_maintenance_mode(config)

    _record_sync_log(
        control_db_path=config.get_control_db_path(),
        status="ABORTED",
        duration_ms=0,
        error_message=f"Subida abortada por el cliente: {upload_id}",
    )

    return jsonify({"status": "aborted", "upload_id": upload_id})
