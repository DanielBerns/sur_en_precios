"""Sync Blueprint for zero-downtime Red/Green database updates from UNPSJB."""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from sur_en_precios.config import Config
from sur_en_precios.web.control_app.app import ControlBase, ScraperLogModel
from sur_en_precios.web.public_app.catalog_slots import (
    VALID_SLOTS,
    SlotName,
    activate_slot,
    choose_target_slot,
    cleanup_orphan_nfs_files,
    compute_file_sha256,
    get_catalog_meta_path,
    get_slot_db_path,
    get_slots_diagnostics,
    rollback_slot,
    safe_remove_sqlite_files,
    validate_candidate_sqlite,
)
from sur_en_precios.web.public_app.database import ensure_public_session_factory
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    is_maintenance_mode,
    set_maintenance_mode,
)
from sur_en_precios.web.public_app.security import sync_api_required

logger = logging.getLogger("sur_en_precios.public_app.sync")

sync_bp = Blueprint("sync", __name__, url_prefix="/api/admin/sync")


class ChunkPartStream(io.RawIOBase):
    """Sequential binary stream over chunk_XXXXX.part files with progressive unlinking.

    Updates the provided compressed-stream SHA-256 hasher on every byte read and
    deletes each part file immediately upon reaching its EOF so peak disk usage
    never holds both the compressed archive and the decompressed SQLite candidate.
    """

    def __init__(self, part_files: List[Path], hasher: Any) -> None:
        super().__init__()
        self._part_files = part_files
        self._hasher = hasher
        self._idx = 0
        self._current_fh: Optional[io.BufferedReader] = None

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        view = memoryview(b)
        if len(view) == 0:
            return 0

        while True:
            if self._current_fh is None:
                if self._idx >= len(self._part_files):
                    return 0
                self._current_fh = open(self._part_files[self._idx], "rb")

            n = self._current_fh.readinto(view)
            if n and n > 0:
                self._hasher.update(view[:n])
                return int(n)

            finished_part = self._part_files[self._idx]
            self._current_fh.close()
            self._current_fh = None
            self._idx += 1
            try:
                finished_part.unlink()
            except Exception:
                pass

    def close(self) -> None:
        if self._current_fh is not None:
            try:
                self._current_fh.close()
            except Exception:
                pass
            self._current_fh = None
        super().close()


def _record_sync_log(
    control_db_path: Path,
    status: str,
    duration_ms: int,
    file_size_bytes: int = 0,
    error_message: str | None = None,
) -> None:
    """Logs the incoming sync execution status into control.sqlite."""
    try:
        engine = create_engine(
            f"sqlite:///{control_db_path}",
            poolclass=NullPool,
            connect_args={"timeout": 30.0},
        )
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


def _has_active_staging_sessions(config: Config) -> bool:
    """Checks if any staging directory currently exists."""
    staging_root = config.sync_staging_dir
    if not staging_root.exists():
        return False
    return any(p.is_dir() for p in staging_root.iterdir())


def _cleanup_stale_staging_sessions(config: Config) -> None:
    """Removes incomplete staging sessions unless an active cutover lock is held."""
    staging_root = config.sync_staging_dir
    if not staging_root.exists():
        return

    timeout_sec = config.get_sync_settings().timeout_seconds
    now_ts = time.time()

    for entry in list(staging_root.iterdir()):
        if not entry.is_dir():
            continue
        finish_lock = entry / "finishing.lock"
        if finish_lock.exists():
            try:
                lock_age = now_ts - finish_lock.stat().st_mtime
                if lock_age < timeout_sec:
                    continue
            except Exception:
                pass
        shutil.rmtree(entry, ignore_errors=True)

    cleanup_orphan_nfs_files(staging_root)


