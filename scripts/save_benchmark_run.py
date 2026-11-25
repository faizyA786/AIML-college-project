from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import BENCHMARK_CASES  # noqa: E402
from ml_engine.benchmark import compare_models  # noqa: E402
from persistence import get_benchmark_rows, persist_approved_run  # noqa: E402


def validate_curated_rows(rows: list[dict], source: str | None) -> None:
    """CLI-level validation; persistence.py repeats the gate inside its transaction."""
    if not rows:
        raise SystemExit("No benchmark observations found in PostgreSQL.")
    if source != "postgresql":
        raise SystemExit(f"Refusing to save forecast from source {source!r}; PostgreSQL is required.")

    invalid_status = sorted({
        str(row.get("source_status") or "missing").strip().lower()
        for row in rows
        if str(row.get("source_status") or "missing").strip().lower() != "curated"
    })
    if invalid_status:
        raise SystemExit(
            "Refusing to save forecast: every observation must explicitly have source_status='curated'. "
            f"Found: {', '.join(invalid_status)}."
        )

    parsed_periods = []
    for index, row in enumerate(rows, start=1):
        period = row.get("period")
        try:
            month = period.strftime("%Y-%m") if hasattr(period, "strftime") else str(period)[:7]
            year, month_number = (int(piece) for piece in month.split("-", 1))
            if month_number < 1 or month_number > 12:
                raise ValueError
            parsed_periods.append((year, month_number))
        except (TypeError, ValueError):
            raise SystemExit(f"Refusing to save forecast: row {index} has an invalid period.")
        try:
            value = float(row["target_value_usd"])
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f"Refusing to save forecast: row {index} has an invalid target value.")
        if not math.isfinite(value) or value < 0:
            raise SystemExit(f"Refusing to save forecast: row {index} has a negative or non-finite target value.")

    if len(parsed_periods) != len(set(parsed_periods)):
        raise SystemExit("Refusing to save forecast: duplicate monthly periods were found.")
    ordered = sorted(parsed_periods)
    for previous, current in zip(ordered, ordered[1:]):
        expected = (previous[0] + (previous[1] == 12), 1 if previous[1] == 12 else previous[1] + 1)
        if current != expected:
            raise SystemExit("Refusing to save forecast: the PostgreSQL series contains missing months.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    case_key = os.getenv("BENCHMARK_CASE", "us_china").strip()
    if case_key not in BENCHMARK_CASES:
        raise SystemExit(f"Unknown BENCHMARK_CASE {case_key!r}. Available: {', '.join(BENCHMARK_CASES)}")

    config = BENCHMARK_CASES[case_key]
    rows, source = get_benchmark_rows(config["series_key"])
    validate_curated_rows(rows or [], source)

    result = compare_models(
        rows or [],
        target_name=config["target_name"],
        target_series=config["target_series"],
    )
    versions = sorted({str(row.get("source_version") or "unknown") for row in rows or []})
    run_id = persist_approved_run(
        result,
        data_version=" | ".join(versions),
        benchmark_key=config["series_key"],
    )
    print(f"Saved approved benchmark run {run_id} to PostgreSQL for {config['series_key']}.")


if __name__ == "__main__":
    main()
