"""Unit and integration tests for Red/Green catalog sync, zero-downtime cutover, rollback, and maintenance."""

from __future__ import annotations

import datetime as dt
import errno
import gzip
import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Tuple

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from werkzeug.serving import make_server

from sur_en_precios.config import AppConfig, Config, read_config
from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    PointOfSale,
    PublicBase,
)
from sur_en_precios.tools import run_daily_update
from sur_en_precios.tools.create_admin import create_admin_user
from sur_en_precios.tools.sync_client import run_sync_catalog_to_web
from sur_en_precios.web.public_app.application import create_public_app
from sur_en_precios.web.public_app.blueprints import sync as sync_module
from sur_en_precios.web.public_app.catalog_slots import (
    get_slot_db_path,
    load_catalog_state,
)
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    is_maintenance_mode,
    set_maintenance_mode,
)

SYNC_TOKEN = "secret_test_sync_token_2026"
AUTH_HEADERS = {"Authorization": f"Bearer {SYNC_TOKEN}"}


def _write_test_config(
    workdir: Path,
    *,
    server_url: str = "http://127.0.0.1:5000",
    sync_to_web: bool = True,
    retain_previous_slot: bool = True,
    chunk_size_bytes: int = 1024,
) -> None:
    """Writes a test config.yaml into workdir."""
    workdir.mkdir(parents=True, exist_ok=True)
    config_data = {
        "app": {"name": "Sur en Precios Test", "region": "AR-U", "debug": True},
        "database": {
            "public_db_filename": "public.sqlite",
            "user_db_filename": "user_data.sqlite",
            "control_db_filename": "control.sqlite",
        },
        "sync": {
            "sync_to_web": sync_to_web,
            "server_url": server_url,
            "api_token": SYNC_TOKEN,
            "chunk_size_bytes": chunk_size_bytes,
            "timeout_seconds": 60,
            "retain_previous_slot": retain_previous_slot,
        },
    }
    with open(workdir / "config.yaml", "w", encoding="utf-8") as f_cfg:
        yaml.dump(config_data, f_cfg)


@pytest.fixture
def app_env(tmp_path: Path):
    """Sets up a complete test environment with temporary directory and initialized app."""
    workdir = tmp_path / "workdir"
    _write_test_config(workdir)

    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    return app, client, workdir