@sync_bp.route("/status", methods=["GET"])
@sync_api_required
def sync_status() -> Any:
    """Returns current server status, Red/Green slot state, maintenance state, and database SHA-256."""
    config: Config = current_app.config["APP_CONFIG"]
    diag = get_slots_diagnostics(config)
    active_db: Path = diag["active_path"]
    active_slot: Optional[str] = diag["active_slot"]

    db_exists = active_db.exists() and active_db.stat().st_size > 0
    db_size = active_db.stat().st_size if db_exists else 0

    db_sha256 = ""
    if active_slot in VALID_SLOTS:
        db_sha256 = str(diag["slots"][active_slot].get("db_sha256", "")).lower()

    meta_path = get_catalog_meta_path(config)
    if not db_sha256 and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                meta_data = json.load(f_meta)
                if int(meta_data.get("size_bytes", -1)) == db_size:
                    db_sha256 = str(meta_data.get("db_sha256", "")).lower()
        except Exception:
            pass

    if not db_sha256 and db_exists and db_size > 0:
        try:
            db_sha256 = compute_file_sha256(active_db)
            tmp_meta = meta_path.with_name(f"{meta_path.name}.tmp")
            with open(tmp_meta, "w", encoding="utf-8") as f_meta:
                json.dump(
                    {
                        "active_slot": active_slot,
                        "db_sha256": db_sha256,
                        "size_bytes": db_size,
                    },
                    f_meta,
                    indent=2,
                )
            tmp_meta.replace(meta_path)
        except Exception as exc:
            logger.warning("Could not compute db_sha256 for status: %s", exc)

    return jsonify(
        {
            "status": "online",
            "maintenance_mode": is_maintenance_mode(config),
            "active_slot": active_slot,
            "previous_slot": diag["previous_slot"],
            "standby_slot": diag["standby_slot"],
            "rollback_available": diag["rollback_available"],
            "database_exists": db_exists,
            "database_filename": active_db.name,
            "database_size_bytes": db_size,
            "db_sha256": db_sha256,
            "slots": diag["slots"],
            "sync_in_progress": _has_active_staging_sessions(config),
            "chunk_size_bytes": config.get_sync_settings().chunk_size_bytes,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )


@sync_bp.route("/start", methods=["POST"])
@sync_api_required
def sync_start() -> Any:
    """Initiates a zero-downtime Red/Green sync session targeting the inactive slot."""
    config: Config = current_app.config["APP_CONFIG"]
    payload: Dict[str, Any] = request.get_json(silent=True) or {}

    expected_chunks = int(payload.get("expected_chunks", 1))
    expected_size_bytes = int(payload.get("expected_size_bytes", 0))
    target_sha256 = str(payload.get("sha256", "")).strip().lower()
    expected_db_sha256 = str(payload.get("db_sha256", "")).strip().lower()

    if expected_chunks <= 0:
        return jsonify({"error": "expected_chunks debe ser mayor a 0"}), 400

    diag = get_slots_diagnostics(config)
    active_path: Path = diag["active_path"]
    active_slot: Optional[SlotName] = diag["active_slot"]
    target_slot: SlotName = choose_target_slot(active_slot)

    # Only activate maintenance mode on cold start when NO catalog file exists at all
    if not active_path.exists() or active_path.stat().st_size == 0:
        set_maintenance_mode(
            config, reason="Inicialización inicial de catálogo UNPSJB en progreso"
        )

    # 1. Reclaim space from abandoned staging sessions
    _cleanup_stale_staging_sessions(config)

    # 2. Reclaim space from the INACTIVE target slot before receiving chunks (active slot is untouched)
    inactive_slot_path = get_slot_db_path(config, target_slot)
    if inactive_slot_path.exists():
        safe_remove_sqlite_files(inactive_slot_path)
        logger.info(
            "Reclaimed inactive slot '%s' (%s) prior to upload.",
            target_slot,
            inactive_slot_path.name,
        )

    # 3. Once Red/Green is active, retire any leftover legacy public.sqlite file to save quota
    if active_slot in VALID_SLOTS:
        legacy_db_path = config.get_public_db_path()
        if legacy_db_path.exists() and legacy_db_path != active_path:
            safe_remove_sqlite_files(legacy_db_path)
            logger.info(
                "Retired legacy %s file to free disk quota.", legacy_db_path.name
            )

    cleanup_orphan_nfs_files(config.data_dir)

    # 4. Prepare staging directory and session manifest
    upload_id = uuid.uuid4().hex
    staging_dir = config.sync_staging_dir / upload_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "upload_id": upload_id,
        "filename": payload.get("filename", "public.sqlite.gz"),
        "active_slot_at_start": active_slot,
        "target_slot": target_slot,
        "expected_chunks": expected_chunks,
        "expected_size_bytes": expected_size_bytes,
        "sha256": target_sha256,
        "db_sha256": expected_db_sha256,
        "started_at": time.time(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(staging_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info(
        "Red/Green sync session started: upload_id=%s, active_slot=%s -> target_slot=%s, chunks=%d, size=%d bytes",
        upload_id,
        active_slot or "legacy",
        target_slot,
        expected_chunks,
        expected_size_bytes,
    )

    return (
        jsonify(
            {
                "status": "ready",
                "upload_id": upload_id,
                "active_slot": active_slot,
                "target_slot": target_slot,
                "chunk_size_bytes": config.get_sync_settings().chunk_size_bytes,
                "message": f"Sesión Red/Green lista (slot destino: {target_slot}). Catálogo activo continúa en línea.",
            }
        ),
        201,
    )


@sync_bp.route("/chunk/<upload_id>/<int:chunk_idx>", methods=["PUT"])
@sync_api_required
def sync_chunk(upload_id: str, chunk_idx: int) -> Any:
    """Receives and writes an individual binary chunk into the isolated staging directory."""
    config: Config = current_app.config["APP_CONFIG"]
    staging_dir = config.sync_staging_dir / upload_id
    meta_path = staging_dir / "meta.json"

    if not staging_dir.exists() or not meta_path.exists():
        return jsonify({"error": "Sesión de subida inexistente o expirada"}), 404

    if chunk_idx < 0:
        return jsonify({"error": "Índice de fragmento inválido"}), 400

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
def sync_finish(upload_id: str) -> Any:
    """Stream-decompresses chunks into an isolated candidate, validates lock-free, and atomically flips Red/Green slot."""
    start_time = time.perf_counter()
    config: Config = current_app.config["APP_CONFIG"]
    staging_dir = config.sync_staging_dir / upload_id
    meta_path = staging_dir / "meta.json"

    if not staging_dir.exists() or not meta_path.exists():
        return jsonify({"error": "Sesión de subida inexistente o expirada"}), 404

    finish_lock = staging_dir / "finishing.lock"
    if finish_lock.exists():
        return jsonify(
            {"error": "La finalización de esta sesión ya está en curso"}
        ), 409

    with open(finish_lock, "w", encoding="utf-8") as f_lock:
        f_lock.write(datetime.now(timezone.utc).isoformat())

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    expected_chunks = int(meta["expected_chunks"])
    expected_gz_sha256 = str(meta.get("sha256", "")).strip().lower()
    expected_db_sha256 = str(meta.get("db_sha256", "")).strip().lower()
    raw_target_slot = meta.get("target_slot")
    target_slot: SlotName = (
        raw_target_slot
        if raw_target_slot in VALID_SLOTS
        else choose_target_slot(get_slots_diagnostics(config)["active_slot"])
    )

    # 1. Verify all chunk parts exist before streaming
    part_files: List[Path] = []
    for idx in range(expected_chunks):
        part_file = staging_dir / f"chunk_{idx:05d}.part"
        if not part_file.exists():
            finish_lock.unlink(missing_ok=True)
            return (
                jsonify(
                    {
                        "error": f"Falta el fragmento {idx} de {expected_chunks} para completar el archivo"
                    }
                ),
                400,
            )
        part_files.append(part_file)

    # 2. Single-pass streaming decompression + progressive chunk deletion + dual SHA-256 hashing
    candidate_path = staging_dir / f"candidate_{target_slot}.sqlite"
    compressed_hasher = hashlib.sha256()
    db_hasher = hashlib.sha256()

    try:
        raw_part_stream = ChunkPartStream(part_files, compressed_hasher)
        with (
            io.BufferedReader(raw_part_stream, buffer_size=64 * 1024) as buffered_in,
            open(candidate_path, "wb") as db_out,
        ):
            with gzip.GzipFile(fileobj=buffered_in, mode="rb") as gz_in:
                while True:
                    decompressed_buf = gz_in.read(64 * 1024)
                    if not decompressed_buf:
                        break
                    db_hasher.update(decompressed_buf)
                    db_out.write(decompressed_buf)
            # Drain any trailing EOF boundary so the final part file is hashed and unlinked
            while buffered_in.read(64 * 1024):
                pass
    except OSError as os_exc:
        is_quota = os_exc.errno == errno.EDQUOT
        logger.error("Decompression I/O error (quota=%s): %s", is_quota, os_exc)
        safe_remove_sqlite_files(candidate_path)
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_DISK_QUOTA" if is_quota else "ERROR_DECOMPRESS",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message=str(os_exc),
        )
        return (
            jsonify(
                {
                    "error": f"Fallo al descomprimir la base de datos: {os_exc}",
                }
            ),
            507 if is_quota else 500,
        )
    except Exception as exc:
        logger.error("Decompression failed: %s", exc)
        safe_remove_sqlite_files(candidate_path)
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

    # 3. Validate compressed and uncompressed SHA-256 digests
    calculated_gz_sha256 = compressed_hasher.hexdigest().lower()
    calculated_db_sha256 = db_hasher.hexdigest().lower()

    if expected_gz_sha256 and calculated_gz_sha256 != expected_gz_sha256:
        logger.error(
            "Compressed SHA-256 mismatch: expected %s, got %s",
            expected_gz_sha256,
            calculated_gz_sha256,
        )
        safe_remove_sqlite_files(candidate_path)
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_CHECKSUM",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message="Checksum SHA-256 comprimido no coincide",
        )
        return (
            jsonify(
                {"error": "Error de verificación de integridad (SHA-256 no coincide)"}
            ),
            400,
        )

    if expected_db_sha256 and calculated_db_sha256 != expected_db_sha256:
        logger.error(
            "Uncompressed DB SHA-256 mismatch: expected %s, got %s",
            expected_db_sha256,
            calculated_db_sha256,
        )
        safe_remove_sqlite_files(candidate_path)
        shutil.rmtree(staging_dir, ignore_errors=True)
        clear_maintenance_mode(config)
        _record_sync_log(
            control_db_path=config.get_control_db_path(),
            status="ERROR_CHECKSUM",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            error_message="Checksum SHA-256 de base descomprimida no coincide",
        )
        return (
            jsonify(
                {
                    "error": "Error de verificación de integridad (SHA-256 de base SQLite no coincide)"
                }
            ),
            400,
        )

    # 4. Run lock-free SQLite validation on the isolated candidate file
    try:
        size_before_validation = candidate_path.stat().st_size
        with open(candidate_path, "rb") as f_hdr:
            hdr_before = f_hdr.read(28)
        validation_stats = validate_candidate_sqlite(candidate_path)
        with open(candidate_path, "rb") as f_hdr_after:
            hdr_after = f_hdr_after.read(28)
        # Recompute db_sha256 only if WAL->DELETE header normalization mutated candidate
        if (
            hdr_before != hdr_after
            or candidate_path.stat().st_size != size_before_validation
        ):
            calculated_db_sha256 = compute_file_sha256(candidate_path)
    except Exception as exc:
        logger.error("Candidate SQLite validation failed: %s", exc)
        safe_remove_sqlite_files(candidate_path)
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
                {"error": f"Fallo de integridad de SQLite en base recibida: {exc}"}
            ),
            500,
        )

    # 5. Atomic Red/Green cutover: rename candidate -> public_<target_slot>.sqlite & update catalog_state.json
    new_state = activate_slot(
        config=config,
        target_slot=target_slot,
        candidate_path=candidate_path,
        db_sha256=calculated_db_sha256,
        archive_sha256=calculated_gz_sha256,
    )

    # 6. Refresh current worker binding immediately (sibling uWSGI workers rebind on next request)
    ensure_public_session_factory(current_app)

    # 7. Clean staging directory
    shutil.rmtree(staging_dir, ignore_errors=True)

    # 8. Optional immediate reclamation if retain_previous_slot is False
    if not config.get_sync_settings().retain_previous_slot:
        if new_state.previous_slot in VALID_SLOTS:
            prev_path = get_slot_db_path(config, new_state.previous_slot)
            safe_remove_sqlite_files(prev_path)
        legacy_db = config.get_public_db_path()
        if legacy_db.exists():
            safe_remove_sqlite_files(legacy_db)

    # 9. Release any cold-start or legacy maintenance lock
    clear_maintenance_mode(config)

    active_meta = new_state.slots[target_slot]
    final_size = active_meta.size_bytes
    total_duration_ms = int((time.perf_counter() - start_time) * 1000)

    _record_sync_log(
        control_db_path=config.get_control_db_path(),
        status="SUCCESS",
        duration_ms=total_duration_ms,
        file_size_bytes=final_size,
    )

    logger.info(
        "Red/Green cutover completed in %d ms: active_slot=%s, previous_slot=%s, size=%d bytes, sha256=%s, stats=%s",
        total_duration_ms,
        new_state.active_slot,
        new_state.previous_slot or "-",
        final_size,
        calculated_db_sha256[:12],
        validation_stats,
    )

    return jsonify(
        {
            "status": "success",
            "message": f"Cutover Red/Green exitoso: slot '{target_slot}' activo.",
            "active_slot": new_state.active_slot,
            "previous_slot": new_state.previous_slot,
            "duration_ms": total_duration_ms,
            "database_size_bytes": final_size,
            "db_sha256": calculated_db_sha256,
        }
    )


