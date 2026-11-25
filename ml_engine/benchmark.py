from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


HORIZON_MONTHS = 3
TARGET_COLUMN = "target_value_usd"
EXTERNAL_CANDIDATES = ["policy_signal", "sector_ip_index", "economic_index"]


@dataclass
class PreparedData:
    frame: pd.DataFrame
    features: pd.DataFrame
    target_only_features: list[str]
    cross_domain_features: list[str]
    target: pd.Series
    usable: pd.DataFrame


def _as_frame(rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if TARGET_COLUMN not in frame and "export_value_usd" in frame:
        frame = frame.rename(columns={"export_value_usd": TARGET_COLUMN})
    required = {"period", TARGET_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(sorted(missing))}.")
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame[TARGET_COLUMN] = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    invalid_periods = int(frame["period"].isna().sum())
    invalid_targets = int(frame[TARGET_COLUMN].isna().sum())
    if invalid_periods or invalid_targets:
        raise ValueError(
            f"Dataset contains {invalid_periods} invalid period value(s) and "
            f"{invalid_targets} invalid target value(s). Correct these rows instead of silently dropping them."
        )
    if frame.empty:
        raise ValueError("Dataset has no monthly observations.")
    if not np.isfinite(frame[TARGET_COLUMN].to_numpy(dtype=float)).all():
        raise ValueError("Trade values must be finite numeric amounts.")
    if frame["period"].duplicated().any():
        raise ValueError("Dataset must contain one row per month; duplicate periods were found.")
    if (frame[TARGET_COLUMN] < 0).any():
        raise ValueError("Trade values must be non-negative.")

    frame = frame.sort_values("period").set_index("period").asfreq("MS")
    for column in EXTERNAL_CANDIDATES:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame[column] = frame[column].replace([np.inf, -np.inf], np.nan)
    if frame[TARGET_COLUMN].isna().any():
        missing_months = int(frame[TARGET_COLUMN].isna().sum())
        raise ValueError(f"Target series has {missing_months} missing month(s). Fill or document gaps before analysis.")
    return frame


def prepare_dataset(rows: list[dict[str, Any]] | pd.DataFrame, horizon: int = HORIZON_MONTHS) -> PreparedData:
    if horizon < 1 or horizon > 12:
        raise ValueError("Forecast horizon must be between 1 and 12 months.")
    frame = _as_frame(rows)
    log_value = np.log1p(frame[TARGET_COLUMN].clip(lower=0))
    features = pd.DataFrame(index=frame.index)

    for lag in (0, 1, 3, 6, 12):
        features[f"target_log_lag_{lag}"] = log_value.shift(lag)
    for window in (1, 3, 6, 12):
        features[f"target_log_change_{window}m"] = log_value - log_value.shift(window)

    cross_features: list[str] = []
    if frame["policy_signal"].notna().any():
        # Use only signals dated before the forecast origin month. This is a
        # conservative one-month publication/availability lag, not a substitute
        # for full point-in-time data vintages.
        available_policy = frame["policy_signal"].shift(1)
        features["policy_signal_lagged"] = available_policy
        features["policy_signal_3m_sum"] = available_policy.rolling(3, min_periods=1).sum()
        cross_features.extend(["policy_signal_lagged", "policy_signal_3m_sum"])
    for source_column, feature_prefix in (("sector_ip_index", "sector_ip"), ("economic_index", "economic_index")):
        if frame[source_column].notna().any():
            # Economic indicators are typically released with a delay. A
            # one-month lag prevents the model from consuming the current
            # month's value as if it were already known at month end.
            series = frame[source_column].shift(1).replace(0, np.nan)
            features[f"{feature_prefix}_level"] = series
            features[f"{feature_prefix}_3m_log_change"] = np.log(series).diff(3)
            cross_features.extend([f"{feature_prefix}_level", f"{feature_prefix}_3m_log_change"])

    target = log_value.shift(-horizon) - log_value
    usable = features.copy()
    usable["_target"] = target
    usable = usable.replace([np.inf, -np.inf], np.nan).dropna(subset=["_target", "target_log_lag_12"])
    # Keep the momentum feature available to the deterministic baseline.
    usable["_target"] = target.loc[usable.index]

    target_only = [column for column in features if column.startswith("target_")]
    return PreparedData(frame, features, target_only, cross_features, target, usable)


def _model_pipeline(kind: str):
    if kind == "linear":
        return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), LinearRegression())
    if kind == "forest":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            RandomForestRegressor(
                n_estimators=60,
                max_depth=4,
                min_samples_leaf=4,
                max_features=0.8,
                random_state=17,
                n_jobs=1,
            ),
        )
    raise ValueError(f"Unknown model type: {kind}")


def _pct_from_log_change(value: float) -> float:
    return float(np.expm1(np.clip(value, -20, 20)) * 100)


