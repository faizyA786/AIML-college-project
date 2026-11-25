# India trade series workflow

## Recommended question

Can statistical and machine-learning models forecast the three-month change in India's integrated-circuit imports, and do dated semiconductor-policy and sector/economic indicators improve the forecast?

The main target is the monthly value of India's imports in USD for HS 8542 from the world. Add China- and U.S.-partner series as separate benchmark keys to inspect supplier-specific exposure:

- **india_imports_hs8542_world**
- **india_imports_hs8542_china**
- **india_imports_hs8542_us**

The U.S. export series is a contextual companion:

- **us_exports_cn_854231**

The product definitions are not automatically equivalent across national tariff schedules or historical revisions. Use the broad HS 8542 series as a candidate only after checking the source's historical classification, units, and coverage. Where a finer code is used, document its concordance by year.

## Source and extraction

The Department of Commerce, Government of India, exposes a monthly “Commodity x Country wise” import report through [TradeStat](https://www.tradestat.commerce.gov.in/ftspcc/import_commodity_xcountry_wise_monthly). The portal currently reports data availability from January 2010 onward and lets the user choose a monthly interval, commodity, partner, and value display.

1. Open the monthly commodity-by-country import report.
2. Select a calendar-month interval and the integrated-circuit commodity code being reviewed (start with HS 8542 only if its history is consistent).
3. Choose partner “World” for the aggregate, or choose China / United States for an individual supplier series.
4. Select a USD value measure; verify the unit displayed in the downloaded file.
5. Download the result and normalize it into **data/benchmark_template.csv** with one YYYY-MM row per month and target_value_usd in USD.
6. Add any external indicators only after documenting their source, unit, observation date, release date, and transformation. Leave unknown values blank.
7. Review every product code and missing month. The importer requires a complete, contiguous monthly target series.

TradeStat may publish provisional and revised values; preserve a source/version note and the download date. The portal also warns that commodity codes can be dropped or reallocated. A historical backtest built on the latest revised series is not a true real-time-vintage backtest.

## Import

After setting DATABASE_URL in .env and initializing the schema, import the normalized file with the key for that partner series. For example:

    python scripts/import_benchmark_csv.py data/india_world.csv --series-key india_imports_hs8542_world --source-version "TradeStat download YYYY-MM-DD"
    python scripts/import_benchmark_csv.py data/india_china.csv --series-key india_imports_hs8542_china --source-version "TradeStat download YYYY-MM-DD"
    python scripts/import_benchmark_csv.py data/india_us.csv --series-key india_imports_hs8542_us --source-version "TradeStat download YYYY-MM-DD"

Do not add event dummy values merely because a policy announcement occurred. The event must be relevant to the defined outcome, its publication date must be known, and the policy variable should be encoded before looking at the resulting model score.

## Interpretation guardrails

Trade value is affected by prices, quantity, currency conversion, demand, inventory cycles, routing, re-exports, classification, and revisions. An import forecast alone does not measure Indian domestic semiconductor output, strategic autonomy, employment, consumer welfare, or the causal effect of foreign export controls. Compare supplier-specific series and, if the research question expands, add independent outcomes such as electronics production or exports with their own official sources and versioned datasets.
