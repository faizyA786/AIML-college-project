from __future__ import annotations

import csv
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


ROOT = Path(__file__).resolve().parent
ALLOWED_SOURCE_STATUSES = {"curated", "unverified"}
DEFAULT_BENCHMARK_SERIES_KEY = "us_exports_cn_854231"


def normalize_database_url(url: str) -> str:
    """Normalize common hosted-Postgres URLs for the psycopg SQLAlchemy driver."""
    value = url.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


@lru_cache(maxsize=1)
def get_engine() -> Engine | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    return create_engine(
        normalize_database_url(url),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=1,
        pool_recycle=300,
        connect_args={"connect_timeout": 5},
    )


def load_csv_papers(domain: str | None = None) -> list[dict[str, Any]]:
    papers_path = ROOT / "data" / "papers.csv"
    if not papers_path.exists():
        return []
    with papers_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if domain:
        rows = [row for row in rows if row.get("domain", "").casefold() == domain.casefold()]
    return rows


def get_papers(domain: str | None = None) -> tuple[list[dict[str, Any]], str]:
    engine = get_engine()
    if engine is not None:
        try:
            query = text(
                "SELECT domain, year, title, authors, venue, method, relevance, url "
                "FROM research_papers"
                + (" WHERE lower(domain) = lower(:domain)" if domain else "")
                + " ORDER BY year DESC, title"
            )
            parameters = {"domain": domain} if domain else {}
            with engine.connect() as connection:
                results = connection.execute(query, parameters).mappings().all()
            if results:
                return [dict(row) for row in results], "postgresql"
        except Exception:
            # During first-time setup the bundled CSV is a read-only fallback.
            pass
    return load_csv_papers(domain), "curated_csv_fallback"


