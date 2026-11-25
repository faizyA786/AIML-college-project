from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

from ml_engine.benchmark import compare_models
from ml_engine.demo_data import synthetic_demo_rows
from persistence import get_benchmark_rows, get_papers, get_run_history


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
load_dotenv(ROOT / ".env")
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

# The prototype's research scope is U.S. semiconductor-related exports to China.
# Schedule B 8542.31 is a broad product classification, not an AI-chip-only series.
BENCHMARK_CASES: dict[str, dict[str, str]] = {
    "us_china": {
        "series_key": "us_exports_cn_854231",
        "target_name": "U.S. exports of processors/controllers to China",
        "target_series": (
            "U.S. Census monthly exports, Schedule B 8542.31; verify annual code continuity, "
            "coverage, revisions, and suppressed values before interpretation"
        ),
        "source_url": "https://www.census.gov/data/developers/data-sets/international-trade.html",
        "source_label": "U.S. Census monthly international trade exports data",
        "default_note": (
            "Schedule B 8542.31 covers electronic integrated circuits (processors/controllers); "
            "it is not a direct measure of AI accelerator exports or the full semiconductor trade. "
            "Check annual classification changes and data suppression."
        ),
    },
}


def _case_config(case: str | None) -> tuple[str, dict[str, str]]:
    selected = (case or "us_china").strip()
    if selected not in BENCHMARK_CASES:
        raise ValueError("The only configured benchmark is U.S. semiconductor-related exports to China (us_china).")
    return selected, BENCHMARK_CASES[selected]


def _classify_source_status(rows: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get("source_status") or "missing").strip().lower()
        if value not in {"curated", "unverified"}:
            value = "missing"
        counts[value] = counts.get(value, 0) + 1
    if counts and counts.get("curated", 0) == len(rows):
        return "curated", counts
    if counts and counts.get("curated", 0) == 0:
        return "unverified", counts
    return "mixed", counts


def _dataset(case: str) -> tuple[list[dict[str, Any]], str, str, str | None, dict[str, int]]:
    config = BENCHMARK_CASES[case]
    rows, db_status = get_benchmark_rows(config["series_key"])
    if rows:
        status, counts = _classify_source_status(rows)
        return rows, "postgresql", status, None, counts

    # Synthetic data is only enabled by explicit configuration; it is never
    # represented as a verified or curated research dataset.
    if os.getenv("DEMO_MODE", "false").casefold() == "true":
        status_note = (
            f"{config['default_note']} Synthetic demonstration values are being used because "
            "no PostgreSQL observations were found. These are fabricated, not official data."
        )
        if db_status:
            status_note = f"{status_note} Database status: {db_status}."
        synthetic = synthetic_demo_rows()
        return synthetic, "synthetic_demo", "synthetic", status_note, {"synthetic": len(synthetic)}

    if db_status and str(db_status).startswith("postgresql_unavailable"):
        raise RuntimeError(
            f"PostgreSQL benchmark data are unavailable ({db_status}). Check DATABASE_URL and database connectivity."
        )
    raise RuntimeError(
        "No benchmark observations are available. Load the U.S.-China monthly series into PostgreSQL, "
        "or explicitly set DEMO_MODE=true for a synthetic interface preview."
    )


def _data_metadata(
    rows: list[dict[str, Any]],
    case: str,
    mode: str,
    status: str,
    note: str | None,
    status_counts: dict[str, int],
) -> dict[str, Any]:
    config = BENCHMARK_CASES[case]
    return {
        "case": case,
        "series_key": config["series_key"],
        "mode": mode,
        "status": status,
        "synthetic": mode == "synthetic_demo",
        "note": note,
        "source_url": config["source_url"],
        "source_label": config["source_label"],
        "record_count": len(rows),
        "source_status_counts": status_counts,
    }


def _parse_uploaded_csv(raw_text: str) -> list[dict[str, Any]]:
    if len(raw_text.encode("utf-8")) > 900_000:
        raise ValueError("CSV upload is too large. Keep it under 900 KB.")
    reader = csv.DictReader(io.StringIO(raw_text))
    target_field = (
        "target_value_usd"
        if reader.fieldnames and "target_value_usd" in reader.fieldnames
        else "export_value_usd"
    )
    if not reader.fieldnames or not {"period", target_field}.issubset(set(reader.fieldnames)):
        raise ValueError("CSV needs `period` and `target_value_usd` columns. Use the provided benchmark template.")
    rows = list(reader)
    if len(rows) > 1200:
        raise ValueError("Upload is limited to 1,200 monthly rows.")
    if not rows:
        raise ValueError("CSV has no data rows.")
    return rows


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/<path:asset_name>")
def public_asset(asset_name: str):
    return send_from_directory(PUBLIC_DIR, asset_name)


