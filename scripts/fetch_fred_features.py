from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SERIES = ("IPG3344S", "EXCHUS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch U.S. semiconductor/electronics production and USD/CNY exchange-rate indicators from FRED."
    )
    parser.add_argument("--start", default="2010-01-01", help="First observation date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Last observation date (YYYY-MM-DD); default is latest available")
    parser.add_argument("--output", default=str(ROOT / "data" / "fred_features.csv"))
    args = parser.parse_args()

    start = pd.to_datetime(args.start, errors="coerce")
    end = pd.to_datetime(args.end, errors="coerce") if args.end else None
    if pd.isna(start) or (args.end and pd.isna(end)):
        raise SystemExit("--start and --end must use YYYY-MM-DD dates.")
    if end is not None and end < start:
        raise SystemExit("--end must not be earlier than --start.")

    response = requests.get(
        FRED_CSV_URL,
        params={"id": ",".join(FRED_SERIES), "cosd": start.date().isoformat(), **({"coed": end.date().isoformat()} if end is not None else {})},
        timeout=45,
    )
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text))
    date_column = next(
        (column for column in frame.columns if str(column).casefold() in {"observation_date", "date"}),
        None,
    )
    if date_column is None:
        raise RuntimeError(f"Could not identify the date column in FRED response: {list(frame.columns)}")
    missing = set(FRED_SERIES) - set(frame.columns)
    if missing:
        raise RuntimeError(f"FRED response is missing expected series columns: {', '.join(sorted(missing))}.")

    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    frame = frame.dropna(subset=[date_column]).set_index(date_column).sort_index()
    for column in FRED_SERIES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)

    # Both requested series are monthly. Do not forward-fill absent observations.
    monthly = frame.resample("MS").mean(numeric_only=True)
    output_frame = monthly.rename(columns={
        "IPG3344S": "sector_ip_index",
        "EXCHUS": "economic_index",
    })[["sector_ip_index", "economic_index"]].reset_index(names="period")
    output_frame["usd_cny_rate"] = output_frame["economic_index"]
    output_frame["source_version"] = (
        f"FRED:{','.join(FRED_SERIES)}; monthly_mean; retrieved={date.today().isoformat()}"
    )
    output_frame["source_status"] = "unverified"
    output_frame["period"] = output_frame["period"].dt.strftime("%Y-%m")

    if output_frame.empty or output_frame[["sector_ip_index", "economic_index"]].notna().sum().sum() == 0:
        raise RuntimeError("FRED returned no usable monthly feature observations for the requested date range.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output_frame.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"Saved {len(output_frame)} monthly feature rows to {output}")
    print("IPG3344S is a U.S. semiconductor/electronics industrial-production proxy. EXCHUS is the monthly average CNY per USD (USD/CNY).")
    print("FRED series are revised/current-vintage observations; confirm release dates and historical vintages before training.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
