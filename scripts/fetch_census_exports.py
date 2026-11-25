from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_URL = "https://api.census.gov/data/timeseries/intltrade/exports/hs"


def parse_month(value: str, field_name: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
    except (ValueError, AttributeError) as exc:
        raise SystemExit(f"{field_name} must use YYYY-MM format.") from exc
    if year < 1989 or month < 1 or month > 12:
        raise SystemExit(f"{field_name} must be a valid Census monthly period in YYYY-MM format.")
    return year, month


def month_before_today(months: int) -> str:
    year, month = date.today().year, date.today().month
    for _ in range(months):
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return f"{year}-{month:02d}"


def fetch_rows(start: str, end: str, api_key: str, commodity: str, country_code: str) -> list[dict[str, str]]:
    params = {
        "get": "E_COMMODITY,E_COMMODITY_SDESC,CTY_CODE,CTY_NAME,YEAR,MONTH,ALL_VAL_MO,LAST_UPDATE",
        "time": f"from {start} to {end}",
        "E_COMMODITY": commodity,
        "CTY_CODE": country_code,
        "key": api_key,
    }
    response = requests.get(API_URL, params=params, timeout=45)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError(f"Census returned no observations: {payload!r}")
    headers = payload[0]
    if not isinstance(headers, list) or not headers:
        raise RuntimeError(f"Census response has no header row: {payload!r}")
    rows = [dict(zip(headers, row)) for row in payload[1:] if len(row) == len(headers)]
    if not rows:
        raise RuntimeError("Census returned zero usable rows. Check commodity, destination, and date range.")
    return rows


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Fetch monthly U.S. exports of integrated circuits to China from Census.")
    parser.add_argument("--start", default="2010-01", help="First month (YYYY-MM)")
    parser.add_argument("--end", default=None, help="Last month (YYYY-MM); default is two months before today")
    parser.add_argument("--commodity", default=os.getenv("US_EXPORT_COMMODITY_CODE", "854231"), help="Schedule B commodity code")
    parser.add_argument("--country", default=os.getenv("US_EXPORT_DESTINATION_CODE", "5700"), help="Census destination code for China")
    parser.add_argument("--output", default=str(ROOT / "data" / "census_exports.csv"))
    args = parser.parse_args()

    start = args.start.strip()
    end = (args.end or month_before_today(2)).strip()
    start_tuple = parse_month(start, "--start")
    end_tuple = parse_month(end, "--end")
    if end_tuple < start_tuple:
        parser.error("--end must be on or after --start.")
    commodity = str(args.commodity).strip()
    country = str(args.country).strip()
    if not commodity.isdigit() or not country.isdigit():
        parser.error("--commodity and --country must be numeric Census classification codes.")

    api_key = os.getenv("CENSUS_API_KEY", "").strip()
    if not api_key:
        print("Set CENSUS_API_KEY in your environment or local .env file. Do not commit the key.", file=sys.stderr)
        return 2

    rows = fetch_rows(start, end, api_key, commodity, country)
    retrieved = date.today().isoformat()
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            year = int(str(row["YEAR"]).strip())
            month = int(str(row["MONTH"]).strip())
            if month < 1 or month > 12:
                raise ValueError("month is outside 1..12")
            period = f"{year:04d}-{month:02d}"
            amount = float(str(row["ALL_VAL_MO"]).replace(",", "").strip())
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Census returned an invalid year, month, or monthly export value: {row!r}") from exc
        if not math.isfinite(amount) or amount < 0:
            raise RuntimeError(f"Census returned an invalid negative or non-finite amount for {period}: {amount!r}")
        if period in seen:
            raise RuntimeError(f"Census returned duplicate observation period {period}.")
        seen.add(period)

        returned_commodity = str(row.get("E_COMMODITY", "")).strip()
        returned_country = str(row.get("CTY_CODE", "")).strip()
        if returned_commodity != commodity:
            raise RuntimeError(f"Census returned unexpected commodity {returned_commodity!r}; expected {commodity!r}.")
        if returned_country and returned_country != country:
            raise RuntimeError(f"Census returned unexpected destination {returned_country!r}; expected {country!r}.")
        if not (start <= period <= end):
            raise RuntimeError(f"Census returned observation {period} outside requested range {start} to {end}.")

        normalized.append({
            "period": period,
            "target_value_usd": str(amount),
            "policy_signal": "",
            "sector_ip_index": "",
            "economic_index": "",
            "target_published_at": "",
            "policy_published_at": "",
            "source_version": (
                f"Census_API;retrieved={retrieved};last_update={row.get('LAST_UPDATE', '')};"
                f"commodity={commodity};destination={country}"
            ),
            "source_status": "unverified",
            "commodity_code": returned_commodity,
            "commodity_description": str(row.get("E_COMMODITY_SDESC", "")).strip(),
            "destination_code": returned_country or country,
            "destination_name": str(row.get("CTY_NAME", "")).strip(),
        })

    normalized.sort(key=lambda item: item["period"])
    if not normalized:
        raise RuntimeError("Census returned no normalized observations.")
    start_year, start_month = start_tuple
    end_year, end_month = end_tuple
    expected_periods = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        expected_periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    missing_periods = sorted(set(expected_periods) - seen)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(normalized[0]))
        writer.writeheader()
        writer.writerows(normalized)

    print(f"Saved {len(normalized)} monthly rows to {output}; status=unverified.")
    print(f"Requested commodity {commodity}; destination {country}; requested period {start} to {end}.")
    if missing_periods:
        print(f"WARNING: {len(missing_periods)} requested month(s) were not returned: {', '.join(missing_periods[:24])}")
        print("Do not fill these months with zero without confirming Census coverage and suppression rules.")
    print("External policy and macro feature columns remain blank until release-dated sources and monthly coverage are reviewed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