def get_benchmark_rows(
    series_key: str | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    engine = get_engine()
    if engine is None:
        return None, None
    selected_key = series_key or os.getenv("BENCHMARK_SERIES_KEY", DEFAULT_BENCHMARK_SERIES_KEY)
    query = text("""
        SELECT period, target_value_usd, policy_signal, sector_ip_index,
               economic_index, target_published_at, policy_published_at,
               source_version, source_status
        FROM benchmark_monthly_observations
        WHERE series_key = :series_key
        ORDER BY period
    """)
    try:
        with engine.connect() as connection:
            rows = connection.execute(query, {"series_key": selected_key}).mappings().all()
        if rows:
            return [dict(row) for row in rows], "postgresql"
        return None, "postgresql_empty"
    except Exception as exc:
        return None, f"postgresql_unavailable:{type(exc).__name__}"


def get_run_history(limit: int = 20) -> list[dict[str, Any]]:
    engine = get_engine()
    if engine is None:
        return []
    query = text("""
        WITH latest_runs AS (
            SELECT id FROM forecast_runs ORDER BY created_at DESC LIMIT :limit
        )
        SELECT r.id, r.benchmark_key, r.created_at, r.model_version, r.model_config,
               r.horizon_months, r.target_period, r.data_version, r.metrics,
               p.model_id, p.forecast_origin, p.target_period AS prediction_target_period,
               p.predicted_change_pct, p.observed_change_pct, p.evaluation_status
        FROM latest_runs l
        JOIN forecast_runs r ON r.id = l.id
        LEFT JOIN predictions p ON p.run_id = r.id
        ORDER BY r.created_at DESC, p.model_id
    """)
    with engine.connect() as connection:
        rows = connection.execute(query, {"limit": max(1, min(int(limit), 50))}).mappings().all()
    runs: dict[int, dict[str, Any]] = {}
    for row in rows:
        run_id = int(row["id"])
        if run_id not in runs:
            runs[run_id] = {
                "id": run_id,
                "benchmark_key": row["benchmark_key"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "model_version": row["model_version"],
                "model_config": row["model_config"],
                "horizon_months": row["horizon_months"],
                "target_period": row["target_period"].isoformat() if row["target_period"] else None,
                "data_version": row["data_version"],
                "metrics": row["metrics"],
                "predictions": [],
            }
        if row["model_id"] is not None:
            runs[run_id]["predictions"].append({
                "model_id": row["model_id"],
                "forecast_origin": row["forecast_origin"].isoformat() if row["forecast_origin"] else None,
                "target_period": row["prediction_target_period"].isoformat() if row["prediction_target_period"] else None,
                "predicted_change_pct": row["predicted_change_pct"],
                "observed_change_pct": row["observed_change_pct"],
                "evaluation_status": row["evaluation_status"],
            })
    return list(runs.values())


def _approved_observation_rows(connection: Connection, benchmark_key: str) -> list[dict[str, Any]]:
    rows = connection.execute(text("""
        SELECT period, target_value_usd, source_version, source_status
        FROM benchmark_monthly_observations
        WHERE series_key = :series_key
        ORDER BY period
    """), {"series_key": benchmark_key}).mappings().all()
    observations = [dict(row) for row in rows]
    if not observations:
        raise RuntimeError("Cannot save forecast: no PostgreSQL observations exist for this benchmark.")

    invalid_statuses = sorted({
        str(row.get("source_status") or "missing").strip().lower()
        for row in observations
        if str(row.get("source_status") or "missing").strip().lower() != "curated"
    })
    if invalid_statuses:
        raise RuntimeError(
            "Cannot save forecast: every database observation must have source_status='curated'. "
            f"Found: {', '.join(invalid_statuses)}."
        )

    seen_periods: set[str] = set()
    month_ordinals: list[int] = []
    for index, row in enumerate(observations, start=1):
        period = row.get("period")
        try:
            if hasattr(period, "year") and hasattr(period, "month"):
                year, month = int(period.year), int(period.month)
            else:
                period_text = str(period)
                year, month = (int(part) for part in period_text[:7].split("-", 1))
            if month < 1 or month > 12:
                raise ValueError
        except (TypeError, ValueError):
            raise RuntimeError(f"Cannot save forecast: invalid monthly period on observation {index}.") from None
        period_key = f"{year:04d}-{month:02d}"
        if period_key in seen_periods:
            raise RuntimeError(f"Cannot save forecast: duplicate monthly observation at {period_key}.")
        seen_periods.add(period_key)
        month_ordinals.append(year * 12 + month)
        try:
            value = float(row["target_value_usd"])
        except (TypeError, ValueError, KeyError) as exc:
            raise RuntimeError(f"Cannot save forecast: invalid target value on observation {index}.") from exc
        if not math.isfinite(value) or value < 0:
            raise RuntimeError(f"Cannot save forecast: target value on observation {index} must be finite and non-negative.")

    if len(observations) < 73:
        raise RuntimeError("Cannot save forecast: at least 73 consecutive monthly observations are required.")
    ordered_months = sorted(month_ordinals)
    if any(current - previous != 1 for previous, current in zip(ordered_months, ordered_months[1:])):
        raise RuntimeError("Cannot save forecast: the PostgreSQL benchmark series contains missing months.")
    return observations


def persist_approved_run(
    result: dict[str, Any],
    data_version: str,
    benchmark_key: str | None = None,
) -> int:
    """Persist a forecast only after rechecking curated source rows in PostgreSQL.

    This gate intentionally lives in the persistence layer as well as the CLI so
    callers cannot bypass it by invoking this function directly.
    """
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is required to save a benchmark run.")

    selected_key = benchmark_key or os.getenv("BENCHMARK_SERIES_KEY", DEFAULT_BENCHMARK_SERIES_KEY)
    required_result_fields = {"horizon_months", "forecast_target_period", "last_observed_period", "forecasts", "caveats"}
    missing = required_result_fields - set(result)
    if missing:
        raise ValueError(f"Cannot save incomplete benchmark result; missing: {', '.join(sorted(missing))}.")
    if not result.get("forecasts"):
        raise ValueError("Cannot save a benchmark run without forecasts.")
    try:
        horizon = int(result["horizon_months"])
        origin_year, origin_month = (int(part) for part in result["last_observed_period"].split("-", 1))
        target_year, target_month = (int(part) for part in result["forecast_target_period"].split("-", 1))
        if not 1 <= origin_month <= 12 or not 1 <= target_month <= 12 or horizon < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Cannot save forecast: invalid horizon or forecast period metadata.") from None
    expected_target_ordinal = origin_year * 12 + origin_month + horizon
    actual_target_ordinal = target_year * 12 + target_month
    if actual_target_ordinal != expected_target_ordinal:
        raise ValueError("Cannot save forecast: target period does not match the origin period and forecast horizon.")
    for index, forecast in enumerate(result["forecasts"], start=1):
        try:
            predicted = float(forecast["predicted_change_pct"])
            implied_value = float(forecast["implied_value_usd"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Cannot save forecast: model forecast {index} contains invalid numeric values.") from None
        if not math.isfinite(predicted) or not math.isfinite(implied_value) or implied_value < 0:
            raise ValueError(f"Cannot save forecast: model forecast {index} contains non-finite or negative values.")

    insert_run = text("""
        INSERT INTO forecast_runs
            (benchmark_key, model_version, model_config, horizon_months, data_version,
             target_period, metrics, forecasts, caveats)
        VALUES (:benchmark_key, :model_version, CAST(:model_config AS jsonb), :horizon_months,
                :data_version, :target_period, CAST(:metrics AS jsonb),
                CAST(:forecasts AS jsonb), CAST(:caveats AS jsonb))
        RETURNING id
    """)

    with engine.begin() as connection:
        observations = _approved_observation_rows(connection, selected_key)
        observed_periods = {
            row["period"].strftime("%Y-%m") if hasattr(row["period"], "strftime") else str(row["period"])[:7]
            for row in observations
        }
        if result["last_observed_period"] not in observed_periods:
            raise RuntimeError(
                "Cannot save forecast: result's last observed month does not match the curated database series."
            )

        run_id = connection.execute(insert_run, {
            "benchmark_key": selected_key,
            "model_version": result.get("model_version", "benchmark-v1"),
            "model_config": json.dumps(result.get("model_configuration", {}), allow_nan=False),
            "horizon_months": int(result["horizon_months"]),
            "data_version": data_version,
            "target_period": result["forecast_target_period"] + "-01",
            "metrics": json.dumps({
                "model_scores": result.get("models", []),
                "unsupervised_regimes": result.get("regimes", {}),
            }, allow_nan=False),
            "forecasts": json.dumps(result["forecasts"], allow_nan=False),
            "caveats": json.dumps(result["caveats"], allow_nan=False),
        }).scalar_one()

        for row in result["forecasts"]:
            connection.execute(text("""
                INSERT INTO predictions
                    (run_id, model_id, forecast_origin, target_period,
                     predicted_change_pct, implied_value_usd)
                VALUES (:run_id, :model_id, :forecast_origin, :target_period,
                        :predicted_change_pct, :implied_value_usd)
            """), {
                "run_id": run_id,
                "model_id": row["id"],
                "forecast_origin": result["last_observed_period"] + "-01",
                "target_period": result["forecast_target_period"] + "-01",
                "predicted_change_pct": float(row["predicted_change_pct"]),
                "implied_value_usd": float(row["implied_value_usd"]),
            })

    return int(run_id)