@app.get("/api/health")
def health():
    llm_configured = all(os.getenv(key) for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
    review_public = os.getenv("LLM_REVIEW_PUBLIC", "false").casefold() == "true"
    return jsonify({
        "status": "ok",
        "app": "Cross-Domain Research Signal Lab",
        "database_configured": bool(os.getenv("DATABASE_URL")),
        "llm_review_configured": llm_configured,
        "review_available": review_public and llm_configured,
        "benchmark_case": "us_china",
    })


@app.get("/api/benchmark")
def benchmark():
    try:
        case, config = _case_config(request.args.get("case"))
        rows, mode, status, note, status_counts = _dataset(case)
        result = compare_models(
            rows,
            target_name=config["target_name"],
            target_series=config["target_series"],
        )
        result["data"] = _data_metadata(rows, case, mode, status, note, status_counts)
        result["source_citations"] = [
            {"label": config["source_label"], "url": config["source_url"]},
            {"label": "BIS semiconductor export-control regulations", "url": "https://www.bis.gov/regulations/ear/744"},
            {"label": "U.S. semiconductor/electronics industrial production (FRED IPG3344S)", "url": "https://fred.stlouisfed.org/series/IPG3344S"},
            {"label": "Chinese yuan per U.S. dollar exchange rate (FRED EXCHUS)", "url": "https://fred.stlouisfed.org/series/EXCHUS"},
            {"label": "U.S. Census Schedule B, Chapter 85", "url": "https://www.census.gov/foreign-trade/schedules/b/2026/c85.pdf"},
        ]
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/papers")
def papers():
    domain = request.args.get("domain")
    try:
        records, source = get_papers(domain)
        return jsonify({"papers": records, "source": source, "count": len(records)})
    except Exception:
        app.logger.exception("Could not load research papers")
        return jsonify({"error": "Research papers are temporarily unavailable."}), 503


@app.get("/api/sources")
def sources():
    path = DATA_DIR / "source_registry.csv"
    if not path.exists():
        return jsonify({"sources": [], "warning": "data/source_registry.csv was not included in this file review."})
    with path.open(encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    return jsonify({"sources": records})


@app.get("/api/history")
def history():
    try:
        return jsonify({"runs": get_run_history(), "database_configured": bool(os.getenv("DATABASE_URL"))})
    except Exception:
        app.logger.exception("Could not load forecast history")
        return jsonify({
            "runs": [],
            "database_configured": bool(os.getenv("DATABASE_URL")),
            "error": "Saved forecast history is temporarily unavailable.",
        }), 503


@app.get("/api/template")
def template():
    return send_from_directory(DATA_DIR, "benchmark_template.csv", as_attachment=True)


@app.post("/api/analyze")
def analyze_upload():
    payload = request.get_json(silent=True) or {}
    raw_text = payload.get("csv_text")
    if not isinstance(raw_text, str):
        return jsonify({"error": "Send a CSV file as the `csv_text` field."}), 400
    try:
        rows = _parse_uploaded_csv(raw_text)
        case, config = _case_config(payload.get("case"))
        result = compare_models(
            rows,
            target_name=config["target_name"],
            target_series=config["target_series"],
        )
        result["data"] = {
            "case": case,
            "source_url": config["source_url"],
            "source_label": "User-provided temporary CSV upload",
            "mode": "temporary_upload",
            "status": "temporary_upload",
            "synthetic": False,
            "note": "Analyzed in memory for this request only. This upload is not saved to PostgreSQL and is not treated as curated.",
            "record_count": len(rows),
        }
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Temporary CSV analysis failed")
        return jsonify({
            "error": f"Analysis could not be completed: {type(exc).__name__}. Check the CSV schema and monthly coverage."
        }), 400


@app.post("/api/review")
def review():
    if os.getenv("LLM_REVIEW_PUBLIC", "false").casefold() != "true":
        return jsonify({
            "available": False,
            "message": "Public LLM review is disabled. Configure a reviewed provider and an abuse/cost limit before enabling it.",
        }), 403
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    if not isinstance(result, dict):
        return jsonify({"error": "Provide a structured benchmark result."}), 400
    try:
        # Review support is an optional project dependency and was not part of
        # the uploaded audit set. Import lazily so the research dashboard still
        # starts when that optional module is absent.
        from ml_engine.review import review_benchmark
    except ImportError:
        return jsonify({
            "available": False,
            "message": "The optional ml_engine.review module is not present in this project copy.",
        }), 503
    return jsonify(review_benchmark(result))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
