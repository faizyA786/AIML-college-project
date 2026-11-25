# Research protocol

## Research question

For monthly semiconductor-related trade outcomes, do cross-domain policy, technology-sector, and economic indicators improve three-month-ahead forecasts over transparent statistical baselines? The India cases focus on import exposure by supplier. A separate U.S.-to-China export series provides geopolitical/trade-policy context.

The study asks whether ML adds useful predictive value. It does not assume that AI is superior, that additional domains are automatically helpful, or that a model's forecast explains causation.

## Pre-analysis decisions

Before examining the test scores, record:

- benchmark key, exact product code, trade direction, geography, and unit;
- source, retrieval date, source version, revisions, missing periods, and code concordance;
- which events and indicators are eligible, including publication dates and release lags;
- forecast horizon (currently fixed at three months);
- training and evaluation windows;
- model families and metrics.

Do not switch codes, feature definitions, or evaluation windows merely because a change improves the reported score. If a definition changes, publish a new benchmark version.

For the starter policy-event worksheet, use +1 for a verified, pre-defined relevant policy event and zero in months without a qualifying event. Do not invent subjective event weights after inspecting model results. Publish the event inclusion rule and source link with the data.

## Models and comparison

The app uses:

- no-change, recent-momentum, and same-period-last-year forecasts as simple baselines;
- a linear autoregression using target history;
- when external features exist, a linear cross-domain regression and a small random forest.
- K-means clustering over standardized historical feature vectors for exploratory pattern discovery; cluster descriptions are not forecasts.

The rolling evaluation preserves chronology and avoids training on labels whose full three-month outcome had not elapsed at the forecast origin. Every supervised model is compared on the same origins. The linear and forest pipelines impute missing predictors using training-window medians; the imputer is refit inside each fold. The K-means summaries are descriptive and are fit across the available feature history; their retrospective mean outcomes must not be presented as prospective cluster predictions.

The current implementation is a compact college demonstration, not an exhaustive forecast tournament. It does not yet include seasonal ARIMA/ETS, probabilistic forecasts, formal significance tests, or point-in-time historical vintages. Add them as separately documented extensions rather than silently replacing a baseline.

## Metrics

Primary scores are MAE and RMSE of the three-month percentage change, in percentage points. Directional accuracy is secondary and can be unstable in short windows. A lower historical score does not guarantee a better future forecast.

## India interpretation

The India series measures customs-recorded import values for a selected product code and partner grouping. It can help describe changes in supply exposure, but it is not an outcome for India's total welfare, domestic semiconductor production, or strategic autonomy. A forecast association with an export-control signal is not a causal estimate. For causal claims, use an explicit identification design, comparison group, and assumptions.

## Historical episodes

The Industrial Revolution, World Wars, and Vietnam War may be useful literature or case-study contexts. They are not labels in this monthly supervised task and are not directly comparable to contemporary chip-trade controls without a defensible operational definition.

## LLM reviewer

The optional OpenAI-compatible endpoint receives a compact forecast summary and returns a short methods critique. It does not access the full database, validate source links, change model output, or determine correctness. Keep it disabled in public deployments until provider keys, spending limits, rate limits, and privacy terms are reviewed.
