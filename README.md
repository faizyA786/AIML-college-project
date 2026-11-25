# Cross-Domain Research Signal Lab

A small, public research app for testing whether policy, semiconductor-sector, and economic signals help forecast a monthly trade outcome. It compares time-ordered statistical baselines with compact machine-learning models and displays the data source and limitations beside the result.

The app does not assume that AI is more accurate. A mixed or negative result is a valid result.

## Current research question

Can models forecast the three-month change in semiconductor-related trade, and do cross-domain indicators improve on transparent baselines?

The first lens is India's integrated-circuit imports from the world, with optional supplier series for China and the United States. A separate U.S.-to-China export series provides a policy/trade comparator. These series have separate product definitions and should not be compared as if they were identical measures.

Candidate India product category: HS 8542. Candidate U.S. product code: Schedule B 8542.31. Both are broad categories that require historical code, coverage, and unit checks. Trade values are not direct measures of domestic semiconductor capability, welfare, or strategic autonomy.

## What is included

- Bright, responsive single-page comparison interface.
- Flask API that serves the interface, cited starter-paper library, source registry, benchmark results, and temporary CSV analysis.
- Python ML package with expanding-window three-month backtests, no-change, momentum, and same-period-last-year baselines, autoregressive linear regression, and a small random forest.
- PostgreSQL schema for papers, source notes, monthly observations, policy events, forecast runs, and later observed outcomes.
- Explicitly labeled synthetic demo observations so the UI can open before the real data is curated.
- Optional OpenAI-compatible LLM reviewer that critiques methods only; it cannot modify the forecast and is disabled by default.
- Data templates and import scripts for Census data and normalized TradeStat extracts.

## Run locally

Use Python 3.12. From this folder:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    cp .env.example .env
    python app.py

Open http://127.0.0.1:5000. With the default DEMO_MODE=true, the page displays synthetic example results. These numbers are for interface demonstration only and are not research findings.

## Load real data

Create a PostgreSQL database and set DATABASE_URL in the local .env file. Then initialize the tables and seed cited papers/source records:

    python scripts/init_db.py
    python scripts/seed_reference_data.py

### India series

