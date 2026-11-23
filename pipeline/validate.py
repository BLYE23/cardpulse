"""Run CardPulse SQL data-quality checks and persist their results.

From the repository root:
    python pipeline/validate.py [--run-id ID] [--db PATH]
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import sys

import config


MARKER = re.compile(r"^-- check: (\w+) \| (error|warn)$", re.MULTILINE)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_checks(path):
    source = path.read_text(encoding="utf-8")
    markers = list(MARKER.finditer(source))
    if not markers:
        raise ValueError(f"No checks found in {path}")
    for index, match in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(source)
        query = source[match.end():end].strip().removesuffix(";").strip()
        if not query:
            raise ValueError(f"Empty check: {match.group(1)}")
        yield match.group(1), match.group(2), query


def run_checks(db_path, run_id):
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}. Run `python pipeline/load_db.py` first.")
    error_failures = False
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        with conn:
            for name, severity, query in parse_checks(config.SQL_DIR / "checks.sql"):
                failing = conn.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
                passed = int(failing == 0)
                conn.execute("""
                    INSERT INTO data_quality_results
                        (run_id, check_name, severity, failing_rows, passed, checked_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (run_id, check_name) DO UPDATE SET
                        severity = excluded.severity,
                        failing_rows = excluded.failing_rows,
                        passed = excluded.passed,
                        checked_at = excluded.checked_at
                """, (run_id, name, severity, failing, passed, utc_now()))
                print(f"{'PASS' if passed else 'FAIL'} {name} ({severity}): {failing} failing rows")
                if severity == "error" and failing:
                    error_failures = True
    return 2 if error_failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="Override CARDPULSE_RUN_ID")
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="SQLite database path")
    args = parser.parse_args()
    run_id = (args.run_id or os.environ.get("CARDPULSE_RUN_ID") or
              "manual-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    try:
        return run_checks(args.db, run_id)
    except Exception as exc:
        print(f"validate.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
