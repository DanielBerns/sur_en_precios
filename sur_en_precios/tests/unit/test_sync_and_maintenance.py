"""Unit tests for UNPSJB-to-PythonAnywhere sync endpoints, maintenance mode, and security."""

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from sur_en_precios.config import AppConfig, Config, read_config
from sur_en_precios.web.public_app.application import create_public_app
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    is_maintenance_mode,
    set_maintenance_mode,
)


@pytest.fixture
def app_env(tmp_path: Path):
    """Sets up a complete test environment with temporary directory and initialized app."""
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)

    config_data = {
        "app": {"name": "Sur en Precios Test", "region": "AR-B", "debug": True},
        "database": {
            "public_db_filename": "public.sqlite",
            "user_db_filename": "user_data.sqlite",
            "control_db_filename": "control.sqlite",
        },
        "sync": {
            "sync_to_web": True,
            "server_url": "http://localhost:5000",
            "api_token": "secret_test_sync_token_2026",
            "chunk_size_bytes": 1024,  # Small chunk size for testing
            "timeout_seconds": 60,
        },
    }
    with open(workdir / "config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    return app, client, workdir


def _create_sample_sqlite_db(db_path: Path) -> bytes:
    """Creates a minimal valid SQLite database with a sample table and returns gzipped bytes."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE test_catalog (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO test_catalog (name) VALUES ('Yerba Mate 1kg');")
        conn.commit()

    with open(db_path, "rb") as f_in:
        raw_bytes = f_in.read()

    return gzip.compress(raw_bytes, compresslevel=6)


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
        app_cfg.sync.timeout_seconds = 1  # 1 second timeout
        cfg = Config(app_cfg, workdir)

        set_maintenance_mode(cfg, reason="Quick timeout")
        # Artificially alter the started_at timestamp in the lock file to simulate elapsed time
        lock_file = cfg.data_dir / "maintenance.lock"
        with open(lock_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        data["started_at"] = "2020-01-01T00:00:00+00:00"
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Should auto-clear due to expiration
        assert is_maintenance_mode(cfg) is False
        assert not lock_file.exists()


class TestSyncApiSecurityAndInterception:
    """Tests for token verification, CSRF bypass, and 503 maintenance page interception."""

    def test_sync_status_requires_bearer_token(self, app_env):
        _, client, _ = app_env

        # 1. No Authorization header -> 401
        res = client.get("/api/admin/sync/status")
        assert res.status_code == 401

        # 2. Invalid Bearer token -> 403
        res = client.get(
            "/api/admin/sync/status",
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert res.status_code == 403

        # 3. Valid Bearer token -> 200
        res = client.get(
            "/api/admin/sync/status",
            headers={"Authorization": "Bearer secret_test_sync_token_2026"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "online"
        assert data["maintenance_mode"] is False

    def test_maintenance_mode_intercepts_public_traffic_with_503(self, app_env):
        app, client, workdir = app_env
        config = app.config["APP_CONFIG"]

        # Activate maintenance mode
        set_maintenance_mode(config, reason="SEPA refresh in progress")

        # Public route should return 503 Service Unavailable
        res_pub = client.get("/")
        assert res_pub.status_code == 503
        assert res_pub.headers.get("Retry-After") == "300"
        assert "Actualizando Catálogo Diario" in res_pub.get_data(as_text=True)

        # Sync API route should still be accessible
        res_sync = client.get(
            "/api/admin/sync/status",
            headers={"Authorization": "Bearer secret_test_sync_token_2026"},
        )
        assert res_sync.status_code == 200
        assert res_sync.get_json()["maintenance_mode"] is True

        # Clear maintenance
        clear_maintenance_mode(config)
        res_pub_after = client.get("/")
        assert res_pub_after.status_code in (200, 302)


class TestSyncFullTransaction:
    """Tests for complete chunk transfer lifecycle, atomic swap, and checksum validation."""

    def test_sync_successful_lifecycle(self, app_env, tmp_path: Path):
        app, client, workdir = app_env
        config = app.config["APP_CONFIG"]

        # Generate sample sqlite and compress it
        sample_db_file = tmp_path / "sample.sqlite"
        gz_bytes = _create_sample_sqlite_db(sample_db_file)
        gz_sha256 = hashlib.sha256(gz_bytes).hexdigest()
        total_size = len(gz_bytes)

        chunk_size = 512
        chunks = [
            gz_bytes[i : i + chunk_size] for i in range(0, total_size, chunk_size)
        ]
        total_chunks = len(chunks)

        auth_headers = {"Authorization": "Bearer secret_test_sync_token_2026"}

        # 1. Start sync
        start_payload = {
            "filename": "public.sqlite.gz",
            "expected_chunks": total_chunks,
            "expected_size_bytes": total_size,
            "sha256": gz_sha256,
        }
        res_start = client.post(
            "/api/admin/sync/start",
            json=start_payload,
            headers=auth_headers,
        )
        assert res_start.status_code == 201
        upload_id = res_start.get_json()["upload_id"]
        assert is_maintenance_mode(config) is True

        # 2. Upload chunks
        for idx, chunk in enumerate(chunks):
            res_chunk = client.put(
                f"/api/admin/sync/chunk/{upload_id}/{idx}",
                data=chunk,
                headers={
                    **auth_headers,
                    "Content-Type": "application/octet-stream",
                },
            )
            assert res_chunk.status_code == 200
            assert res_chunk.get_json()["chunk_index"] == idx

        # 3. Finish sync
        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}",
            headers=auth_headers,
        )
        assert res_finish.status_code == 200
        assert is_maintenance_mode(config) is False

        # 4. Verify public.sqlite exists and contains the sample table
        public_db = config.get_public_db_path()
        assert public_db.exists()
        with sqlite3.connect(str(public_db)) as conn:
            row = conn.execute(
                "SELECT name FROM test_catalog WHERE id = 1"
            ).fetchone()
            assert row[0] == "Yerba Mate 1kg"

    def test_sync_checksum_mismatch_aborts_transaction(self, app_env, tmp_path: Path):
        app, client, workdir = app_env
        config = app.config["APP_CONFIG"]

        sample_db_file = tmp_path / "sample_mismatch.sqlite"
        gz_bytes = _create_sample_sqlite_db(sample_db_file)
        fake_sha256 = "0" * 64

        auth_headers = {"Authorization": "Bearer secret_test_sync_token_2026"}

        res_start = client.post(
            "/api/admin/sync/start",
            json={
                "filename": "public.sqlite.gz",
                "expected_chunks": 1,
                "expected_size_bytes": len(gz_bytes),
                "sha256": fake_sha256,
            },
            headers=auth_headers,
        )
        upload_id = res_start.get_json()["upload_id"]

        client.put(
            f"/api/admin/sync/chunk/{upload_id}/0",
            data=gz_bytes,
            headers={
                **auth_headers,
                "Content-Type": "application/octet-stream",
            },
        )

        res_finish = client.post(
            f"/api/admin/sync/finish/{upload_id}",
            headers=auth_headers,
        )
        assert res_finish.status_code == 400
        assert "SHA-256 no coincide" in res_finish.get_json()["error"]
        assert is_maintenance_mode(config) is False

    def test_sync_abort_cleans_up(self, app_env):
        app, client, workdir = app_env
        config = app.config["APP_CONFIG"]
        auth_headers = {"Authorization": "Bearer secret_test_sync_token_2026"}

        res_start = client.post(
            "/api/admin/sync/start",
            json={"expected_chunks": 5, "sha256": "abc"},
            headers=auth_headers,
        )
        upload_id = res_start.get_json()["upload_id"]
        assert is_maintenance_mode(config) is True

        res_abort = client.post(
            f"/api/admin/sync/abort/{upload_id}",
            headers=auth_headers,
        )
        assert res_abort.status_code == 200
        assert is_maintenance_mode(config) is False


class TestConfigSyncSettings:
    """Verifies that config.yaml properly controls sync-to-web without CLI flags."""

    def test_config_reads_sync_to_web(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump({"sync": {"sync_to_web": True, "api_token": "token123"}}, f)

        cfg = read_config(workdir_override=tmp_path, should_create_override=False)
        assert cfg.get_sync_settings().sync_to_web is True
        assert cfg.get_sync_settings().api_token == "token123"

        # Now test default / unset
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        cfg2 = read_config(workdir_override=tmp_path, should_create_override=False)
        assert cfg2.get_sync_settings().sync_to_web is False
