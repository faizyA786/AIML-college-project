from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_months(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if "period" not in frame.columns:
        raise SystemExit(f"{label} CSV needs a period column.")
    frame = frame.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    if frame["period"].isna().any():
        raise SystemExit(f"{label} CSV contains invalid period values.")
    if frame["period"].duplicated().any():
        raise SystemExit(f"{label} CSV must contain no more than one row per month.")
    return frame


def _source_status(frame: pd.DataFrame) -> pd.Series:
    if "source_status" not in frame.columns:
        return pd.Series("unverified", index=frame.index, dtype="object")
    return frame["source_status"].fillna("unverified").astype(str).str.strip().str.lower().where(
        lambda values: values.isin(["curated", "unverified"]), "unverified"
    )


def _policy_signal(events_path: str, coverage_path: str, periods: pd.Series) -> pd.DataFrame:
    events = pd.read_csv(events_path)
    required_event_fields = {"title", "published_at", "source_url", "direction", "severity"}
    if not required_event_fields.issubset(events.columns):
        raise SystemExit(
            "Policy event CSV needs published_at, source_url, direction, and severity columns."
        )
    events["published_at"] = pd.to_datetime(events["published_at"], errors="coerce")
    events["severity"] = pd.to_numeric(events["severity"], errors="coerce")
    events["direction"] = events["direction"].fillna("ambiguous").astype(str).str.strip().str.lower()
    events["source_status"] = _source_status(events)
    if events["published_at"].isna().any():
        raise SystemExit("Policy event CSV contains an invalid published_at date.")
    events["title"] = events["title"].fillna("").astype(str).str.strip()
    if events["title"].eq("").any():
        raise SystemExit("Policy event CSV contains a blank title.")
    if events.duplicated(subset=["title", "published_at", "source_url"]).any():
        raise SystemExit("Policy event CSV contains duplicate title/date/source records.")
    if (
        events["severity"].isna().any()
        or (~events["severity"].between(1, 5)).any()
        or (events["severity"] % 1 != 0).any()
    ):
        raise SystemExit("Policy event severity must be an integer from 1 to 5.")
    valid_directions = {"restrictive", "relaxing", "neutral", "ambiguous"}
    invalid_directions = sorted(set(events["direction"]) - valid_directions)
    if invalid_directions:
        raise SystemExit(f"Unsupported policy direction value(s): {', '.join(invalid_directions)}.")
    if not events["source_url"].astype(str).str.startswith("https://").all():
        raise SystemExit("Every policy event source_url must use HTTPS.")

    # A supplied list of events is not evidence that a quiet month was fully
    # reviewed. Monthly completeness must be declared separately. An unverified
    # event or an event with unresolved direction also blocks zero-filling for that month.
    events["period"] = events["published_at"].dt.to_period("M").dt.to_timestamp()
    monthly_event_status = events.groupby("period", as_index=False).agg(
        _has_unresolved_event=(
            "source_status",
            lambda values: bool((~values.eq("curated")).any()),
        ),
        _has_ambiguous_event=(
            "direction",
            lambda values: bool(values.eq("ambiguous").any()),
        ),
    )
    curated_events = events.loc[events["source_status"].eq("curated")].copy()
    explicit_signal = (
        pd.to_numeric(curated_events["signal_value"], errors="coerce")
        if "signal_value" in curated_events.columns
        else pd.Series(np.nan, index=curated_events.index)
    )
    curated_events["signal_value"] = np.select(
        [
            curated_events["direction"].eq("restrictive"),
            curated_events["direction"].eq("relaxing"),
            curated_events["direction"].eq("neutral"),
        ],
        [curated_events["severity"], -curated_events["severity"], 0.0],
        default=np.nan,
    )
    curated_events["signal_value"] = explicit_signal.where(
        explicit_signal.notna(), curated_events["signal_value"]
    )
    curated_events = curated_events.dropna(subset=["signal_value"])
    monthly_events = curated_events.groupby("period", as_index=False).agg(
        _event_signal=("signal_value", "sum"),
        policy_published_at=("published_at", "max"),
    )

    coverage = pd.read_csv(coverage_path)
    coverage = _normalize_months(coverage, "Policy coverage")
    required_coverage = {"coverage_status", "source_url"}
    if not required_coverage.issubset(coverage.columns):
        raise SystemExit("Policy coverage CSV needs period, coverage_status, and source_url columns.")
    coverage["coverage_status"] = coverage["coverage_status"].fillna("incomplete").astype(str).str.strip().str.lower()
    if not coverage["coverage_status"].isin(["complete", "incomplete"]).all():
        raise SystemExit("coverage_status must be 'complete' or 'incomplete'.")
    coverage["source_status"] = _source_status(coverage)
    if not coverage["source_url"].astype(str).str.startswith("https://").all():
        raise SystemExit("Every policy coverage source_url must use HTTPS.")
    coverage["coverage_is_approved"] = coverage["coverage_status"].eq("complete") & coverage["source_status"].eq("curated")

    result = pd.DataFrame({"period": pd.to_datetime(periods).drop_duplicates().sort_values()})
    result = result.merge(coverage[["period", "coverage_status", "source_status", "coverage_is_approved"]], on="period", how="left", validate="one_to_one")
    result = result.merge(monthly_events, on="period", how="left", validate="one_to_one")
    result = result.merge(monthly_event_status, on="period", how="left", validate="one_to_one")
    result["coverage_is_approved"] = (
        result["coverage_is_approved"].eq(True)
        & ~result["_has_unresolved_event"].astype("boolean").fillna(False).astype(bool)
        & ~result["_has_ambiguous_event"].astype("boolean").fillna(False).astype(bool)
    )
    result["policy_signal"] = np.where(
        result["coverage_is_approved"].eq(True),
        result["_event_signal"].fillna(0.0),
        np.nan,
    )
    result["policy_event_coverage_complete"] = result["coverage_is_approved"].fillna(False)
    result["policy_source_status"] = np.where(result["coverage_is_approved"].eq(True), "curated", "unverified")
    return result[["period", "policy_signal", "policy_published_at", "policy_event_coverage_complete", "policy_source_status"]]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge release-aware monthly indicators and completeness-verified policy events."
    )
    parser.add_argument("target_csv", help="Normalized monthly target file with period and target_value_usd")
    parser.add_argument("--features", default=None, help="Monthly feature CSV from fetch_fred_features.py or manually curated")
    parser.add_argument("--policy-events", default=None, help="Policy event CSV with direction, severity, dates, and source URLs")
    parser.add_argument("--policy-coverage", default=None, help="Required monthly completeness CSV for policy zero-filling")
    parser.add_argument("--output", default=str(ROOT / "data" / "benchmark_with_features.csv"))
    args = parser.parse_args()

    target = pd.read_csv(args.target_csv)
    if "target_value_usd" not in target and "export_value_usd" in target:
        target = target.rename(columns={"export_value_usd": "target_value_usd"})
    if not {"period", "target_value_usd"}.issubset(target.columns):
        raise SystemExit("Target CSV needs period and target_value_usd columns.")
    target = _normalize_months(target, "Target")
    target["target_value_usd"] = pd.to_numeric(target["target_value_usd"], errors="coerce")
    if target["target_value_usd"].isna().any() or not np.isfinite(target["target_value_usd"].to_numpy(dtype=float)).all():
        raise SystemExit("Target CSV contains invalid or non-finite target values.")
    if (target["target_value_usd"] < 0).any():
        raise SystemExit("Target trade values must be non-negative.")
    target = target.sort_values("period").reset_index(drop=True)

    if args.features:
        features = _normalize_months(pd.read_csv(args.features), "Feature")
        numeric_columns = [column for column in ("sector_ip_index", "economic_index") if column in features.columns]
        for column in numeric_columns:
            features[column] = pd.to_numeric(features[column], errors="coerce")
            features[column] = features[column].replace([np.inf, -np.inf], np.nan)
        features["feature_source_status"] = _source_status(features)
        feature_select = ["period", *numeric_columns, "feature_source_status"]
        if "source_version" in features.columns:
            feature_select.append("source_version")
        target = target.drop(columns=numeric_columns + ["feature_source_status", "feature_source_version"], errors="ignore")
        features = features.rename(columns={"source_version": "feature_source_version"})
        target = target.merge(features[["period", *numeric_columns, "feature_source_status", *(["feature_source_version"] if "feature_source_version" in features else [])]], on="period", how="left", validate="one_to_one")
        target["feature_source_status"] = target["feature_source_status"].fillna("unverified")
    else:
        target["feature_source_status"] = "unverified"

    if args.policy_events and args.policy_coverage:
        policy = _policy_signal(args.policy_events, args.policy_coverage, target["period"])
        target = target.drop(columns=["policy_signal", "policy_published_at", "policy_event_coverage_complete", "policy_source_status"], errors="ignore")
        target = target.merge(policy, on="period", how="left", validate="one_to_one")
        target["policy_source_status"] = target["policy_source_status"].fillna("unverified")
        target["policy_event_coverage_complete"] = target["policy_event_coverage_complete"].fillna(False)
    elif args.policy_events or args.policy_coverage:
        print("WARNING: both --policy-events and --policy-coverage are required. Policy signals will remain missing; no zeroes will be inferred.")
        target["policy_signal"] = np.nan
        target["policy_event_coverage_complete"] = False
        target["policy_source_status"] = "unverified"
    else:
        target["policy_signal"] = pd.to_numeric(target.get("policy_signal", pd.Series(np.nan, index=target.index)), errors="coerce")
        target["policy_event_coverage_complete"] = False
        target["policy_source_status"] = "unverified"

    for column in ("target_published_at", "policy_published_at"):
        if column not in target:
            target[column] = ""
    if "source_version" not in target:
        target["source_version"] = ""
    if "feature_source_version" in target:
        target["source_version"] = (
            target["source_version"].fillna("").astype(str)
            + "; features=" + target["feature_source_version"].fillna("").astype(str)
        ).str.strip("; ")
    target["period"] = target["period"].dt.strftime("%Y-%m")
    target["policy_signal"] = target["policy_signal"].where(target["policy_source_status"].eq("curated"), np.nan)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    target.to_csv(output, index=False)
    complete_count = int(target["policy_event_coverage_complete"].sum())
    print(f"Saved merged monthly dataset with {len(target)} target rows to {output}.")
    print(f"Monthly policy coverage marked complete and curated: {complete_count}.")
    print("An absent event is zero only for a month with explicit complete + curated coverage; all other months remain missing.")
    print("Review source units, code changes, release dates, feature provenance, and classification scope before import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
