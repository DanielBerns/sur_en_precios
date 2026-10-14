import json
from datetime import date
from pathlib import Path

import pytest

from sur_en_precios.config import read_config
from sur_en_precios.tools.log_analyzer import analyze_log_file, run_log_analyzer
from sur_en_precios.tools.run_etl import (
    create_sample_sepa_data,
    find_latest_raw_date,
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


def test_run_etl_create_sample_sepa_data(tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample"
    create_sample_sepa_data(sample_dir)

    sucursales = sample_dir / "sucursales.csv"
    productos = sample_dir / "productos.csv"

    assert sucursales.exists()
    assert productos.exists()
    assert "Carrefour Central" in sucursales.read_text(encoding="utf-8")
    assert "Leche Entera 1L" in productos.read_text(encoding="utf-8")


def test_cli_parsers_strictly_restrict_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sur_en_precios.tools.log_analyzer import main as log_main
    from sur_en_precios.tools.run_etl import main as etl_main
    from sur_en_precios.tools.run_harvest import main as harvest_main

    # Test unknown arguments raise SystemExit in argparse
    for tool_main, bad_arg in [
        (etl_main, "--region"),
        (etl_main, "--date"),
        (harvest_main, "--url"),
        (harvest_main, "--file"),
        (log_main, "--limit"),
        (log_main, "--level"),
    ]:
        monkeypatch.setattr("sys.argv", ["prog", bad_arg, "val"])
        with pytest.raises(SystemExit) as exc_info:
            tool_main()
        # Argparse exits with status 2 on unrecognized arguments
        assert exc_info.value.code == 2
