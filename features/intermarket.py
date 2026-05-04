"""Intermarket: XAU vs DXY, US10Y, real yields (TIPS proxy), VIX, SPX.
XAU drivers (urutan importance):
1. US Real yields (TIPS, inverse) — corr ~ -0.85
2. DXY — corr -0.7 to -0.9
3. VIX (risk-off boost) — variable
4. SPX (risk-on diluter) — mild
"""
from __future__ import annotations
from typing import Dict, Optional
import numpy as np
import pandas as pd


def align_close(bundle: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine close prices into single DF aligned by time."""
    out = pd.DataFrame()
    for k, df in bundle.items():
        if df is None or df.empty:
            continue
        s = df["close"].rename(k)
        if out.empty:
            out = s.to_frame()
        else:
            out = out.join(s, how="outer")
    return out.ffill().dropna(how="all")


def rolling_corr(df: pd.DataFrame, base: str, others: list[str], window: int = 50) -> pd.DataFrame:
    """Rolling correlation of base vs each `others`."""
    base_ret = df[base].pct_change()
    out = pd.DataFrame(index=df.index)
    for o in others:
        if o not in df.columns:
            continue
        o_ret = df[o].pct_change()
        out[f"corr_{base}_{o}"] = base_ret.rolling(window, min_periods=window // 2).corr(o_ret)
    return out


def intermarket_score(bundle: Dict[str, pd.DataFrame]) -> dict:
    """Score arah XAU based on intermarket signals.
    Returns dict dengan score (-1..+1) dan reasoning per komponen.
    Pos score = bullish XAU, neg = bearish.
    """
    closes = align_close(bundle)
    if closes.empty or "xau" not in closes.columns:
        return {"score": 0.0, "components": {}, "note": "data unavailable"}

    components = {}

    # 1. DXY momentum (last 5 bars) → inverse for XAU
    if "dxy" in closes.columns:
        dxy_chg = closes["dxy"].pct_change(5).iloc[-1]
        if pd.notna(dxy_chg):
            components["dxy"] = {
                "value": float(dxy_chg),
                "score": float(-np.tanh(dxy_chg * 100)),  # -1..+1
                "note": f"DXY 5-bar Δ {dxy_chg*100:+.2f}%",
            }

    # 2. US 10Y yield momentum → inverse for XAU
    if "us10y" in closes.columns:
        y_chg = closes["us10y"].pct_change(5).iloc[-1]
        if pd.notna(y_chg):
            components["us10y"] = {
                "value": float(y_chg),
                "score": float(-np.tanh(y_chg * 50)),
                "note": f"US10Y 5-bar Δ {y_chg*100:+.2f}%",
            }

    # 3. VIX spike → bullish XAU (risk-off)
    if "vix" in closes.columns:
        v = closes["vix"].iloc[-1]
        v_chg = closes["vix"].pct_change(5).iloc[-1]
        if pd.notna(v_chg):
            components["vix"] = {
                "value": float(v),
                "score": float(np.tanh(v_chg * 5)),
                "note": f"VIX={v:.1f}, 5-bar Δ {v_chg*100:+.2f}%",
            }

    # 4. SPX → mild inverse (risk-on diluter)
    if "spx" in closes.columns:
        spx_chg = closes["spx"].pct_change(5).iloc[-1]
        if pd.notna(spx_chg):
            components["spx"] = {
                "value": float(spx_chg),
                "score": float(-np.tanh(spx_chg * 30) * 0.3),  # mild weight
                "note": f"SPX 5-bar Δ {spx_chg*100:+.2f}%",
            }

    # 5. Gold/Silver ratio — extreme = warning
    if "silver" in closes.columns and "xau" in closes.columns:
        ratio = closes["xau"] / closes["silver"]
        z = (ratio.iloc[-1] - ratio.tail(100).mean()) / ratio.tail(100).std()
        if pd.notna(z):
            components["gold_silver"] = {
                "value": float(ratio.iloc[-1]),
                "score": float(-np.tanh(z) * 0.2),
                "note": f"G/S ratio z={z:+.2f} (extreme reversion bias)",
            }

    if not components:
        return {"score": 0.0, "components": {}, "note": "no intermarket data"}

    weights = {"dxy": 0.30, "us10y": 0.30, "vix": 0.20, "spx": 0.10, "gold_silver": 0.10}
    weighted = sum(c["score"] * weights.get(name, 0.1) for name, c in components.items())
    total_w = sum(weights.get(name, 0.1) for name in components)
    score = weighted / total_w if total_w else 0.0

    return {
        "score": float(np.clip(score, -1, 1)),
        "components": components,
        "note": "weighted intermarket bias for XAU",
    }
