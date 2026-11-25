from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from persistence import normalize_database_url  # noqa: E402


STATUSES = ("unverified", "curated")
DIRECTIONS = {"restrictive", "relaxing", "neutral", "ambiguous"}


def parse_date(value: str, field_name: str, required: bool = False) -> date | None:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _records(path: str) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Import dated semiconductor policy events and optional monthly coverage declarations."
    )
    parser.add_argument("csv_path", help="Policy event CSV with title, published_at, direction, severity, source_url")
    parser.add_argument("--coverage-csv", default=None, help="Monthly coverage CSV with period, coverage_status, source_url")
    parser.add_argument("--series-key", default="us_exports_cn_854231")
    parser.add_argument("--event-status", choices=STATUSES, default="unverified")
    parser.add_argument("--coverage-status-source", choices=STATUSES, default="unverified")
    parser.add_argument("--curation-note", default="", help="Required if either imported source is marked curated")
    args = parser.parse_args()

    if (args.event_status == "curated" or args.coverage_status_source == "curated") and not args.curation_note.strip():
        parser.error("--curation-note is required when importing curated events or coverage.")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set DATABASE_URL in the project .env file first.")

    event_headers, event_rows = _records(args.csv_path)
    required = {"title", "published_at", "direction", "severity", "source_url"}
    if not required.issubset(event_headers):
        raise SystemExit("Policy event CSV needs title, published_at, direction, severity, and source_url columns.")
    events = []
    seen_event_keys: set[tuple[str, date, str]] = set()
    for line_number, row in enumerate(event_rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        try:
            title = str(row.get("title", "")).strip()
            published_at = parse_date(row.get("published_at", ""), "published_at", required=True)
            effective_at = parse_date(row.get("effective_at", ""), "effective_at")
            direction = str(row.get("direction", "ambiguous")).strip().lower()
            severity = int(row.get("severity", ""))
            source_url = str(row.get("source_url", "")).strip()
            if not title:
                raise ValueError("title is required")
            if direction not in DIRECTIONS:
                raise ValueError(f"direction must be one of {', '.join(sorted(DIRECTIONS))}")
            if severity < 1 or severity > 5:
                raise ValueError("severity must be an integer from 1 to 5")
            if not source_url.startswith("https://"):
                raise ValueError("source_url must use HTTPS")
            event_key = (title, published_at, source_url)
            if event_key in seen_event_keys:
                raise ValueError("duplicate title/published_at/source_url record")
            seen_event_keys.add(event_key)
            if direction == "restrictive":
                signal_value = float(severity)
            elif direction == "relaxing":
                signal_value = -float(severity)
            elif direction == "neutral":
                signal_value = 0.0
            else:
                signal_value = None
            events.append({
                "title": title,
                "published_at": published_at,
                "effective_at": effective_at,
                "destination_code": str(row.get("destination_code", "")).strip() or None,
                "direction": direction,
                "severity": severity,
                "signal_value": signal_value,
                "source_url": source_url,
                "source_status": args.event_status,
                "notes": str(row.get("notes", "")).strip() or None,
            })
        except (TypeError, ValueError) as error:
            raise SystemExit(f"Invalid policy event at CSV line {line_number}: {error}") from error

    coverage = []
    if args.coverage_csv:
        coverage_headers, coverage_rows = _records(args.coverage_csv)
        required_coverage = {"period", "coverage_status", "source_url"}
        if not required_coverage.issubset(coverage_headers):
            raise SystemExit("Policy coverage CSV needs period, coverage_status, and source_url columns.")
        seen_periods: set[date] = set()
        for line_number, row in enumerate(coverage_rows, start=2):
            try:
                raw_month = str(row.get("period", "")).strip()
                if len(raw_month) == 7:
                    year_text, month_text = raw_month.split("-", 1)
                    month = date(int(year_text), int(month_text), 1)
                else:
                    parsed_month = parse_date(raw_month, "period", required=True)
                    month = date(parsed_month.year, parsed_month.month, 1)
                coverage_status = str(row.get("coverage_status", "")).strip().lower()
                source_url = str(row.get("source_url", "")).strip()
                if coverage_status not in {"complete", "incomplete"}:
                    raise ValueError("coverage_status must be complete or incomplete")
                if not source_url.startswith("https://"):
                    raise ValueError("source_url must use HTTPS")
                if month in seen_periods:
                    raise ValueError(f"duplicate monthly coverage declaration for {month:%Y-%m}")
                seen_periods.add(month)
                coverage.append({
                    "series_key": args.series_key,
                    "period": month,
                    "coverage_status": coverage_status,
                    "source_url": source_url,
                    "source_version": str(row.get("source_version", "")).strip() or "policy-coverage-csv",
                    "source_status": args.coverage_status_source,
                    "notes": str(row.get("notes", "")).strip() or None,
                })
            except (TypeError, ValueError) as error:
                raise SystemExit(f"Invalid policy coverage at CSV line {line_number}: {error}") from error

    if not events and not coverage:
        raise SystemExit("No policy event or coverage rows were found.")

    event_statement = text("""
        INSERT INTO policy_events
            (title, published_at, effective_at, destination_code, direction, severity,
             signal_value, source_url, source_status, notes)
        VALUES (:title, :published_at, :effective_at, :destination_code, :direction, :severity,
                :signal_value, :source_url, :source_status, :notes)
        ON CONFLICT (title, published_at, source_url) DO UPDATE SET
            effective_at = EXCLUDED.effective_at,
            destination_code = EXCLUDED.destination_code,
            direction = EXCLUDED.direction,
            severity = EXCLUDED.severity,
            signal_value = EXCLUDED.signal_value,
            source_status = EXCLUDED.source_status,
            notes = EXCLUDED.notes
    """)
    coverage_statement = text("""
        INSERT INTO policy_event_coverage
            (series_key, period, coverage_status, source_url, source_version, source_status, notes)
        VALUES (:series_key, :period, :coverage_status, :source_url, :source_version, :source_status, :notes)
        ON CONFLICT (series_key, period) DO UPDATE SET
            coverage_status = EXCLUDED.coverage_status,
            source_url = EXCLUDED.source_url,
            source_version = EXCLUDED.source_version,
            source_status = EXCLUDED.source_status,
            notes = EXCLUDED.notes
    """)

    engine = create_engine(normalize_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            if events:
                connection.execute(event_statement, events)
            if coverage:
                connection.execute(coverage_statement, coverage)
    finally:
        engine.dispose()

    print(f"Imported {len(events)} policy event(s) as {args.event_status}.")
    print(f"Imported {len(coverage)} monthly coverage declaration(s) as {args.coverage_status_source}.")
    if not coverage:
        print("No monthly coverage file was supplied. Missing event months will remain unknown, not zero.")
    if args.curation_note:
        print(f"Maintainer curation note: {args.curation_note.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
