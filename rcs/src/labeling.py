"""Triple barrier labeling (López de Prado, Advances in Financial ML).

For each candle i:
    - Set entry = close[i]
    - upper barrier (TP) = entry + k_tp × ATR
    - lower barrier (SL) = entry - k_sl × ATR
    - vertical barrier = max_hold_candles ahead
    Label = barrier yang ke-hit pertama:
        +1 → TP hit (LONG good)
        -1 → SL hit (LONG bad)
         0 → time expired (no clear edge)

For SHORT perspective, simply flip sign of label later (multiclass training does
this automatically when feeding raw OHLC + features).

Critical: NO LOOKAHEAD bias. Label uses future data (candles i+1 onwards) only
for OUTCOME determination, not for feature computation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def triple_barrier_labels(
    df: pd.DataFrame,
    k_tp: float,
    k_sl: float,
    max_hold: int,
    atr_col: str = "atr14",
) -> np.ndarray:
    """Compute triple-barrier labels.

    Args:
        df: DataFrame with columns 'high', 'low', 'close' + atr_col (default 'atr14')
        k_tp: TP multiplier × ATR
        k_sl: SL multiplier × ATR (positive number; we negate internally)
        max_hold: max candles to look ahead (vertical barrier)
        atr_col: column name for ATR values

    Returns:
        np.ndarray of int labels in {-1, 0, +1}, same length as df.
        Last `max_hold` rows are zeros (insufficient lookahead window).
    """
    if not all(c in df.columns for c in ("high", "low", "close", atr_col)):
        raise ValueError(f"df missing required columns: high/low/close/{atr_col}")

    n = len(df)
    labels = np.zeros(n, dtype=int)

    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    atr   = df[atr_col].values

    for i in range(n - max_hold):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = close[i]
        tp = entry + k_tp * a
        sl = entry - k_sl * a

        # Look forward up to max_hold candles
        end = min(i + 1 + max_hold, n)
        hit_label = 0
        for j in range(i + 1, end):
            if high[j] >= tp:
                hit_label = 1
                break
            if low[j] <= sl:
                hit_label = -1
                break
        labels[i] = hit_label

    return labels


def label_distribution(labels: np.ndarray) -> dict:
    """Sanity check: count of each class.
    Realistic distributions for XAU triple barrier:
        +1 (TP hit): 18-25%
        -1 (SL hit): 18-25%
         0 (expired): 50-65%
    Significantly skewed (e.g. >40% of one class) suggests labeling bug.
    """
    total = len(labels)
    if total == 0:
        return {"total": 0}
    longs   = int((labels ==  1).sum())
    shorts  = int((labels == -1).sum())
    flat    = int((labels ==  0).sum())
    return {
        "total":      total,
        "long_n":     longs,    "long_pct":    round(longs  / total * 100, 1),
        "short_n":    shorts,   "short_pct":   round(shorts / total * 100, 1),
        "flat_n":     flat,     "flat_pct":    round(flat   / total * 100, 1),
        "warning":    "skew detected" if max(longs, shorts) / total > 0.40 else "",
    }


# ─── Smoke test ─────────────────────────────────────────────────────────────────

def _smoke():
    import pandas as pd
    import numpy as np

    np.random.seed(42)
    n = 1000
    close = 4500 + np.cumsum(np.random.randn(n) * 5)
    df = pd.DataFrame({
        "close": close,
        "high":  close + np.random.rand(n) * 3,
        "low":   close - np.random.rand(n) * 3,
        "atr14": np.full(n, 5.0),
    })
    labels = triple_barrier_labels(df, k_tp=1.5, k_sl=1.0, max_hold=24)
    print(label_distribution(labels))


if __name__ == "__main__":
    _smoke()
