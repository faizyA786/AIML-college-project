# Data dictionary

## Observation table

| Field | Meaning | Rule |
|---|---|---|
| series_key | Stable benchmark identifier | One target definition and geography per key |
| period | Month represented by the target observation | First day of month in PostgreSQL; YYYY-MM in CSV |
| target_value_usd | Observed monthly trade value in USD | Non-negative, numeric, same unit and trade direction within a series |
| policy_signal | Monthly sum of preregistered scores for relevant published policy events | Default codebook: +1 per verified qualifying event; feature is shifted one month by the model |
| sector_ip_index | Semiconductor/electronics activity indicator | Preserve source series and release/vintage metadata; feature is shifted one month |
| economic_index | Broader economic indicator | Preserve unit and transformations; feature is shifted one month |
| target_published_at | Date target observation became public | Keep when known; not currently used to enforce vintage availability |
| policy_published_at | Date policy information became public | Keep for audit; event feature should not precede this date |
| source_version | Retrieval/version/edition note | Required in PostgreSQL; e.g. source name and retrieval date |
| source_status | Curation state | Imported rows use curated; synthetic data never goes into PostgreSQL through the app |

## Benchmark keys

| Key | Target | Source |
|---|---|---|
| india_imports_hs8542_world | India imports of candidate HS 8542 from all partners | Government of India TradeStat |
| india_imports_hs8542_china | India imports of candidate HS 8542 from China | Government of India TradeStat |
| india_imports_hs8542_us | India imports of candidate HS 8542 from the United States | Government of India TradeStat |
| us_exports_cn_854231 | U.S. exports of proposed Schedule B 8542.31 to China | U.S. Census Bureau |

## Derived target

The supervised target is the log change in one plus trade value three months ahead:

    log(1 + trade_value[t + 3]) - log(1 + trade_value[t])

Metrics transform this log change with expm1 and report mean absolute error (MAE), root mean squared error (RMSE), and directional accuracy in percentage points. Because the transformation uses one plus value, it closely approximates ordinary percentage change for large trade values and remains defined for zero values. Direction accuracy excludes actual changes of effectively zero.

The supervised models use target-history lags and, when present, selected external indicators. External indicator values use a one-month lag as a conservative availability rule. This does not enforce exact source publication calendars or historical revisions; use point-in-time vintages before making real-time claims. Unsupervised K-means uses standardized lagged feature vectors for descriptive grouping; the cluster summaries are retrospective and are not forecasts.
