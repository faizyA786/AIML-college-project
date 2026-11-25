from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def synthetic_demo_rows(periods: int | None = None) -> list[dict[str, object]]:
    """Return deterministic fabricated observations for UI-only demonstration.

    These rows are synthetic and must never be treated as validated research
    observations or used to persist an approved forecast.
    """
    if periods is None:
        end = pd.Timestamp(date.today().replace(day=1)) - pd.DateOffset(months=2)
        periods = len(pd.date_range("2010-01-01", end=end, freq="MS"))
    elif isinstance(periods, bool) or not isinstance(periods, int) or periods < 1:
        raise ValueError("periods must be a positive integer")

    rng = np.random.default_rng(2026)
    dates = pd.date_range("2010-01-01", periods=periods, freq="MS")
    policy = np.zeros(periods, dtype=float)
    for index in (28, 64, 104, 149, 173):
        if index < periods:
            policy[index] = 1.0

    macro = 100 + np.cumsum(rng.normal(0.12, 0.7, periods))
    sector = 100 + np.cumsum(rng.normal(0.18, 1.5, periods))
    log_exports = (
        18.0
        + 0.002 * np.arange(periods)
        + 0.02 * np.sin(np.arange(periods) * 2 * np.pi / 12)
    )

    for i in range(1, periods):
        log_exports[i] = (
            log_exports[i - 1]
            + 0.12 * (log_exports[i - 1] - log_exports[max(0, i - 3)])
            + 0.001 * (macro[i] - macro[max(0, i - 1)])
            + 0.0008 * (sector[i] - sector[max(0, i - 1)])
            - 0.012 * policy[i]
            + rng.normal(0, 0.018)
        )

    value = np.maximum(np.expm1(log_exports), 0)
    return [
        {
            "period": period.strftime("%Y-%m"),
            "target_value_usd": float(value[i]),
            "policy_signal": float(policy[i]),
            "sector_ip_index": float(sector[i]),
            "economic_index": float(macro[i]),
            "source_version": "synthetic-demo-v1",
        }
        for i, period in enumerate(dates)
    ]
