"""Smart Money Concepts (ICT-style): liquidity sweeps, FVG (Fair Value Gap), Order Blocks.
Versi simplified-but-correct — institusional traders cari struktur ini."""
from __future__ import annotations
import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Mark fractal swing high/low (simple pivot)."""
    h, l = df["high"], df["low"]
    sh = (h == h.rolling(lookback * 2 + 1, center=True).max())
    sl = (l == l.rolling(lookback * 2 + 1, center=True).min())
    return pd.DataFrame({"swing_high": sh, "swing_low": sl})


def liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Detect saat harga ambil prior swing high/low lalu reverse (stop hunt).
    Bullish sweep: low break prior swing low tapi close above it (rejection).
    Bearish sweep: high break prior swing high tapi close below it.
    """
    sw = swing_points(df, lookback=5)
    prior_swing_high = df["high"].where(sw["swing_high"]).ffill().shift(1)
    prior_swing_low = df["low"].where(sw["swing_low"]).ffill().shift(1)

    bull_sweep = (df["low"] < prior_swing_low) & (df["close"] > prior_swing_low)
    bear_sweep = (df["high"] > prior_swing_high) & (df["close"] < prior_swing_high)

    return pd.DataFrame({
        "bull_sweep": bull_sweep.fillna(False),
        "bear_sweep": bear_sweep.fillna(False),
        "prior_sh": prior_swing_high,
        "prior_sl": prior_swing_low,
    })


def fair_value_gap(df: pd.DataFrame) -> pd.DataFrame:
    """3-candle FVG.
    Bullish FVG: low[i] > high[i-2]  (gap antara candle i-2 high dan i low).
    Bearish FVG: high[i] < low[i-2].
    Returns boolean series + gap top/bottom buat retest detection.
    """
    h, l = df["high"], df["low"]
    bull = l > h.shift(2)
    bear = h < l.shift(2)
    return pd.DataFrame({
        "fvg_bull": bull.fillna(False),
        "fvg_bear": bear.fillna(False),
        "fvg_bull_top": l.where(bull),
        "fvg_bull_bot": h.shift(2).where(bull),
        "fvg_bear_top": l.shift(2).where(bear),
        "fvg_bear_bot": h.where(bear),
    })


def order_blocks(df: pd.DataFrame, impulse_atr_mult: float = 1.5) -> pd.DataFrame:
    """Order Block = candle terakhir yg berlawanan arah sebelum impulse move.
    Detect: candle bearish diikuti impulse bullish (size > X*ATR) → bullish OB at that bearish candle.
    """
    from features.technical import atr
    a = atr(df, 14)
    body = df["close"] - df["open"]
    next_body = body.shift(-1)

    impulse_up = next_body > impulse_atr_mult * a
    impulse_dn = -next_body > impulse_atr_mult * a

    bull_ob = (body < 0) & impulse_up   # bearish candle followed by big bull
    bear_ob = (body > 0) & impulse_dn

    return pd.DataFrame({
        "bull_ob": bull_ob.fillna(False),
        "bear_ob": bear_ob.fillna(False),
        "bull_ob_top": df["high"].where(bull_ob),
        "bull_ob_bot": df["low"].where(bull_ob),
        "bear_ob_top": df["high"].where(bear_ob),
        "bear_ob_bot": df["low"].where(bear_ob),
    })


def break_of_structure(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """BOS: close break prior swing high/low. Indicates trend continuation."""
    sw = swing_points(df, lookback=5)
    prior_high = df["high"].where(sw["swing_high"]).ffill().shift(1)
    prior_low = df["low"].where(sw["swing_low"]).ffill().shift(1)
    bos_up = df["close"] > prior_high
    bos_dn = df["close"] < prior_low
    return pd.DataFrame({
        "bos_up": bos_up.fillna(False),
        "bos_dn": bos_dn.fillna(False),
    })


def add_all_smc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.join(swing_points(out))
    out = out.join(liquidity_sweep(out))
    out = out.join(fair_value_gap(out))
    out = out.join(order_blocks(out))
    out = out.join(break_of_structure(out))
    return out
