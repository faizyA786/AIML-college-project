# Cross-Domain Research Signal Lab — corrected project files

This package contains the corrected versions of the project files supplied for audit. It is arranged in the expected project layout; do not copy every file into one flat directory.

## File placement

| Package path | Intended project path | Purpose |
|---|---|---|
| `public/index.html` | `public/index.html` | Single U.S.–China case selector and slide-based benchmark dashboard |
| `public/styles.css` | `public/styles.css` | Horizontal slideshow and responsive styles |
| `public/app.js` | `public/app.js` | U.S.–China default, distinct data-status messaging, slideshow navigation |
| `app.py` | `app.py` | Flask API configuration, U.S.–China-only benchmark, status-aware responses |
| `persistence.py` | `persistence.py` | Returns source status and enforces curated-only persistence inside the database transaction |
| `schema.sql` | `schema.sql` | Unverified-by-default observations, status constraints, and monthly policy coverage table |
| `ml_engine/benchmark.py` | `ml_engine/benchmark.py` | Seasonal-baseline alignment fix and stricter input validation |
| `ml_engine/demo_data.py` | `ml_engine/demo_data.py` | Explicitly synthetic, deterministic UI-only demonstration data |
| `scripts/import_benchmark_csv.py` | `scripts/import_benchmark_csv.py` | Status argument defaults to unverified; validates monthly continuity and values |
| `scripts/merge_features.py` | `scripts/merge_features.py` | Completeness-aware policy signals; no implicit zero for missing event months |
| `scripts/fetch_fred_features.py` | `scripts/fetch_fred_features.py` | Uses FRED `EXCHUS` for CNY per USD |
| `scripts/fetch_census_exports.py` | `scripts/fetch_census_exports.py` | Validates classification, destination, dates, duplicates, nonnegative values, and gaps |
| `scripts/import_policy_events.py` | `scripts/import_policy_events.py` | Direction, severity, source status, and optional monthly completeness import |
| `scripts/save_benchmark_run.py` | `scripts/save_benchmark_run.py` | U.S.–China default, direct-run path bootstrap, fail-closed curated checks |
| `data/benchmark_template.csv` | `data/benchmark_template.csv` | Existing monthly target CSV template |
| `data/policy_events_template.csv` | `data/policy_events_template.csv` | New policy event input template |
| `data/policy_event_coverage_template.csv` | `data/policy_event_coverage_template.csv` | New monthly completeness declaration template |

## Important data-integrity rules

1. `source_status` defaults to `unverified`. A target CSV import is unverified unless the maintainer explicitly supplies `--status curated` and a non-empty `--curation-note`.
2. The SQL migration downgrades existing rows tagged `curated` exactly once. The previous schema defaulted missing status to curated, so those old labels cannot be trusted as proof of human review. Re-curate observations only after checking their source records.
3. Approved forecast persistence checks the current PostgreSQL observations again inside `persist_approved_run()`, including curated status, finite/non-negative values, at least 73 consecutive months, origin/target-period alignment, and finite forecast outputs. The CLI check is an additional guard, not the only guard.
4. A missing policy event row is **not** a zero. A policy month is zero-filled only when a monthly coverage record says `complete` and is itself marked `curated`, with no unverified or direction-ambiguous events in that month. Incomplete, absent, unverified, or ambiguous coverage remains null.
5. Census and FRED fetchers produce unverified data. Retrieval from an official API does not itself mean the data have been validated for product-code continuity, release timing, or research use.
6. Synthetic demo data and temporary CSV uploads are clearly identified and cannot be persisted as approved forecast runs.

## Core run commands

Run these from the project root, after restoring the project's existing environment and dependencies:

```bash
python -m flask --app app run
python scripts/fetch_census_exports.py --start 2010-01
python scripts/fetch_fred_features.py --start 2010-01-01
python scripts/merge_features.py data/census_exports.csv --features data/fred_features.csv
python scripts/import_benchmark_csv.py data/benchmark_with_features.csv
```

The example merge command intentionally omits policy events and coverage, so the policy feature remains missing. To add policy signals, supply **both** `--policy-events` and `--policy-coverage`; use `data/policy_events_template.csv` and `data/policy_event_coverage_template.csv` as formats. Set each reviewed event row's `source_status` and each reviewed coverage row's `source_status` to `curated` only after checking the underlying official source and completeness for that month. An unverified event in a month also blocks zero-filling.

After source review, an explicitly curated target series can be imported with:

```bash
python scripts/import_benchmark_csv.py data/benchmark_with_features.csv \
  --status curated \
  --curation-note "Document the product-code, coverage, revisions, units, and source checks completed"
```

Policy events and coverage can also be loaded to PostgreSQL. Keep the defaults unverified until the evidence is reviewed:

```bash
python scripts/import_policy_events.py data/policy_events.csv \
  --coverage-csv data/policy_event_coverage.csv \
  --event-status curated \
  --coverage-status-source curated \
  --curation-note "Cite the policy source set and explain why each month is complete"
```

Only after the PostgreSQL rows are marked curated should a maintainer save an approved run:

```bash
python scripts/save_benchmark_run.py
```

Set `DATABASE_URL` in a local `.env` file. Set `CENSUS_API_KEY` for the Census fetcher. Do not commit secrets. `DEMO_MODE=true` explicitly enables synthetic UI preview when PostgreSQL has no usable observations; the default is off.

## Existing project files not included in this package

The uploaded audit set did not include these dependencies referenced by the project. Keep the project's existing versions in place; they have not been rewritten or validated here:

- `ml_engine/review.py`
- `data/papers.csv`
- `data/source_registry.csv`
- the project's dependency manifest and deployment configuration (for example `requirements.txt`, `.env`, or hosting files)

No real Census/FRED/policy dataset is included or fabricated in this package.

## Validation status

The package was assembled from the uploaded originals and already-prepared Step 12–14 fixes. Syntax and static checks are run before delivery. Full database integration, API calls, frontend browser checks, and end-to-end backtesting still require the project's environment, credentials, data, and PostgreSQL instance.
