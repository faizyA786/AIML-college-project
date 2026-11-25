from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_engine.benchmark import prepare_dataset  # noqa: E402
from persistence import normalize_database_url  # noqa: E402


ALLOWED_STATUSES = ("unverified", "curated")


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Import monthly U.S.-China benchmark observations into PostgreSQL."
    )
    parser.add_argument("csv_path", help="CSV with period and target_value_usd columns")
    parser.add_argument(
        "--series-key",
        default=os.getenv("BENCHMARK_SERIES_KEY", "us_exports_cn_854231"),
        help="Benchmark key; default is the U.S.-China Schedule B 8542.31 series",
    )
    parser.add_argument("--source-version", default="census-csv-import")
    parser.add_argument(
        "--status",
        choices=ALLOWED_STATUSES,
        default="unverified",
        help="Status to assign. Defaults to unverified; curated requires a curation note.",
    )
    parser.add_argument(
        "--curation-note",
        default="",
        help="Required when --status curated; document the checks completed by the maintainer.",
    )
    args = parser.parse_args()

    if args.status == "curated" and not args.curation_note.strip():
        parser.error("--curation-note is required when --status curated.")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set DATABASE_URL in the project .env file first.")

    frame = pd.read_csv(args.csv_path)
    if "target_value_usd" not in frame.columns and "export_value_usd" in frame.columns:
        frame = frame.rename(columns={"export_value_usd": "target_value_usd"})
    if not {"period", "target_value_usd"}.issubset(frame.columns):
        raise SystemExit("CSV needs period and target_value_usd columns; see data/benchmark_template.csv.")

    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame["target_value_usd"] = pd.to_numeric(frame["target_value_usd"], errors="coerce")
    if frame["period"].isna().any() or frame["target_value_usd"].isna().any():
        raise SystemExit("CSV has invalid period or target_value_usd values; no rows were imported.")
    if not np.isfinite(frame["target_value_usd"].to_numpy(dtype=float)).all():
        raise SystemExit("CSV target values must be finite numbers; no rows were imported.")
    if (frame["target_value_usd"] < 0).any():
        raise SystemExit("CSV target values must be non-negative; no rows were imported.")
    if frame["period"].duplicated().any():
        raise SystemExit("CSV contains duplicate monthly periods; no rows were imported.")
    frame = frame.sort_values("period").reset_index(drop=True)
    expected = pd.date_range(frame["period"].iloc[0], frame["period"].iloc[-1], freq="MS")
    if len(frame) != len(expected) or not frame["period"].reset_index(drop=True).equals(pd.Series(expected)):
        raise SystemExit("CSV must contain one consecutive row per month; missing months were found.")
    if len(frame) < 73:
        raise SystemExit(f"CSV has {len(frame)} months; at least 73 consecutive months are required for this benchmark.")

    for optional in (
        "policy_signal", "sector_ip_index", "economic_index",
        "target_published_at", "policy_published_at", "source_version",
    ):
        if optional not in frame:
            frame[optional] = None
    # If a merged dataset has external inputs, do not let a target-only curation
    # flag silently elevate unverified feature sources to curated status.
    if args.status == "curated":
        for status_column, value_columns in (
            ("feature_source_status", ("sector_ip_index", "economic_index")),
            ("policy_source_status", ("policy_signal",)),
        ):
            present_columns = [column for column in value_columns if column in frame.columns]
            populated_mask = pd.Series(False, index=frame.index)
            for column in present_columns:
                populated_mask |= pd.to_numeric(frame[column], errors="coerce").notna()
            if not populated_mask.any():
                continue
            if status_column not in frame.columns:
                raise SystemExit(
                    f"Cannot import as curated: {status_column} is missing while related external features are populated. "
                    "Re-merge with source-status metadata and curate the underlying source first."
                )
            source_values = frame.loc[populated_mask, status_column].fillna("unverified").astype(str).str.strip().str.lower()
            if not source_values.eq("curated").all():
                raise SystemExit(
                    f"Cannot import as curated: populated values in {status_column} include unverified sources. "
                    "Verify those external data rows and set their status to curated only after review."
                )

    # Model-side validation also checks numeric feature coercion and target continuity.
    prepare_dataset(frame)

    for date_column in ("target_published_at", "policy_published_at"):
        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.date
    for optional_numeric in ("policy_signal", "sector_ip_index", "economic_index"):
        frame[optional_numeric] = pd.to_numeric(frame[optional_numeric], errors="coerce")
        frame[optional_numeric] = frame[optional_numeric].where(np.isfinite(frame[optional_numeric]), None)

    records = []
    for row in frame.to_dict(orient="records"):
        records.append({
            "series_key": args.series_key,
            "period": row["period"].date(),
            "target_value_usd": float(row["target_value_usd"]),
            "policy_signal": None if pd.isna(row["policy_signal"]) else float(row["policy_signal"]),
            "sector_ip_index": None if pd.isna(row["sector_ip_index"]) else float(row["sector_ip_index"]),
            "economic_index": None if pd.isna(row["economic_index"]) else float(row["economic_index"]),
            "target_published_at": row["target_published_at"],
            "policy_published_at": row["policy_published_at"],
            "source_version": args.source_version if pd.isna(row["source_version"]) or not str(row["source_version"]).strip() else str(row["source_version"]),
            "source_status": args.status,
        })

    statement = text("""
        INSERT INTO benchmark_monthly_observations
            (series_key, period, target_value_usd, policy_signal, sector_ip_index,
             economic_index, target_published_at, policy_published_at, source_version, source_status)
        VALUES (:series_key, :period, :target_value_usd, :policy_signal, :sector_ip_index,
                :economic_index, :target_published_at, :policy_published_at, :source_version, :source_status)
        ON CONFLICT (series_key, period) DO UPDATE SET
            target_value_usd = EXCLUDED.target_value_usd,
            policy_signal = EXCLUDED.policy_signal,
            sector_ip_index = EXCLUDED.sector_ip_index,
            economic_index = EXCLUDED.economic_index,
            target_published_at = EXCLUDED.target_published_at,
            policy_published_at = EXCLUDED.policy_published_at,
            source_version = EXCLUDED.source_version,
            source_status = EXCLUDED.source_status
    """)

    engine = create_engine(normalize_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            connection.execute(statement, records)
            updated = connection.execute(text("""
                UPDATE predictions p
                SET observed_value_usd = target.target_value_usd,
                    observed_change_pct = 100.0 * ((1.0 + target.target_value_usd) / (1.0 + origin.target_value_usd) - 1.0),
                    evaluated_at = now(),
                    evaluation_status = 'observed'
                FROM forecast_runs r,
                     benchmark_monthly_observations target,
                     benchmark_monthly_observations origin
                WHERE p.run_id = r.id
                  AND r.benchmark_key = :series_key
                  AND p.evaluation_status = 'awaiting_outcome'
                  AND target.series_key = r.benchmark_key
                  AND target.period = p.target_period
                  AND target.source_status = 'curated'
                  AND origin.series_key = r.benchmark_key
                  AND origin.period = p.forecast_origin
                  AND origin.source_status = 'curated'
            """), {"series_key": args.series_key}).rowcount
    finally:
        engine.dispose()

    print(f"Imported {len(records)} monthly observations as {args.status!r} under {args.series_key}.")
    if args.status == "curated":
        print(f"Maintainer curation note: {args.curation_note.strip()}")
    else:
        print("These observations are not eligible for approved forecast saving until reviewed and re-imported as curated.")
    print(f"Updated {updated} saved forecast(s) only where both origin and outcome months are curated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
