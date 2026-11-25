# Data status

The app starts with a deterministic **synthetic demonstration series**. It is fabricated for showing the interface and model workflow; it is not official data and must never be reported as a research finding.

The India case is the recommended first real-data case: monthly imports in USD for integrated circuits (candidate HS 8542), with optional India partner series for China and the United States. The Government of India TradeStat portal provides monthly commodity-by-country imports from 2010 onward. Confirm units, product-code continuity, revisions, and the source release status before treating a downloaded series as curated.

The U.S.–China series is a separate comparison case using Census monthly export values and the proposed Schedule B 8542.31 code. It is broader than AI accelerators and needs its own code-history and coverage review.

Use **benchmark_template.csv** to normalize each verified source extract to one row per month. Leave unsupported feature fields blank; do not fabricate feature values. Import a series with **scripts/import_benchmark_csv.py** and an explicit **--series-key**. Record source/version and publication dates in the CSV. The static source list is in **source_registry.csv**; field definitions are in **../docs/DATA_DICTIONARY.md**.

Policy events in **policy_events_template.csv** are blank by design. Add only verified event records with publication dates and direct citations. No example policy event is bundled as a real observation.
