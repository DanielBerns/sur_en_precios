"""Red / Green immutable slot manager for zero-downtime public catalog updates."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from sur_en_precios.config import Config

logger = logging.getLogger("sur_en_precios.public_app.catalog_slots")

SlotName = Literal["red", "green"]
SLOT_RED: SlotName = "red"
SLOT_GREEN: SlotName = "green"
VALID_SLOTS: Tuple[SlotName, SlotName] = (SLOT_RED, SLOT_GREEN)

SQLITE_MAGIC_HEADER = b"SQLite format 3\x00"


class SlotMetadata(BaseModel):
    """Metadata describing a populated Red or Green SQLite catalog file."""

    slot: SlotName
    filename: str
    db_sha256: str
    archive_sha256: str = ""
    size_bytes: int
    synced_at: str


class CatalogState(BaseModel):
    """Persistent Red/Green slot routing state shared across uWSGI workers."""

    active_slot: Optional[SlotName] = None
    previous_slot: Optional[SlotName] = None
    slots: Dict[str, SlotMetadata] = Field(default_factory=dict)
    updated_at: str = ""


# Per-worker cache: state_path -> (st_ino, st_mtime_ns, st_size, CatalogState)
_STATE_CACHE: Dict[Path, Tuple[int, int, int, CatalogState]] = {}


def get_slot_db_path(config: Config, slot: str) -> Path:
    """Returns the filesystem path for the requested Red or Green slot."""
    if slot not in VALID_SLOTS:
        raise ValueError(f"Invalid catalog slot '{slot}'. Expected 'red' or 'green'.")
    return config.data_dir / f"public_{slot}.sqlite"


def get_catalog_state_path(config: Config) -> Path:
    """Returns the atomic pointer file path tracking the active slot."""
    return config.data_dir / "catalog_state.json"


def get_catalog_meta_path(config: Config) -> Path:
    """Returns the backwards-compatible catalog metadata cache path."""
    return config.data_dir / "catalog_meta.json"


def compute_file_sha256(file_path: Path) -> str:
    """Computes lowercase hex SHA-256 digest of a file in streaming chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f_in:
        while True:
            buf = f_in.read(64 * 1024)
            if not buf:
                break
            hasher.update(buf)
    return hasher.hexdigest().lower()


def _atomic_write_json(target_path: Path, payload: Dict[str, Any]) -> None:
    """Writes JSON to a sibling temporary file and atomically renames it into place."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f_out:
        json.dump(payload, f_out, indent=2)
    tmp_path.replace(target_path)


def load_catalog_state(config: Config) -> CatalogState:
    """Loads CatalogState from disk using a stat-keyed per-worker cache."""
    state_path = get_catalog_state_path(config)
    if not state_path.exists():
        _STATE_CACHE.pop(state_path, None)
        return CatalogState()

    try:
        st = state_path.stat()
        cache_sig = (st.st_ino, st.st_mtime_ns, st.st_size)
        cached = _STATE_CACHE.get(state_path)
        if cached is not None and cached[:3] == cache_sig:
            return cached[3]

        with open(state_path, "r", encoding="utf-8") as f_in:
            raw_data = json.load(f_in)
        parsed = CatalogState(**raw_data)
        _STATE_CACHE[state_path] = (st.st_ino, st.st_mtime_ns, st.st_size, parsed)
        return parsed
    except Exception as exc:
        logger.warning("Failed reading catalog_state.json: %s", exc)
        return CatalogState()


def save_catalog_state(config: Config, state: CatalogState) -> None:
    """Atomically persists CatalogState and updates legacy catalog_meta.json."""
    state_path = get_catalog_state_path(config)
    _atomic_write_json(state_path, state.model_dump())

    try:
        st = state_path.stat()
        _STATE_CACHE[state_path] = (st.st_ino, st.st_mtime_ns, st.st_size, state)
    except Exception:
        _STATE_CACHE.pop(state_path, None)

    if state.active_slot and state.active_slot in state.slots:
        active_meta = state.slots[state.active_slot]
        meta_path = get_catalog_meta_path(config)
        try:
            _atomic_write_json(
                meta_path,
                {
                    "active_slot": state.active_slot,
                    "db_sha256": active_meta.db_sha256,
                    "archive_sha256": active_meta.archive_sha256,
                    "synced_at": active_meta.synced_at,
                    "size_bytes": active_meta.size_bytes,
                },
            )
        except Exception as exc:
            logger.warning("Could not write catalog_meta.json: %s", exc)


def resolve_active_public_db(config: Config) -> Tuple[Path, Optional[SlotName]]:
    """Resolves the active SQLite catalog path and slot name.

    Order of precedence:
    1. Active Red/Green slot from catalog_state.json (if non-empty file exists).
    2. Standby previous_slot from catalog_state.json (automatic self-healing fallback).
    3. Legacy/local config.get_public_db_path() ('public.sqlite') with slot=None.
    """
    state = load_catalog_state(config)

    if state.active_slot in VALID_SLOTS:
        active_path = get_slot_db_path(config, state.active_slot)
        if active_path.exists() and active_path.stat().st_size > 0:
            return active_path, state.active_slot

    if state.previous_slot in VALID_SLOTS:
        prev_path = get_slot_db_path(config, state.previous_slot)
        if prev_path.exists() and prev_path.stat().st_size > 0:
            logger.warning(
                "Active slot '%s' missing; falling back to standby slot '%s'.",
                state.active_slot,
                state.previous_slot,
            )
            return prev_path, state.previous_slot

    return config.get_public_db_path(), None


def has_populated_active_catalog(config: Config) -> bool:
    """Returns True if an active slot or legacy database exists and is non-empty."""
    db_path, _ = resolve_active_public_db(config)
    return db_path.exists() and db_path.stat().st_size > 100


def choose_target_slot(active_slot: Optional[str]) -> SlotName:
    """Selects the inactive target slot for the next Red/Green deployment."""
    if active_slot == SLOT_RED:
        return SLOT_GREEN
    return SLOT_RED


def safe_remove_sqlite_files(db_path: Path) -> None:
    """Truncates in-place and unlinks a SQLite file and its journal/WAL companions."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = (
            db_path if suffix == "" else db_path.with_name(f"{db_path.name}{suffix}")
        )
        if candidate.exists():
            try:
                with open(candidate, "wb") as f_trunc:
                    f_trunc.truncate(0)
            except Exception:
                pass
            try:
                candidate.unlink()
            except Exception as exc:
                logger.warning("Could not unlink %s: %s", candidate, exc)