Use the Government of India [TradeStat monthly import-by-commodity-and-partner report](https://www.tradestat.commerce.gov.in/ftspcc/import_commodity_xcountry_wise_monthly). Select a monthly range, review the HS 8542 definition and history, choose World / China / United States as the partner, and select a USD value. Normalize the official extract into data/benchmark_template.csv with one row per month. Check all units, code continuity, missing months, publication/revision status, and source retrieval date.

Import each partner series under its own key:

    python scripts/import_benchmark_csv.py data/india_world.csv --series-key india_imports_hs8542_world --source-version "TradeStat download YYYY-MM-DD"
    python scripts/import_benchmark_csv.py data/india_china.csv --series-key india_imports_hs8542_china --source-version "TradeStat download YYYY-MM-DD"
    python scripts/import_benchmark_csv.py data/india_us.csv --series-key india_imports_hs8542_us --source-version "TradeStat download YYYY-MM-DD"

The importer validates that the target is a complete, contiguous monthly series with enough history for the rolling comparison. External feature columns may remain blank; cross-domain model variants appear only when verified features have been loaded.

### U.S.–China comparator

Set CENSUS_API_KEY in .env, then retrieve monthly U.S. export data:

    python scripts/fetch_census_exports.py --start 2010-01 --commodity 854231 --country 5700 --output data/us_china.csv
    python scripts/import_benchmark_csv.py data/us_china.csv --series-key us_exports_cn_854231 --source-version "Census retrieval YYYY-MM-DD"

The fetch script requires the Census API key. Keep the key private. The resulting category is not a precise proxy for AI accelerators, and code continuity and non-suppressed values must be inspected before use.

### Adding cross-domain features

Fetch monthly semiconductor production and INR/USD features from FRED, then merge them with a target file and a manually curated policy-event worksheet:

    python scripts/fetch_fred_features.py
    cp data/policy_events_template.csv data/policy_events.csv
    # Fill data/policy_events.csv with relevant, cited events before using it
    python scripts/import_policy_events.py data/policy_events.csv
    python scripts/merge_features.py data/india_world.csv --features data/fred_features.csv --policy-events data/policy_events.csv --output data/india_world_with_features.csv
    python scripts/import_benchmark_csv.py data/india_world_with_features.csv --series-key india_imports_hs8542_world --source-version "TradeStat plus FRED snapshot YYYY-MM-DD"

The FRED production series measures U.S. semiconductor/electronics output and is a proxy for sector activity, not Indian output. INR/USD is a broad economic input. Policy events must be source-verified and dated by publication. The model shifts numeric external features by one month, but it does not enforce exact release calendars or historical data vintages.

## Model comparison

The supervised label is the three-month log change in trade value. The app scores forecasts with MAE and RMSE in percentage points of the change, and reports direction accuracy as a secondary measure. Models use expanding historical windows and identical forecast origins. Training labels are withheld until their three-month outcome has matured.

The separate K-means analysis groups similar standardized feature patterns. It is descriptive, fit across the available historical features, and not a forward forecast.

The displayed backtest uses current curated historical values, not a full archive of what each source published at each historical forecast date. Revisions and release timing can therefore make it optimistic as a reconstruction of a real-time forecasting workflow. See docs/RESEARCH_PROTOCOL.md and docs/DATA_DICTIONARY.md before interpreting results.

To save a maintainer-reviewed forecast, set BENCHMARK_CASE in .env to india_world, india_china, india_us, or us_china, then run:

    python scripts/save_benchmark_run.py

The read-only history panel shows saved forecasts. Importing later monthly data updates any saved forecast whose target month and origin month are now observed.

## API routes

| Route | Use |
|---|---|
| GET /api/health | App, database, and optional review configuration |
| GET /api/benchmark?case=india_world | Benchmark; cases: india_world, india_china, india_us, us_china |
| GET /api/papers?domain=Technology | Cited research-paper catalogue |
| GET /api/sources | Source registry with limitations |
| GET /api/template | Download the monthly data template |
| GET /api/history | Read-only saved forecast history and later outcomes |
| POST /api/analyze | Analyze an in-memory CSV; not persisted |
| POST /api/review | Optional advisory LLM critique; disabled unless explicitly configured |

## Optional LLM methods reviewer

The LLM reviewer is not part of the forecast calculation. It receives a compact benchmark summary and may identify methodological caveats. It cannot inspect the database, validate citations, verify predictions, or overwrite results.

Configure LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL on the server. Keep LLM_REVIEW_PUBLIC=false until the provider, spending controls, public request limits, and privacy terms are reviewed. Never place the provider key in frontend code.

## Deploy on Vercel

The project uses a root-level Flask app and requirements.txt. Import the project into Vercel as a Python/Flask application, connect a managed PostgreSQL service with a serverless-compatible connection URL, and set these server-side variables:

| Variable | Use |
|---|---|
| DATABASE_URL | Required PostgreSQL connection string |
| DEMO_MODE | Keep true until real monthly data is loaded; then set false |
| LLM_REVIEW_PUBLIC | Keep false by default; set true only with reviewed provider limits |
| LLM_BASE_URL, LLM_API_KEY, LLM_MODEL | Optional server-side advisory reviewer configuration |

Initialize and seed the database once from a trusted local environment before switching DEMO_MODE=false. CENSUS_API_KEY is needed only when running the Census data-fetch script locally; it is not needed by the deployed app.

Vercel's Python function runtime serves the Flask API; the public directory contains the page assets. Keep the database connection pool small for serverless function instances. This prototype is designed for a small college demo, but actual response time and concurrent capacity should be checked on the chosen Vercel and database plans.

Official deployment guide: https://vercel.com/docs/frameworks/backend/flask

## Security and public access

No login system is included. Read-only research and temporary CSV analysis are public. CSV uploads are limited to 1 MB and are processed in memory, not written to PostgreSQL. Only curated data should be imported into shared tables. Keep database and provider credentials in server-side environment variables. Add rate limits and usage controls before exposing paid LLM requests or persistent public write operations.

## Project map

    app.py                         Flask routes and request handling
    ml_engine/                     Forecasting and optional advisory review
    persistence.py                 PostgreSQL access and CSV fallback
    database/schema.sql            PostgreSQL tables and indexes
    data/papers.csv                Cited starter research library
    data/source_registry.csv       Source URLs and limitations
    data/benchmark_template.csv    Normalized monthly observation format
    scripts/                       Data fetch, merge, seed, import, and run tools
    public/                        Frontend HTML, CSS, and JavaScript
    docs/                           Data protocol and research methods

## Research references

The initial cited papers are listed in data/papers.csv. Bibliographic relevance is a starting point for reading, not an endorsement of every claim in those papers. Verify the full text, methods, and source before citing a substantive conclusion.
