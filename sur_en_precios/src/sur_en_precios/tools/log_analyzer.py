import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from sur_en_precios.config import read_config


def analyze_log_file(
    log_path: Path,
    level_filter: str | None = None,
    search_term: str | None = None,
    date_filter: str | None = None,
) -> List[Dict[str, Any]]:
    """Reads structured JSON log file and filters entries by log level, date, or search query."""
    if not log_path.exists():
        print(f"Log file not found at: {log_path}")
        return []

    matching_logs: List[Dict[str, Any]] = []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                if level_filter:
                    rec_level = record.get("level", "").upper()
                    if rec_level != level_filter.upper():
                        continue

                if date_filter:
                    rec_ts = str(record.get("timestamp", ""))
                    if date_filter not in rec_ts:
                        continue

                if search_term:
                    if search_term.lower() not in line_str.lower():
                        continue

                matching_logs.append(record)
    except Exception as exc:
        print(f"Error reading log file {log_path}: {exc}", file=sys.stderr)
        return []

    return matching_logs


def run_log_analyzer(
    workdir_override: Path | None = None,
    should_create_override: bool | None = None,
    level_filter_override: str | None = None,
    search_term_override: str | None = None,
    date_filter_override: str | None = None,
    limit_override: int | None = None,
    summary_override: bool | None = None,
) -> List[Dict[str, Any]]:
    """Runs the log analyzer using configuration settings or explicit overrides."""
    workdir_path = (
        workdir_override or (Path.home() / "Info" / "sur_en_precios").resolve()
    )
    should_create = (
        should_create_override if should_create_override is not None else False
    )
    config = read_config(
        workdir_override=workdir_path, should_create_override=should_create
    )
    log_settings = config.get_log_analyzer_settings()

    level_filter = (
        level_filter_override
        if level_filter_override is not None
        else log_settings.level
    )
    search_term = (
        search_term_override
        if search_term_override is not None
        else log_settings.search
    )
    date_filter = (
        date_filter_override if date_filter_override is not None else log_settings.date
    )
    limit = limit_override if limit_override is not None else log_settings.limit
    is_summary = (
        summary_override if summary_override is not None else log_settings.summary
    )

    log_path = config.log_dir / "sur_en_precios.log.json"

    records = analyze_log_file(
        log_path=log_path,
        level_filter=level_filter,
        search_term=search_term,
        date_filter=date_filter,
    )

    if is_summary:
        counts: Dict[str, int] = {}
        for r in records:
            lvl = r.get("level", "UNKNOWN").upper()
            counts[lvl] = counts.get(lvl, 0) + 1
        print(f"\nLog Summary ({log_path}):")
        for lvl, cnt in counts.items():
            print(f"  {lvl}: {cnt}")
        print()
        return records

    filter_info = []
    if level_filter:
        filter_info.append(f"level={level_filter}")
    if date_filter:
        filter_info.append(f"date={date_filter}")
    if search_term:
        filter_info.append(f"search='{search_term}'")
    filter_str = f" (filters: {', '.join(filter_info)})" if filter_info else ""

    print(f"\nFound {len(records)} matching log records in {log_path}{filter_str}:")
    for r in records[:limit]:
        ts = r.get("timestamp", "")
        lvl = r.get("level", "")
        msg = r.get("message", "")
        module = r.get("module", "")
        print(f"[{ts}] [{lvl}] [{module}] {msg}")
    if len(records) > limit:
        print(
            f"... ({len(records) - limit} more records truncated, limit is {limit})\n"
        )
    else:
        print()

    return records


def main() -> None:
    """CLI entry point for structured log analyzer."""
    parser = argparse.ArgumentParser(
        description="Structured JSON Log Analyzer for Sur en Precios (filters configured in config.yaml)"
    )
    parser.add_argument("--workdir", help="Path to working directory")
    parser.add_argument(
        "--create", action="store_true", help="Create default config if missing"
    )

    args = parser.parse_args()

    workdir_path = Path(args.workdir).resolve() if args.workdir else None

    try:
        run_log_analyzer(
            workdir_override=workdir_path,
            should_create_override=args.create,
        )
    except Exception as exc:
        print(f"\n[ERROR] Log analyzer failed: {exc}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
