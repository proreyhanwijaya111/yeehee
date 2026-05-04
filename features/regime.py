"""Regime detection: trending / ranging / volatile / quiet.
Strategy MUST match regime. Salah regime = pasti loss."""
from __future__ import annotations
from enum import Enum
import numpy as np
import pandas as pd

from features.technical import adx, atr, bollinger


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DN = "trending_dn"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"


def hurst_exponent(series: pd.Series, max_lag: int = 50) -> float:
    """Hurst H: <0.5 mean-reverting, ~0.5 random walk, >0.5 trending."""
    s = series.dropna().values
    if len(s) < max_lag * 2:
        return 0.5
    lags = range(2, max_lag)
    tau = []
    for lag in lags:
        diff = s[lag:] - s[:-lag]
        if len(diff) > 0 and np.std(diff) > 0:
            tau.append(np.sqrt(np.std(diff)))
    if len(tau) < 2:
        return 0.5
    poly = np.polyfit(np.log(list(lags)[:len(tau)]), np.log(tau), 1)
    return float(poly[0] * 2.0)


def detect_regime(df: pd.DataFrame, atr_lookback: int = 100) -> pd.DataFrame:
    """Per-bar regime label + confidence."""
    out = df.copy()
    a = atr(out, 14)
    adx_df = adx(out, 14)
    bb = bollinger(out["close"], 20, 2.0)

    atr_pct = a / out["close"]
    atr_pct_rank = atr_pct.rolling(atr_lookback, min_periods=20).rank(pct=True)
    bb_width_rank = bb["bb_width"].rolling(atr_lookback, min_periods=20).rank(pct=True)

    is_trending = adx_df["adx"] > 25
    is_strong_trend = adx_df["adx"] > 35
    is_volatile = atr_pct_rank > 0.85
    is_quiet = atr_pct_rank < 0.15
    trend_up = adx_df["plus_di"] > adx_df["minus_di"]

    regimes = []
    for i in range(len(out)):
        if pd.isna(adx_df["adx"].iloc[i]):
            regimes.append(Regime.RANGING.value)
            continue
        if is_volatile.iloc[i] and not is_strong_trend.iloc[i]:
            regimes.append(Regime.VOLATILE.value)
        elif is_quiet.iloc[i]:
            regimes.append(Regime.QUIET.value)
        elif is_trending.iloc[i]:
            regimes.append(Regime.TRENDING_UP.value if trend_up.iloc[i] else Regime.TRENDING_DN.value)
        else:
            regimes.append(Regime.RANGING.value)

    out["regime"] = regimes
    out["adx"] = adx_df["adx"]
    out["atr_pct_rank"] = atr_pct_rank
    out["bb_width_rank"] = bb_width_rank
    return out


def current_regime(df: pd.DataFrame) -> dict:
    r = detect_regime(df).iloc[-1]
    return {
        "regime": r["regime"],
        "adx": float(r["adx"]) if pd.notna(r["adx"]) else None,
        "atr_pct_rank": float(r["atr_pct_rank"]) if pd.notna(r["atr_pct_rank"]) else None,
    }