def _score(actual_log: np.ndarray, predicted_log: np.ndarray) -> dict[str, float | int | None]:
    actual_pct = np.array([_pct_from_log_change(value) for value in actual_log], dtype=float)
    predicted_pct = np.array([_pct_from_log_change(value) for value in predicted_log], dtype=float)
    error = predicted_pct - actual_pct
    nonzero = np.abs(actual_pct) > 1e-9
    direction = float(np.mean(np.sign(actual_pct[nonzero]) == np.sign(predicted_pct[nonzero]))) if nonzero.any() else None
    return {
        "n_forecasts": int(len(actual_pct)),
        "mae_percentage_points": float(np.mean(np.abs(error))),
        "rmse_percentage_points": float(np.sqrt(np.mean(error**2))),
        "direction_accuracy": direction,
    }


def _rolling_predictions(prepared: PreparedData, feature_columns: list[str], kind: str, max_folds: int = 36) -> tuple[list[dict[str, Any]], list[float], list[float]]:
    usable = prepared.usable
    horizon = HORIZON_MONTHS
    min_train_rows = 48
    origins = list(range(min_train_rows + horizon, len(usable)))
    if not origins:
        raise ValueError(f"At least {min_train_rows + horizon + 1} usable monthly rows are needed after lag creation.")
    origins = origins[-max_folds:]
    scored_rows: list[dict[str, Any]] = []
    actuals: list[float] = []
    predictions: list[float] = []
    for origin_position in origins:
        # Training labels are usable only after their full forecast horizon has elapsed.
        last_train_position = origin_position - horizon
        train = usable.iloc[: last_train_position + 1]
        test = usable.iloc[[origin_position]]
        if len(train) < min_train_rows:
            continue
        model = _model_pipeline(kind)
        model.fit(train[feature_columns], train["_target"])
        prediction = float(model.predict(test[feature_columns])[0])
        actual = float(test["_target"].iloc[0])
        origin = test.index[0]
        target_period = origin + pd.DateOffset(months=horizon)
        scored_rows.append({
            "forecast_origin": origin.strftime("%Y-%m"),
            "target_period": target_period.strftime("%Y-%m"),
            "actual_change_pct": _pct_from_log_change(actual),
            "predicted_change_pct": _pct_from_log_change(prediction),
        })
        actuals.append(actual)
        predictions.append(prediction)
    return scored_rows, actuals, predictions