@sync_bp.route("/abort/<upload_id>", methods=["POST"])
@sync_api_required
def sync_abort(upload_id: str) -> Any:
    """Aborts a staging sync session and cleans up temporary files without touching the active slot."""
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


@sync_bp.route("/rollback", methods=["POST"])
@sync_api_required
def sync_rollback() -> Any:
    """Atomically switches active traffic back to the validated standby Red/Green slot."""
    start_time = time.perf_counter()
    config: Config = current_app.config["APP_CONFIG"]

    try:
        new_state = rollback_slot(config)
        ensure_public_session_factory(current_app)
        clear_maintenance_mode(config)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.warning("Rollback rejected: %s", exc)
        return jsonify({"error": str(exc)}), 409

    active_slot = new_state.active_slot
    active_meta = new_state.slots[active_slot] if active_slot else None
    duration_ms = int((time.perf_counter() - start_time) * 1000)

    _record_sync_log(
        control_db_path=config.get_control_db_path(),
        status="ROLLBACK_SUCCESS",
        duration_ms=duration_ms,
        file_size_bytes=active_meta.size_bytes if active_meta else 0,
    )

    logger.info(
        "Red/Green rollback completed in %d ms: active_slot=%s, previous_slot=%s",
        duration_ms,
        new_state.active_slot,
        new_state.previous_slot or "-",
    )

    return jsonify(
        {
            "status": "rolled_back",
            "active_slot": new_state.active_slot,
            "previous_slot": new_state.previous_slot,
            "database_size_bytes": active_meta.size_bytes if active_meta else 0,
            "db_sha256": active_meta.db_sha256 if active_meta else "",
            "duration_ms": duration_ms,
        }
    )