def _build_populated_catalog_sqlite(
    db_path: Path,
    product_name: str = "Yerba Mate Patagonia 1kg",
    ean: str = "7790001000012",
    price_ars: int = 4200,
    wal_mode: bool = False,
) -> Tuple[bytes, str, str]:
    """Creates a realistic PublicBase SQLite catalog and returns (gz_bytes, gz_sha256, db_sha256)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(f"sqlite:///{db_path}")
    PublicBase.metadata.create_all(engine)
    with Session(engine) as session:
        article = Article(
            ean=ean,
            name=product_name,
            clean_description=product_name,
            brand_name="Patagonia",
            package="1 kg",
            package_amount=1.0,
            package_unit="kg",
        )
        pos = PointOfSale(
            code="AR-U-CR-001",
            brand_name="La Anónima",
            branch_name="Centro",
            city="Comodoro Rivadavia",
            province="Chubut",
            province_code="AR-U",
        )
        session.add_all([article, pos])
        session.flush()
        session.add(
            DailyPrice(
                date=dt.date(2026, 10, 24),
                ean=ean,
                store_code="AR-U-CR-001",
                price=price_ars,
                unit_price=float(price_ars),
            )
        )
        session.commit()
    engine.dispose()

    with sqlite3.connect(str(db_path)) as conn:
        if wal_mode:
            conn.execute("PRAGMA journal_mode = WAL;")
        else:
            conn.execute("PRAGMA journal_mode = DELETE;")

    raw_bytes = db_path.read_bytes()
    db_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    gz_bytes = gzip.compress(raw_bytes, compresslevel=6)
    gz_sha256 = hashlib.sha256(gz_bytes).hexdigest()
    return gz_bytes, gz_sha256, db_sha256


def _upload_catalog_via_client(
    client: Any,
    gz_bytes: bytes,
    gz_sha256: str,
    db_sha256: str,
    chunk_size: int = 512,
) -> Tuple[Any, Any]:
    """Executes /start, /chunk/*, and /finish/* against a Flask test client."""
    chunks = [gz_bytes[i : i + chunk_size] for i in range(0, len(gz_bytes), chunk_size)]
    res_start = client.post(
        "/api/admin/sync/start",
        json={
            "filename": "public.sqlite.gz",
            "expected_chunks": len(chunks),
            "expected_size_bytes": len(gz_bytes),
            "sha256": gz_sha256,
            "db_sha256": db_sha256,
        },
        headers=AUTH_HEADERS,
    )
    assert res_start.status_code == 201
    upload_id = res_start.get_json()["upload_id"]

    for idx, chunk in enumerate(chunks):
        res_chunk = client.put(
            f"/api/admin/sync/chunk/{upload_id}/{idx}",
            data=chunk,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        assert res_chunk.status_code == 200
        assert res_chunk.get_json()["chunk_index"] == idx

    res_finish = client.post(
        f"/api/admin/sync/finish/{upload_id}",
        headers=AUTH_HEADERS,
    )
    return res_start, res_finish


class TestMaintenanceMode:
    """Tests for maintenance mode flag handling and expiration."""

    def test_set_and_clear_maintenance_mode(self, tmp_path: Path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        cfg = Config(AppConfig(), workdir)

        assert is_maintenance_mode(cfg) is False

        set_maintenance_mode(cfg, reason="Testing maintenance")
        assert is_maintenance_mode(cfg) is True

        clear_maintenance_mode(cfg)
        assert is_maintenance_mode(cfg) is False

    def test_maintenance_expiration(self, tmp_path: Path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        app_cfg = AppConfig()
        app_cfg.sync.timeout_seconds = 1
        cfg = Config(app_cfg, workdir)

        set_maintenance_mode(cfg, reason="Quick timeout")
        lock_file = cfg.data_dir / "maintenance.lock"
        with open(lock_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        data["started_at"] = "2020-01-01T00:00:00+00:00"
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        assert is_maintenance_mode(cfg) is False
        assert not lock_file.exists()


class TestSyncApiSecurityAndInterception:
    """Tests for token verification, CSRF bypass, and 503 maintenance page interception."""

    def test_sync_status_requires_bearer_token(self, app_env):
        _, client, _ = app_env

        res = client.get("/api/admin/sync/status")
        assert res.status_code == 401

        res = client.get(
            "/api/admin/sync/status",
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert res.status_code == 403

        res = client.get("/api/admin/sync/status", headers=AUTH_HEADERS)
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "online"
        assert data["maintenance_mode"] is False
        assert "active_slot" in data
        assert "slots" in data

    def test_maintenance_mode_intercepts_public_traffic_with_503(self, app_env):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]

        set_maintenance_mode(config, reason="Manual maintenance window")

        res_pub = client.get("/")
        assert res_pub.status_code == 503
        assert res_pub.headers.get("Retry-After") == "300"
        assert "Actualizando Catálogo Diario" in res_pub.get_data(as_text=True)

        res_sync = client.get("/api/admin/sync/status", headers=AUTH_HEADERS)
        assert res_sync.status_code == 200
        assert res_sync.get_json()["maintenance_mode"] is True

        clear_maintenance_mode(config)
        res_pub_after = client.get("/")
        assert res_pub_after.status_code in (200, 302)


class TestSyncRedGreenLifecycle:
    """Tests for Red/Green slot rotation, zero-downtime reads, and multi-worker rebinding."""

    def test_cold_start_enables_maintenance_only_when_no_catalog_exists(
        self, app_env, tmp_path: Path
    ):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]

        # Simulate true cold start with no catalog file on disk
        legacy_db = config.get_public_db_path()
        if legacy_db.exists():
            legacy_db.unlink()

        gz_bytes, gz_sha256, db_sha256 = _build_populated_catalog_sqlite(
            tmp_path / "cold_start.sqlite",
            product_name="Leche Entera ColdStart 1L",
        )

        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_bytes),
                "sha256": gz_sha256,
                "db_sha256": db_sha256,
            },
            headers=AUTH_HEADERS,
        )
        assert res_start.status_code == 201
        assert res_start.get_json()["target_slot"] == "red"
        assert is_maintenance_mode(config) is True

        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_bytes,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}",
            headers=AUTH_HEADERS,
        )
        assert res_finish.status_code == 200
        assert res_finish.get_json()["active_slot"] == "red"
        assert is_maintenance_mode(config) is False

        red_db = get_slot_db_path(config, "red")
        assert red_db.exists()
        res_search = client.get("/?q=ColdStart")
        assert res_search.status_code == 200
        assert "Leche Entera ColdStart 1L" in res_search.get_data(as_text=True)

    def test_zero_downtime_three_generation_rotation_and_legacy_retirement(
        self, app_env, tmp_path: Path
    ):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]
        legacy_db = config.get_public_db_path()
        assert legacy_db.exists()

        # Generation 1 -> Slot RED
        gz_v1, gz_sha_v1, db_sha_v1 = _build_populated_catalog_sqlite(
            tmp_path / "gen1.sqlite",
            product_name="Yerba Generacion Roja",
            price_ars=3500,
        )
        res_start_1, res_finish_1 = _upload_catalog_via_client(
            client, gz_v1, gz_sha_v1, db_sha_v1
        )
        assert res_start_1.get_json()["target_slot"] == "red"
        assert is_maintenance_mode(config) is False
        assert res_finish_1.status_code == 200
        assert res_finish_1.get_json()["active_slot"] == "red"
        assert get_slot_db_path(config, "red").exists()
        assert not any(config.sync_staging_dir.iterdir())

        # Verify catalog_meta.json and /status
        meta_file = config.data_dir / "catalog_meta.json"
        assert meta_file.exists()
        meta_json = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta_json["active_slot"] == "red"
        assert meta_json["db_sha256"] == db_sha_v1
        assert meta_json["archive_sha256"] == gz_sha_v1

        # Generation 2 -> Slot GREEN (while RED continues serving 200 OK!)
        gz_v2, gz_sha_v2, db_sha_v2 = _build_populated_catalog_sqlite(
            tmp_path / "gen2.sqlite",
            product_name="Yerba Generacion Verde",
            price_ars=3900,
        )
        chunks_v2 = [gz_v2[i : i + 512] for i in range(0, len(gz_v2), 512)]
        res_start_2 = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": len(chunks_v2),
                "expected_size_bytes": len(gz_v2),
                "sha256": gz_sha_v2,
                "db_sha256": db_sha_v2,
            },
            headers=AUTH_HEADERS,
        )
        assert res_start_2.status_code == 201
        assert res_start_2.get_json()["target_slot"] == "green"
        assert is_maintenance_mode(config) is False
        # Legacy public.sqlite is retired automatically once Red/Green is active
        assert not legacy_db.exists()

        upload_id_2 = res_start_2.get_json()["upload_id"]
        for idx, chunk in enumerate(chunks_v2):
            client.put(
                f"/api/admin/sync/chunk/{upload_id_2}/{idx}",
                data=chunk,
                headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
            )
            # Mid-upload public search must stay 200 OK serving RED data
            live_resp = client.get("/?q=Yerba")
            assert live_resp.status_code == 200
            assert "Yerba Generacion Roja" in live_resp.get_data(as_text=True)

        res_finish_2 = client.post(
            f"/api/admin/sync/finish/{upload_id_2}",
            headers=AUTH_HEADERS,
        )
        assert res_finish_2.status_code == 200
        fin2 = res_finish_2.get_json()
        assert fin2["active_slot"] == "green"
        assert fin2["previous_slot"] == "red"
        assert get_slot_db_path(config, "green").exists()
        assert get_slot_db_path(config, "red").exists()  # Standby retained

        live_after_2 = client.get("/?q=Yerba")
        assert live_after_2.status_code == 200
        assert "Yerba Generacion Verde" in live_after_2.get_data(as_text=True)

        # Generation 3 -> Reclaims RED before upload, promotes new RED
        gz_v3, gz_sha_v3, db_sha_v3 = _build_populated_catalog_sqlite(
            tmp_path / "gen3.sqlite",
            product_name="Yerba Generacion Roja Dos",
            price_ars=4100,
        )
        res_start_3 = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_v3),
                "sha256": gz_sha_v3,
                "db_sha256": db_sha_v3,
            },
            headers=AUTH_HEADERS,
        )
        assert res_start_3.status_code == 201
        assert res_start_3.get_json()["target_slot"] == "red"
        # Inactive RED slot reclaimed immediately at /start to preserve disk quota
        assert not get_slot_db_path(config, "red").exists()
        assert get_slot_db_path(config, "green").exists()

        upload_id_3 = res_start_3.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id_3}/0",
            data=gz_v3,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish_3 = client.post(
            f"/api/admin/sync/finish/{upload_id_3}",
            headers=AUTH_HEADERS,
        )
        assert res_finish_3.status_code == 200
        assert res_finish_3.get_json()["active_slot"] == "red"
        assert res_finish_3.get_json()["previous_slot"] == "green"

        live_after_3 = client.get("/?q=Yerba")
        assert "Yerba Generacion Roja Dos" in live_after_3.get_data(as_text=True)

    def test_multi_worker_automatic_slot_rebinding_without_restart(
        self, tmp_path: Path
    ):
        workdir = tmp_path / "multiworker_workdir"
        _write_test_config(workdir)

        worker_1 = create_public_app(workdir=workdir)
        worker_1.config["TESTING"] = True
        client_1 = worker_1.test_client()

        worker_2 = create_public_app(workdir=workdir)
        worker_2.config["TESTING"] = True
        client_2 = worker_2.test_client()

        # Upload v1 (RED) on Worker 1 -> Worker 2 must automatically bind to RED
        gz_v1, gz_sha_v1, db_sha_v1 = _build_populated_catalog_sqlite(
            tmp_path / "mw1.sqlite",
            product_name="Aceite Girasol WorkerUno",
        )
        _, finish_1 = _upload_catalog_via_client(client_1, gz_v1, gz_sha_v1, db_sha_v1)
        assert finish_1.status_code == 200

        res_w2_v1 = client_2.get("/?q=Aceite")
        assert res_w2_v1.status_code == 200
        assert "Aceite Girasol WorkerUno" in res_w2_v1.get_data(as_text=True)

        # Upload v2 (GREEN) on Worker 1 -> Worker 2 must automatically rebind to GREEN
        gz_v2, gz_sha_v2, db_sha_v2 = _build_populated_catalog_sqlite(
            tmp_path / "mw2.sqlite",
            product_name="Aceite Girasol WorkerDos",
        )
        _, finish_2 = _upload_catalog_via_client(client_1, gz_v2, gz_sha_v2, db_sha_v2)
        assert finish_2.status_code == 200

        res_w2_v2 = client_2.get("/?q=Aceite")
        assert res_w2_v2.status_code == 200
        html_w2 = res_w2_v2.get_data(as_text=True)
        assert "Aceite Girasol WorkerDos" in html_w2
        assert "Aceite Girasol WorkerUno" not in html_w2

        # Immutable read-only mode must not create any companion lock/WAL/journal files
        data_files = {p.name for p in (workdir / "data").iterdir()}
        assert not any(
            name.endswith(("-wal", "-shm", "-journal")) for name in data_files
        )

    def test_retain_previous_slot_false_deletes_standby_immediately(
        self, tmp_path: Path
    ):
        workdir = tmp_path / "no_retain_workdir"
        _write_test_config(workdir, retain_previous_slot=False)
        app = create_public_app(workdir=workdir)
        app.config["TESTING"] = True
        client = app.test_client()
        config = app.config["APP_CONFIG"]

        gz_v1, gz_sha_v1, db_sha_v1 = _build_populated_catalog_sqlite(
            tmp_path / "nr1.sqlite", product_name="Producto Uno"
        )
        _upload_catalog_via_client(client, gz_v1, gz_sha_v1, db_sha_v1)
        assert get_slot_db_path(config, "red").exists()

        gz_v2, gz_sha_v2, db_sha_v2 = _build_populated_catalog_sqlite(
            tmp_path / "nr2.sqlite", product_name="Producto Dos"
        )
        _upload_catalog_via_client(client, gz_v2, gz_sha_v2, db_sha_v2)

        assert get_slot_db_path(config, "green").exists()
        assert not get_slot_db_path(config, "red").exists()

        status_data = client.get(
            "/api/admin/sync/status", headers=AUTH_HEADERS
        ).get_json()
        assert status_data["active_slot"] == "green"
        assert status_data["rollback_available"] is False


class TestSyncFailureIsolationAndEdgeCases:
    """Verifies failed uploads never corrupt or interrupt the currently active slot."""

    def _seed_active_red_slot(self, client: Any, tmp_path: Path) -> str:
        gz_v1, gz_sha_v1, db_sha_v1 = _build_populated_catalog_sqlite(
            tmp_path / "seed_red.sqlite",
            product_name="Arroz Activo Protegido",
        )
        _, res_finish = _upload_catalog_via_client(client, gz_v1, gz_sha_v1, db_sha_v1)
        assert res_finish.status_code == 200
        return db_sha_v1

    def test_compressed_checksum_mismatch_aborts_and_preserves_active_slot(
        self, app_env, tmp_path: Path
    ):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]
        seed_sha = self._seed_active_red_slot(client, tmp_path)

        gz_bad, _, _ = _build_populated_catalog_sqlite(
            tmp_path / "mismatch.sqlite", product_name="Arroz Invalido"
        )
        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_bad),
                "sha256": "0" * 64,
            },
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_bad,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}", headers=AUTH_HEADERS
        )
        assert res_finish.status_code == 400
        assert "SHA-256 no coincide" in res_finish.get_json()["error"]
        assert is_maintenance_mode(config) is False

        # Active RED slot must remain untouched and online
        state = load_catalog_state(config)
        assert state.active_slot == "red"
        assert state.slots["red"].db_sha256 == seed_sha
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )

    def test_uncompressed_db_checksum_mismatch_preserves_active_slot(
        self, app_env, tmp_path: Path
    ):
        _, client, _ = app_env
        self._seed_active_red_slot(client, tmp_path)

        gz_bytes, gz_sha, _ = _build_populated_catalog_sqlite(
            tmp_path / "db_mismatch.sqlite", product_name="Arroz Corrupto"
        )
        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_bytes),
                "sha256": gz_sha,
                "db_sha256": "f" * 64,
            },
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_bytes,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}", headers=AUTH_HEADERS
        )
        assert res_finish.status_code == 400
        assert "SHA-256 de base SQLite no coincide" in res_finish.get_json()["error"]
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )

    def test_corrupted_gzip_returns_500_and_preserves_active_slot(
        self, app_env, tmp_path: Path
    ):
        _, client, _ = app_env
        self._seed_active_red_slot(client, tmp_path)

        bad_payload = b"not-a-valid-gzip-stream"
        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(bad_payload),
                "sha256": hashlib.sha256(bad_payload).hexdigest(),
            },
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=bad_payload,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}", headers=AUTH_HEADERS
        )
        assert res_finish.status_code == 500
        assert "Fallo al descomprimir" in res_finish.get_json()["error"]
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )

    def test_empty_production_catalog_rejected_and_preserves_active_slot(
        self, app_env, tmp_path: Path
    ):
        _, client, _ = app_env
        self._seed_active_red_slot(client, tmp_path)

        # Create a PublicBase DB with tables but 0 articles and 0 daily_prices
        empty_db = tmp_path / "empty_catalog.sqlite"
        engine = create_engine(f"sqlite:///{empty_db}")
        PublicBase.metadata.create_all(engine)
        engine.dispose()

        raw_empty = empty_db.read_bytes()
        gz_empty = gzip.compress(raw_empty)
        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_empty),
                "sha256": hashlib.sha256(gz_empty).hexdigest(),
                "db_sha256": hashlib.sha256(raw_empty).hexdigest(),
            },
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_empty,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}", headers=AUTH_HEADERS
        )
        assert res_finish.status_code == 500
        assert "Empty production catalog rejected" in res_finish.get_json()["error"]
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )

    def test_disk_quota_exceeded_returns_507_and_cleans_staging(
        self, app_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]
        self._seed_active_red_slot(client, tmp_path)

        gz_bytes, gz_sha, db_sha = _build_populated_catalog_sqlite(
            tmp_path / "quota.sqlite", product_name="Arroz Sin Cuota"
        )
        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_bytes),
                "sha256": gz_sha,
                "db_sha256": db_sha,
            },
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_bytes,
            headers={**AUTH_HEADERS, "Content-Type": "application/octet-stream"},
        )

        def _raise_edquot(self_stream: Any, b: Any) -> int:
            raise OSError(errno.EDQUOT, "Disk quota exceeded")

        monkeypatch.setattr(sync_module.ChunkPartStream, "readinto", _raise_edquot)

        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}", headers=AUTH_HEADERS
        )
        assert res_finish.status_code == 507
        assert "Disk quota exceeded" in res_finish.get_json()["error"]
        assert not (config.sync_staging_dir / upload_id).exists()
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )

    def test_sync_abort_cleans_up_staging_without_touching_active_slot(
        self, app_env, tmp_path: Path
    ):
        app, client, _ = app_env
        config = app.config["APP_CONFIG"]
        self._seed_active_red_slot(client, tmp_path)

        res_start = client.post(
            "/api/admin/sync/start",
            json={"expected_chunks": 3, "sha256": "abc"},
            headers=AUTH_HEADERS,
        )
        upload_id = res_start.get_json()["upload_id"]
        assert (config.sync_staging_dir / upload_id).exists()
        assert is_maintenance_mode(config) is False

        res_abort = client.post(
            f"/api/admin/sync/abort/{upload_id}",
            headers=AUTH_HEADERS,
        )
        assert res_abort.status_code == 200
        assert not (config.sync_staging_dir / upload_id).exists()
        assert "Arroz Activo Protegido" in client.get("/?q=Arroz").get_data(
            as_text=True
        )


class TestRollbackAndEndToEndClient:
    """Tests for API/Admin rollback and end-to-end aiohttp sync_client execution."""

    def test_api_and_admin_ui_rollback_workflow(self, tmp_path: Path):
        workdir = tmp_path / "rollback_workdir"
        _write_test_config(workdir)

        create_admin_user(
            username="admin_rollback",
            password="SuperAdminPassword123!",
            workdir_override=workdir,
        )

        app = create_public_app(workdir=workdir)
        app.config["TESTING"] = False
        app.config["CSRF_ENABLED"] = True
        client = app.test_client()

        # Before any Red/Green sync -> 409 Conflict
        res_early_rb = client.post("/api/admin/sync/rollback", headers=AUTH_HEADERS)
        assert res_early_rb.status_code == 409

        # Sync 1 -> RED
        gz_v1, gz_sha_v1, db_sha_v1 = _build_populated_catalog_sqlite(
            tmp_path / "rb_v1.sqlite", product_name="Harina Version Roja"
        )
        _upload_catalog_via_client(client, gz_v1, gz_sha_v1, db_sha_v1)

        # Still no standby slot -> 409 Conflict
        res_single_rb = client.post("/api/admin/sync/rollback", headers=AUTH_HEADERS)
        assert res_single_rb.status_code == 409

        # Sync 2 -> GREEN (RED becomes standby)
        gz_v2, gz_sha_v2, db_sha_v2 = _build_populated_catalog_sqlite(
            tmp_path / "rb_v2.sqlite", product_name="Harina Version Verde"
        )
        _upload_catalog_via_client(client, gz_v2, gz_sha_v2, db_sha_v2)
        assert "Harina Version Verde" in client.get("/?q=Harina").get_data(as_text=True)

        # API Rollback: GREEN -> RED
        res_api_rb = client.post("/api/admin/sync/rollback", headers=AUTH_HEADERS)
        assert res_api_rb.status_code == 200
        assert res_api_rb.get_json()["active_slot"] == "red"
        assert "Harina Version Roja" in client.get("/?q=Harina").get_data(as_text=True)

        # Admin UI login with CSRF enabled, inspect /admin/system, and trigger UI rollback (RED -> GREEN)
        login_get = client.get("/auth/login").get_data(as_text=True)
        csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_get)
        assert csrf_match is not None
        csrf_tok = csrf_match.group(1)

        res_login = client.post(
            "/auth/login",
            data={
                "csrf_token": csrf_tok,
                "username": "admin_rollback",
                "password": "SuperAdminPassword123!",
            },
            follow_redirects=True,
        )
        assert res_login.status_code == 200

        sys_html = client.get("/admin/system").get_data(as_text=True)
        assert "RED (public_red.sqlite)" in sys_html
        assert "Revertir al Slot Anterior (GREEN)" in sys_html

        sys_csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', sys_html)
        assert sys_csrf_match is not None

        res_ui_rb = client.post(
            "/admin/system/rollback",
            data={"csrf_token": sys_csrf_match.group(1)},
            follow_redirects=True,
        )
        assert res_ui_rb.status_code == 200
        ui_html = res_ui_rb.get_data(as_text=True)
        assert "Catálogo revertido exitosamente" in ui_html
        assert "GREEN (public_green.sqlite)" in ui_html
        assert "Harina Version Verde" in client.get("/?q=Harina").get_data(as_text=True)

    def test_end_to_end_aiohttp_sync_client_and_rollback(self, tmp_path: Path):
        server_workdir = tmp_path / "remote_pa_workdir"
        _write_test_config(server_workdir, sync_to_web=False)
        server_app = create_public_app(workdir=server_workdir)

        http_server = make_server("127.0.0.1", 0, server_app)
        port = http_server.server_port
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()

        try:
            client_workdir = tmp_path / "local_unpsjb_workdir"
            _write_test_config(
                client_workdir,
                server_url=f"http://127.0.0.1:{port}",
                sync_to_web=True,
                chunk_size_bytes=1024,
            )
            client_cfg = read_config(
                workdir_override=client_workdir, should_create_override=False
            )

            # Build local DB in WAL mode to verify client normalizes to DELETE before hashing
            _build_populated_catalog_sqlite(
                client_cfg.get_public_db_path(),
                product_name="Fideos Remotos Uno",
                wal_mode=True,
            )

            # 1. Initial upload -> RED
            res_1 = run_sync_catalog_to_web(workdir_override=client_workdir)
            assert res_1["status"] == "SUCCESS"
            assert res_1["server_response"]["active_slot"] == "red"

            # 2. Second identical upload -> SKIPPED_IDENTICAL_HASH
            res_skip = run_sync_catalog_to_web(workdir_override=client_workdir)
            assert res_skip["status"] == "SKIPPED_IDENTICAL_HASH"
            assert res_skip["active_slot"] == "red"

            # 3. Updated local DB -> GREEN
            _build_populated_catalog_sqlite(
                client_cfg.get_public_db_path(),
                product_name="Fideos Remotos Dos",
                price_ars=2900,
            )
            res_2 = run_sync_catalog_to_web(workdir_override=client_workdir)
            assert res_2["status"] == "SUCCESS"
            assert res_2["server_response"]["active_slot"] == "green"

            # 4. Remote CLI rollback -> RED
            res_rb = run_sync_catalog_to_web(
                workdir_override=client_workdir, rollback=True
            )
            assert res_rb["status"] == "rolled_back"
            assert res_rb["active_slot"] == "red"
        finally:
            http_server.shutdown()
            server_thread.join(timeout=5)

    def test_run_daily_update_retries_remote_sync_when_local_etl_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        workdir = tmp_path / "daily_retry_workdir"
        _write_test_config(workdir, sync_to_web=True)
        cfg = read_config(workdir_override=workdir, should_create_override=False)

        _build_populated_catalog_sqlite(
            cfg.get_public_db_path(), product_name="Azucar Retry"
        )

        etl_called = False
        sync_called = False

        async def _fake_harvest(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"new_count": 0, "extracted_files": []}

        def _fake_etl(*args: Any, **kwargs: Any) -> None:
            nonlocal etl_called
            etl_called = True

        async def _fake_sync(passed_cfg: Config) -> dict[str, Any]:
            nonlocal sync_called
            sync_called = True
            return {"status": "SUCCESS"}

        monkeypatch.setattr(run_daily_update, "run_harvest", _fake_harvest)
        monkeypatch.setattr(run_daily_update, "run_etl_pipeline", _fake_etl)
        monkeypatch.setattr(run_daily_update, "sync_catalog_to_web", _fake_sync)

        result = run_daily_update.run_daily_update_sync(workdir_override=workdir)
        assert result["status"] == "SUCCESS"
        assert etl_called is False
        assert sync_called is True


class TestConfigSyncSettings:
    """Verifies that config.yaml properly controls sync-to-web and slot retention."""

    def test_config_reads_sync_settings(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "sync": {
                        "sync_to_web": True,
                        "api_token": "token123",
                        "retain_previous_slot": False,
                    }
                },
                f,
            )

        cfg = read_config(workdir_override=tmp_path, should_create_override=False)
        assert cfg.get_sync_settings().sync_to_web is True
        assert cfg.get_sync_settings().api_token == "token123"
        assert cfg.get_sync_settings().retain_previous_slot is False

        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        cfg2 = read_config(workdir_override=tmp_path, should_create_override=False)
        assert cfg2.get_sync_settings().sync_to_web is False
        assert cfg2.get_sync_settings().retain_previous_slot is True