def _discover_regimes(prepared: PreparedData) -> dict[str, Any]:
    """Describe recurring feature patterns; this is exploratory, not a forecast."""
    usable = prepared.usable
    columns = prepared.target_only_features + prepared.cross_domain_features
    values = usable[columns].replace([np.inf, -np.inf], np.nan)
    imputer = SimpleImputer(strategy="median", add_indicator=True)
    filled = imputer.fit_transform(values)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(filled)
    cluster_count = min(3, max(2, len(usable) // 20))
    cluster_count = min(cluster_count, len(usable) - 1)
    clusterer = KMeans(n_clusters=cluster_count, n_init=10, random_state=17)
    labels = clusterer.fit_predict(scaled)
    summaries = []
    for cluster_id in range(cluster_count):
        mask = labels == cluster_id
        observed = usable.loc[mask, "_target"].to_numpy(dtype=float)
        mean_change = _pct_from_log_change(float(np.mean(observed))) if len(observed) else 0.0
        if mean_change > 0.05:
            description = "Positive mean realized change"
        elif mean_change < -0.05:
            description = "Negative mean realized change"
        else:
            description = "Near-zero mean realized change"
        summaries.append({
            "cluster": cluster_id + 1,
            "observations": int(mask.sum()),
            "mean_realized_change_pct": mean_change,
            "description": description,
        })
    latest_values = prepared.features.iloc[[-1]][columns].replace([np.inf, -np.inf], np.nan)
    latest_cluster = int(clusterer.predict(scaler.transform(imputer.transform(latest_values)))[0]) + 1
    return {
        "method": "K-means clustering over standardized target-history and available lagged external features",
        "feature_count": len(columns),
        "latest_feature_cluster": latest_cluster,
        "clusters": summaries,
        "caveat": "Clusters are descriptive, fit across the available feature history, and not a prediction or causal regime. Their mean outcomes are retrospective summaries.",
    }


def compare_models(
    rows: list[dict[str, Any]] | pd.DataFrame,
    *,
    horizon: int = HORIZON_MONTHS,
    target_name: str = "Monthly integrated-circuit trade value",
    target_series: str = "Product code and geography require validation",
) -> dict[str, Any]:
    if horizon != HORIZON_MONTHS:
        # The first benchmark is explicitly defined as a three-month horizon.
        raise ValueError("The selected first benchmark uses a fixed three-month horizon.")
    prepared = prepare_dataset(rows, horizon)
    usable = prepared.usable
    if len(usable) < 58:
        raise ValueError("At least 73 consecutive monthly observations are needed to initialize the rolling comparison.")

    model_specs: list[tuple[str, str, list[str], str]] = [
        ("zero_change", "Statistical baseline · no change", [], "constant"),
        ("recent_momentum", "Statistical baseline · recent momentum", [], "momentum"),
        ("seasonal_naive", "Statistical baseline · same period last year", [], "seasonal"),
        ("linear_target_only", "Classical statistical · linear autoregression", prepared.target_only_features, "linear"),
    ]
    if prepared.cross_domain_features:
        model_specs.extend([
            ("linear_cross_domain", "Classical statistical · cross-domain regression", prepared.target_only_features + prepared.cross_domain_features, "linear"),
            ("forest_cross_domain", "ML · cross-domain random forest", prepared.target_only_features + prepared.cross_domain_features, "forest"),
        ])

    comparisons: list[dict[str, Any]] = []
    all_backtests: dict[str, list[dict[str, Any]]] = {}
    for model_id, label, columns, kind in model_specs:
        if kind in {"constant", "momentum", "seasonal"}:
            origins = list(range(48 + horizon, len(usable)))[-36:]
            scored = []
            actuals = []
            predictions = []
            for position in origins:
                row = usable.iloc[position]
                if kind == "constant":
                    prediction = 0.0
                elif kind == "seasonal":
                    # For a 3-month forecast from origin t, the comparable
                    # same-season interval last year is (t-12, t-9].
                    # Its 3-month change is therefore stored at t-9,
                    # i.e. position - (12 - horizon), not position - 12.
                    seasonal_change_column = f"target_log_change_{horizon}m"
                    seasonal_position = position - (12 - horizon)
                    prediction = float(
                        usable.iloc[seasonal_position][seasonal_change_column]
                    )
                else:
                    prediction = float(row.get("target_log_change_3m", 0.0))
                actual = float(row["_target"])
                origin = usable.index[position]
                scored.append({
                    "forecast_origin": origin.strftime("%Y-%m"),
                    "target_period": (origin + pd.DateOffset(months=horizon)).strftime("%Y-%m"),
                    "actual_change_pct": _pct_from_log_change(actual),
                    "predicted_change_pct": _pct_from_log_change(prediction),
                })
                actuals.append(actual)
                predictions.append(prediction)
        else:
            scored, actuals, predictions = _rolling_predictions(prepared, columns, kind)
        if not actuals:
            continue
        metrics = _score(np.asarray(actuals), np.asarray(predictions))
        comparisons.append({"id": model_id, "label": label, "family": kind, **metrics})
        all_backtests[model_id] = scored

    latest = prepared.frame.index[-1]
    latest_value = float(prepared.frame[TARGET_COLUMN].iloc[-1])
    future_period = latest + pd.DateOffset(months=horizon)
    next_forecasts: list[dict[str, Any]] = []
    last_feature_row = prepared.features.iloc[[-1]]
    for model_id, label, columns, kind in model_specs:
        if kind == "constant":
            estimate = 0.0
        elif kind == "momentum":
            estimate = float(last_feature_row["target_log_change_3m"].fillna(0).iloc[0])
        elif kind == "seasonal":
            # Match the upcoming 3-month interval to the corresponding
            # 3-month interval one year earlier. With a 3-month horizon,
            # that historical change ends 9 months before the latest month.
            seasonal_change_column = f"target_log_change_{horizon}m"
            seasonal_position_from_end = -(13 - horizon)
            estimate = float(
                prepared.features[seasonal_change_column].iloc[seasonal_position_from_end]
            )
        else:
            train = usable
            model = _model_pipeline(kind)
            model.fit(train[columns], train["_target"])
            estimate = float(model.predict(last_feature_row[columns])[0])
        next_forecasts.append({
            "id": model_id,
            "label": label,
            "predicted_change_pct": _pct_from_log_change(estimate),
            "implied_value_usd": max(0.0, float(np.expm1(np.log1p(latest_value) + estimate))),
        })

    return {
        "model_version": "benchmark-v1",
        "model_configuration": {
            "horizon_months": horizon,
            "max_backtest_origins": 36,
            "forest_estimators": 60,
            "minimum_training_rows": 48,
            "external_feature_lag_months": 1,
            "target_only_features": prepared.target_only_features,
            "cross_domain_features": prepared.cross_domain_features,
            "random_seed": 17,
        },
        "target_name": target_name,
        "target_series": target_series,
        "horizon_months": horizon,
        "last_observed_period": latest.strftime("%Y-%m"),
        "forecast_target_period": future_period.strftime("%Y-%m"),
        "observations": int(len(prepared.frame)),
        "comparison_window": len(next(iter(all_backtests.values()), [])),
        "external_features_used": prepared.cross_domain_features,
        "metrics_note": "Errors are measured in percentage points of three-month trade-value change. Lower MAE/RMSE is better; directional accuracy is secondary.",
        "models": sorted(comparisons, key=lambda item: item["mae_percentage_points"]),
        "forecasts": next_forecasts,
        "backtests": all_backtests,
        "regimes": _discover_regimes(prepared),
        "caveats": [
            "A better score on this historical window does not guarantee future superiority.",
            "Monthly trade values can be revised; use release/vintage dates where available.",
            "Cross-domain features use a conservative one-month lag; this does not replace true point-in-time release vintages.",
            "The policy signal is an association feature, not proof that policy caused a trade change.",
            "Three-month forecast rows are provisional until their target-period outcomes are observed.",
        ],
    }
