import json
from datetime import date
from pathlib import Path

import pytest

from sur_en_precios.config import read_config
from sur_en_precios.tools.log_analyzer import analyze_log_file, run_log_analyzer
from sur_en_precios.tools.run_etl import (
    find_latest_raw_date,
    run_etl_pipeline,
)


def test_log_analyzer_filtering(tmp_path: Path) -> None:
    log_file = tmp_path / "test.log.json"
    lines = [
        {
            "timestamp": "2026-10-01 10:00:00,000",
            "level": "INFO",
            "message": "Harvest started",
            "module": "harvester",
        },
        {
            "timestamp": "2026-10-01 10:05:00,000",
            "level": "ERROR",
            "message": "Connection timeout",
            "module": "scraper",
        },
        {
            "timestamp": "2026-10-02 12:00:00,000",
            "level": "INFO",
            "message": "ETL complete",
            "module": "etl",
        },
        {
            "timestamp": "2026-10-02 12:01:00,000",
            "level": "WARNING",
            "message": "Missing column",
            "module": "etl",
        },
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")
        f.write("Not valid json\n\n")

    # Filter by level
    errors = analyze_log_file(log_file, level_filter="ERROR")
    assert len(errors) == 1
    assert errors[0]["message"] == "Connection timeout"

    # Filter by date
    oct_1 = analyze_log_file(log_file, date_filter="2026-10-01")
    assert len(oct_1) == 2

    # Filter by search
    etl_logs = analyze_log_file(log_file, search_term="ETL")
    assert len(etl_logs) == 2

    # Nonexistent file
    missing = analyze_log_file(tmp_path / "nonexistent.log")
    assert missing == []


def test_run_log_analyzer_summary_and_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    workdir = tmp_path / "workdir"
    config = read_config(workdir_override=workdir, should_create_override=True)
    log_file = config.log_dir / "sur_en_precios.log.json"

    lines = [
        {
            "timestamp": "2026-10-01 10:00:00",
            "level": "INFO",
            "message": "Msg 1",
            "module": "m",
        },
        {
            "timestamp": "2026-10-01 10:01:00",
            "level": "INFO",
            "message": "Msg 2",
            "module": "m",
        },
        {
            "timestamp": "2026-10-01 10:02:00",
            "level": "ERROR",
            "message": "Msg 3",
            "module": "m",
        },
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")

    # Run with summary
    res_summary = run_log_analyzer(workdir_override=workdir, summary_override=True)
    assert len(res_summary) == 3
    captured = capsys.readouterr()
    assert "Log Summary" in captured.out
    assert "INFO: 2" in captured.out
    assert "ERROR: 1" in captured.out

    # Run with limit
    res_limited = run_log_analyzer(
        workdir_override=workdir, limit_override=1, summary_override=False
    )
    assert len(res_limited) == 3
    captured_limit = capsys.readouterr()
    assert "more records truncated" in captured_limit.out


def test_run_etl_find_latest_raw_date(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    assert find_latest_raw_date(raw_dir) is None

    raw_dir.mkdir(parents=True)
    d1 = raw_dir / "2026-10-01"
    d1.mkdir()
    (d1 / "sucursales.csv").write_text("test")

    d2 = raw_dir / "2026-10-05"
    d2.mkdir()
    (d2 / "sucursales.csv").write_text("test")

    latest = find_latest_raw_date(raw_dir)
    assert latest == date(2026, 10, 5)


def test_run_etl_fails_fast_when_missing_raw_data(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    config_file = workdir / "config.yaml"
    config_file.write_text(
        "app:\n"
        "  region: AR-B\n"
        "scraper:\n"
        "  raw_storage_dir: data/raw\n"
        "etl:\n"
        "  insert_batch_size: 100\n",
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        run_etl_pipeline(workdir_override=workdir, should_create_override=False)

    assert "No harvested SEPA dataset found" in str(
        exc_info.value
    ) or "No SEPA raw dataset found" in str(exc_info.value)
    assert not (workdir / "data" / "raw").exists() or not list(
        (workdir / "data" / "raw").iterdir()
    )


def test_cli_parsers_strictly_restrict_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sur_en_precios.tools.log_analyzer import main as log_main
    from sur_en_precios.tools.run_etl import main as etl_main
    from sur_en_precios.tools.run_harvest import main as harvest_main
    from sur_en_precios.tools.start import main as start_main

    # Test unknown arguments raise SystemExit in argparse
    for tool_main, bad_arg in [
        (etl_main, "--region"),
        (etl_main, "--date"),
        (etl_main, "--create"),
        (harvest_main, "--url"),
        (harvest_main, "--file"),
        (harvest_main, "--create"),
        (log_main, "--limit"),
        (log_main, "--level"),
        (log_main, "--create"),
        (start_main, "--create"),
        (start_main, "--unknown"),
    ]:
        monkeypatch.setattr("sys.argv", ["prog", bad_arg])
        with pytest.raises(SystemExit) as exc_info:
            tool_main()
        # Argparse exits with status 2 on unrecognized arguments
        assert exc_info.value.code == 2


def test_start_tool_initializes_workdir_directories_and_databases(
    tmp_path: Path,
) -> None:
    from sqlalchemy import create_engine, inspect

    from sur_en_precios.tools.start import init_workdir

    workdir = tmp_path / "custom_workdir"
    assert not workdir.exists()

    config = init_workdir(workdir=workdir)

    # 1. Config file created and matches workdir
    assert config.workdir == workdir
    config_file = workdir / "config.yaml"
    assert config_file.exists()

    # 2. Directories created
    assert config.data_dir.exists()
    assert config.raw_dir.exists()
    assert config.temp_dir.exists()
    assert config.log_dir.exists()
    assert config.baskets_dir.exists()
    assert config.sync_staging_dir.exists()

    # 3. Databases created and tables present
    # 3.1 Public DB
    public_db = config.get_public_db_path()
    assert public_db.exists()
    pub_engine = create_engine(f"sqlite:///{public_db}")
    pub_tables = set(inspect(pub_engine).get_table_names())
    pub_engine.dispose()
    assert {
        "categories",
        "brands",
        "tags",
        "articles",
        "points_of_sale",
        "daily_prices",
        "daily_product_metrics",
        "unreviewed_articles",
    }.issubset(pub_tables)

    # 3.2 User Data DB
    user_db = config.get_user_db_path()
    assert user_db.exists()
    user_engine = create_engine(f"sqlite:///{user_db}")
    user_tables = set(inspect(user_engine).get_table_names())
    user_engine.dispose()
    assert {"users", "baskets", "basket_items"}.issubset(user_tables)

    # 3.3 Control DB
    control_db = config.get_control_db_path()
    assert control_db.exists()
    ctrl_engine = create_engine(f"sqlite:///{control_db}")
    ctrl_tables = set(inspect(ctrl_engine).get_table_names())
    ctrl_engine.dispose()
    assert "scraper_logs" in ctrl_tables

    # 3.4 Evolution DB
    evolution_db = config.get_evolution_db_path()
    assert evolution_db.exists()
    evo_engine = create_engine(f"sqlite:///{evolution_db}")
    evo_tables = set(inspect(evo_engine).get_table_names())
    evo_engine.dispose()
    assert {
        "evolution_baskets",
        "evolution_runs",
        "evolution_daily_summaries",
        "evolution_daily_items",
        "alembic_version",
    }.issubset(evo_tables)


def test_start_tool_idempotency(tmp_path: Path) -> None:
    from sur_en_precios.tools.start import init_workdir

    workdir = tmp_path / "idempotent_workdir"
    cfg1 = init_workdir(workdir=workdir)
    assert cfg1.workdir == workdir

    # Second execution must be completely safe and non-destructive
    cfg2 = init_workdir(workdir=workdir)
    assert cfg2.workdir == workdir


def test_start_tool_cli_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from sur_en_precios.tools.start import main as start_main

    workdir = tmp_path / "cli_workdir"
    monkeypatch.setattr("sys.argv", ["prog", "--workdir", str(workdir)])

    start_main()

    captured = capsys.readouterr()
    assert "SUR EN PRECIOS — WORKDIR INITIALIZED" in captured.out
    assert "Workdir initialization completed successfully." in captured.out
    assert (workdir / "config.yaml").exists()
    assert (workdir / "data" / "public.sqlite").exists()
    assert (workdir / "data" / "user_data.sqlite").exists()
    assert (workdir / "data" / "control.sqlite").exists()
    assert (workdir / "data" / "evolution.sqlite").exists()