def cleanup_orphan_nfs_files(directory: Path) -> None:
    """Best-effort cleanup of orphaned .nfs* silly-rename files in a directory."""
    if not directory.exists():
        return
    try:
        for nfs_file in directory.glob(".nfs*"):
            try:
                with open(nfs_file, "wb") as f_nfs:
                    f_nfs.truncate(0)
                nfs_file.unlink()
                logger.info("Cleaned up orphaned NFS file: %s", nfs_file.name)
            except Exception:
                pass
    except Exception:
        pass


def build_readonly_immutable_uri(db_path: Path) -> str:
    """Builds a standard RFC file:// URI with SQLite read-only immutable flags."""
    return f"{db_path.resolve().as_uri()}?mode=ro&immutable=1"


def validate_candidate_sqlite(candidate_path: Path) -> Dict[str, Any]:
    """Validates an isolated candidate SQLite database without acquiring NFS write locks.

    Ensures:
    1. Valid SQLite3 100-byte header.
    2. Rollback journal mode (header bytes 18-19 == 1, 1); normalizes privately if WAL.
    3. Lock-free read-only PRAGMA integrity_check == 'ok'.
    4. At least one table exists; if production catalog tables exist, verifies non-zero rows.
    """
    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate database not found: {candidate_path}")

    file_size = candidate_path.stat().st_size
    if file_size < 100:
        raise ValueError(
            f"Candidate database too small to be valid SQLite ({file_size} bytes)"
        )

    with open(candidate_path, "rb") as f_hdr:
        header = f_hdr.read(100)

    if header[:16] != SQLITE_MAGIC_HEADER:
        raise ValueError("Invalid SQLite file header signature")

    write_ver, read_ver = header[18], header[19]
    if (write_ver, read_ver) != (1, 1):
        # Candidate is isolated in staging; convert WAL to standard rollback journal privately
        with sqlite3.connect(str(candidate_path), timeout=30.0) as rw_conn:
            rw_conn.execute("PRAGMA busy_timeout = 30000;")
            rw_conn.execute("PRAGMA journal_mode = DELETE;")

    uri = build_readonly_immutable_uri(candidate_path)
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        cursor = conn.cursor()
        integrity_res = cursor.execute("PRAGMA integrity_check;").fetchone()
        if not integrity_res or integrity_res[0] != "ok":
            raise ValueError(f"PRAGMA integrity_check failed: {integrity_res}")

        table_rows = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
        tables = {str(r[0]) for r in table_rows}
        if not tables:
            raise ValueError("Candidate SQLite database contains no tables")

        stats: Dict[str, Any] = {"tables_count": len(tables)}
        if "articles" in tables and "daily_prices" in tables:
            articles_cnt = int(
                cursor.execute("SELECT count(*) FROM articles;").fetchone()[0]
            )
            prices_cnt = int(
                cursor.execute("SELECT count(*) FROM daily_prices;").fetchone()[0]
            )
            if articles_cnt <= 0 or prices_cnt <= 0:
                raise ValueError(
                    f"Empty production catalog rejected (articles={articles_cnt}, daily_prices={prices_cnt})"
                )
            stats["articles_count"] = articles_cnt
            stats["prices_count"] = prices_cnt

        return stats
    finally:
        conn.close()


