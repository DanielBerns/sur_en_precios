import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from sur_en_precios.config import resolve_working_directory


def analyze_log_file(
    log_path: Path, level_filter: str | None = None, search_term: str | None = None
) -> List[Dict[str, Any]]:
    """Reads structured JSON log file and filters entries by log level or search query."""
    if not log_path.exists():
        print(f"Log file not found at: {log_path}")
        return []

    matching_logs: List[Dict[str, Any]] = []

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if level_filter:
                rec_level = record.get("level", "").upper()
                if rec_level != level_filter.upper():
                    continue

            if search_term:
                line_lower = line.lower()
                if search_term.lower() not in line_lower:
                    continue

            matching_logs.append(record)

    return matching_logs


def main() -> None:
    """CLI entry point for structured log analyzer."""
    parser = argparse.ArgumentParser(
        description="Structured JSON Log Analyzer for Sur en Precios"
    )
    parser.add_argument(
        "--level", help="Filter by log level (DEBUG, INFO, WARNING, ERROR)"
    )
    parser.add_argument("--search", help="Search substring within log messages")
    parser.add_argument(
        "--summary", action="store_true", help="Print summary of log counts by level"
    )
    parser.add_argument("--workdir", help="Path to working directory")

    args = parser.parse_args()

    workdir_path, _ = resolve_working_directory()
    log_path = workdir_path / "logs" / "sur_en_precios.log.json"

    records = analyze_log_file(
        log_path, level_filter=args.level, search_term=args.search
    )

    if args.summary:
        counts: Dict[str, int] = {}
        for r in records:
            lvl = r.get("level", "UNKNOWN").upper()
            counts[lvl] = counts.get(lvl, 0) + 1
        print(f"Log Summary ({log_path}):")
        for lvl, cnt in counts.items():
            print(f"  {lvl}: {cnt}")
        return

    print(f"Found {len(records)} matching log records in {log_path}:")
    for r in records[:50]:  # Limit output display
        ts = r.get("timestamp", "")
        lvl = r.get("level", "")
        msg = r.get("message", "")
        module = r.get("module", "")
        print(f"[{ts}] [{lvl}] [{module}] {msg}")


if __name__ == "__main__":
    main()
