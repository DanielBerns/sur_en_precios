"""Maintenance mode manager for Sur en Precios public web application."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sur_en_precios.config import Config

logger = logging.getLogger("sur_en_precios.public_app.maintenance")


def get_maintenance_lock_path(config: Config) -> Path:
    """Returns the pathlib.Path for the maintenance lock file."""
    return config.data_dir / "maintenance.lock"


def set_maintenance_mode(config: Config, reason: str = "Catálogo en actualización") -> None:
    """Activates maintenance mode by writing a maintenance.lock file."""
    lock_path = get_maintenance_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": True,
        "reason": reason,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": config.get_sync_settings().timeout_seconds,
    }
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info("Maintenance mode activated: %s", reason)


def clear_maintenance_mode(config: Config) -> None:
    """Deactivates maintenance mode by deleting maintenance.lock."""
    lock_path = get_maintenance_lock_path(config)
    if lock_path.exists():
        try:
            lock_path.unlink()
            logger.info("Maintenance mode cleared.")
        except Exception as exc:
            logger.error("Failed to remove maintenance lock: %s", exc)


def is_maintenance_mode(config: Config) -> bool:
    """Checks whether the application is currently under maintenance with auto-expiration."""
    lock_path = get_maintenance_lock_path(config)
    if not lock_path.exists():
        return False

    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        started_at_str = data.get("started_at")
        timeout_seconds = data.get("timeout_seconds", 900)

        if started_at_str:
            started_at = datetime.fromisoformat(started_at_str)
            elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed_seconds > timeout_seconds:
                logger.warning(
                    "Maintenance lock expired (%d seconds elapsed > %d limit). Auto-clearing.",
                    elapsed_seconds,
                    timeout_seconds,
                )
                clear_maintenance_mode(config)
                return False

        return True
    except Exception as exc:
        logger.error("Failed reading maintenance lock file: %s", exc)
        return False