def activate_slot(
    config: Config,
    target_slot: SlotName,
    candidate_path: Path,
    db_sha256: str,
    archive_sha256: str = "",
) -> CatalogState:
    """Promotes a validated candidate SQLite file into target_slot and switches catalog_state.json."""
    old_state = load_catalog_state(config)
    _, current_active_slot = resolve_active_public_db(config)

    target_db_path = get_slot_db_path(config, target_slot)
    target_db_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure no companion journal/WAL remnants exist before atomic rename
    for suffix in ("-wal", "-shm", "-journal"):
        companion = target_db_path.with_name(f"{target_db_path.name}{suffix}")
        if companion.exists():
            try:
                companion.unlink()
            except Exception:
                pass

    # Move candidate onto target slot (brand-new inode)
    candidate_path.replace(target_db_path)

    final_size = target_db_path.stat().st_size
    now_iso = datetime.now(timezone.utc).isoformat()

    slot_meta = SlotMetadata(
        slot=target_slot,
        filename=target_db_path.name,
        db_sha256=db_sha256.lower(),
        archive_sha256=archive_sha256.lower(),
        size_bytes=final_size,
        synced_at=now_iso,
    )

    new_previous_slot: Optional[SlotName] = None
    if current_active_slot in VALID_SLOTS and current_active_slot != target_slot:
        prev_db_path = get_slot_db_path(config, current_active_slot)
        if prev_db_path.exists() and prev_db_path.stat().st_size > 0:
            new_previous_slot = current_active_slot

    new_slots: Dict[str, SlotMetadata] = {}
    if new_previous_slot and new_previous_slot in old_state.slots:
        new_slots[new_previous_slot] = old_state.slots[new_previous_slot]
    new_slots[target_slot] = slot_meta

    new_state = CatalogState(
        active_slot=target_slot,
        previous_slot=new_previous_slot,
        slots=new_slots,
        updated_at=now_iso,
    )
    save_catalog_state(config, new_state)
    return new_state


def rollback_slot(config: Config) -> CatalogState:
    """Atomically switches active_slot back to the validated standby slot."""
    state = load_catalog_state(config)
    _, current_active_slot = resolve_active_public_db(config)

    if current_active_slot not in VALID_SLOTS:
        raise RuntimeError(
            "No hay un slot Red/Green activo para revertir (modo legado o sin inicializar)."
        )

    standby_slot: SlotName = (
        state.previous_slot
        if state.previous_slot in VALID_SLOTS
        and state.previous_slot != current_active_slot
        else (SLOT_GREEN if current_active_slot == SLOT_RED else SLOT_RED)
    )
    standby_path = get_slot_db_path(config, standby_slot)

    if not standby_path.exists() or standby_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"El slot de respaldo '{standby_slot}' ({standby_path.name}) no está disponible en disco."
        )

    validate_candidate_sqlite(standby_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    new_slots = dict(state.slots)
    if standby_slot not in new_slots:
        new_slots[standby_slot] = SlotMetadata(
            slot=standby_slot,
            filename=standby_path.name,
            db_sha256=compute_file_sha256(standby_path),
            size_bytes=standby_path.stat().st_size,
            synced_at=now_iso,
        )

    active_path = get_slot_db_path(config, current_active_slot)
    new_prev: Optional[SlotName] = (
        current_active_slot
        if active_path.exists() and active_path.stat().st_size > 0
        else None
    )

    new_state = CatalogState(
        active_slot=standby_slot,
        previous_slot=new_prev,
        slots=new_slots,
        updated_at=now_iso,
    )
    save_catalog_state(config, new_state)
    return new_state


def get_slots_diagnostics(config: Config) -> Dict[str, Any]:
    """Returns diagnostic status of active/standby slots and files on disk."""
    state = load_catalog_state(config)
    active_path, active_slot = resolve_active_public_db(config)

    slots_info: Dict[str, Dict[str, Any]] = {}
    for slot in VALID_SLOTS:
        p = get_slot_db_path(config, slot)
        exists = p.exists() and p.stat().st_size > 0
        size_bytes = p.stat().st_size if exists else 0
        meta = state.slots.get(slot)
        slots_info[slot] = {
            "slot": slot,
            "filename": p.name,
            "path": str(p),
            "exists": exists,
            "size_bytes": size_bytes,
            "db_sha256": meta.db_sha256 if (meta and exists) else "",
            "synced_at": meta.synced_at if (meta and exists) else "",
            "is_active": active_slot == slot,
        }

    standby_slot: Optional[SlotName] = None
    if active_slot == SLOT_RED and slots_info[SLOT_GREEN]["exists"]:
        standby_slot = SLOT_GREEN
    elif active_slot == SLOT_GREEN and slots_info[SLOT_RED]["exists"]:
        standby_slot = SLOT_RED

    return {
        "active_slot": active_slot,
        "previous_slot": state.previous_slot,
        "standby_slot": standby_slot,
        "rollback_available": standby_slot is not None,
        "active_path": active_path,
        "active_filename": active_path.name,
        "slots": slots_info,
    }
