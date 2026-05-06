"""Swing H4-D1: real yield trend + COT positioning + breakout/pullback.
Best for: 2-7 day holds. Strongest signal of the 3 styles when conditions align."""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from config.settings import SWING, THRESHOLDS
from strategies.base import Signal, Side, Style, StrategyContext, calc_rr


def generate(ctx: StrategyContext) -> Signal:
    df = ctx.df_primary
    if df is None or len(df) < 200:
        return Signal(Style.SWING.value, Side.FLAT.value, 0, 0, 0, 0, 0, 0, ["insufficient data"])

    last = df.iloc[-1]
    atr_v = float(last.get("atr14", df["close"].iloc[-1] * 0.005))
    df_close = float(last["close"])
    # Real-time SPOT for entry/SL/TP base (see runner.py spot_for_entry).
    close = float(ctx.spot_price) if ctx.spot_price else df_close

    reasons_long: list[str] = []
    reasons_short: list[str] = []
    risks: list[str] = []

    # 1. EMA200 — major trend
    e50, e200 = last.get("ema50"), last.get("ema200")
    if pd.notna(e50) and pd.notna(e200):
        if close > e200 and e50 > e200:
            reasons_long.append("Above EMA200 + EMA50>EMA200 (major bull trend)")
        elif close < e200 and e50 < e200:
            reasons_short.append("Below EMA200 + EMA50<EMA200 (major bear trend)")

    # 2. Daily HTF alignment
    if ctx.df_htf is not None and len(ctx.df_htf) >= 50:
        htf = ctx.df_htf.iloc[-1]
        htf_close = float(htf["close"])
        htf_e50 = htf.get("ema50", htf_close)
        htf_e200 = htf.get("ema200", htf_close)
        if htf_close > htf_e50 > htf_e200:
            reasons_long.append("Daily: aligned bullish")
        elif htf_close < htf_e50 < htf_e200:
            reasons_short.append("Daily: aligned bearish")
        else:
            risks.append("Daily HTF mixed — swing edge weakened")

    # 3. ADX strong trend
    adx_v = last.get("adx", 0)
    if pd.notna(adx_v) and adx_v > 30:
        plus_di, minus_di = last.get("plus_di", 0), last.get("minus_di", 0)
        if plus_di > minus_di:
            reasons_long.append(f"H4 ADX={adx_v:.1f} STRONG bull trend")
        else:
            reasons_short.append(f"H4 ADX={adx_v:.1f} STRONG bear trend")

    # 4. Breakout of 20-bar range
    h20 = df["high"].rolling(20).max().iloc[-2]
    l20 = df["low"].rolling(20).min().iloc[-2]
    if pd.notna(h20) and close > h20:
        reasons_long.append("Breakout above 20-bar high")
    if pd.notna(l20) and close < l20:
        reasons_short.append("Breakdown below 20-bar low")

    # 5. SMC structure
    if last.get("bos_up", False):
        reasons_long.append("BOS up (HTF structure broken)")
    if last.get("bos_dn", False):
        reasons_short.append("BOS down (HTF structure broken)")

    # 6. Intermarket — heavy weight for swing
    inter_score = ctx.intermarket.get("score", 0.0)
    if inter_score > 0.4:
        reasons_long.append(f"Intermarket strongly bullish ({inter_score:+.2f})")
    elif inter_score > 0.15:
        reasons_long.append(f"Intermarket bullish ({inter_score:+.2f})")
    elif inter_score < -0.4:
        reasons_short.append(f"Intermarket strongly bearish ({inter_score:+.2f})")
    elif inter_score < -0.15:
        reasons_short.append(f"Intermarket bearish ({inter_score:+.2f})")

    # 7. COT positioning — weekly. Critical for swing.
    cot = ctx.cot or {}
    z = cot.get("z")
    if z is not None:
        if z > 1.5:
            reasons_short.append(f"COT MM extreme long z={z:+.2f} (swing mean-revert short)")
        elif z < -1.5:
            reasons_long.append(f"COT MM extreme short z={z:+.2f} (swing mean-revert long)")
        elif z > 0.8:
            risks.append(f"COT MM crowded long z={z:+.2f} (caution on long)")
        elif z < -0.8:
            risks.append(f"COT MM crowded short z={z:+.2f} (caution on short)")

    # 8. Regime
    if ctx.regime in ("trending_up", "trending_dn"):
        if reasons_long and ctx.regime == "trending_up":
            reasons_long.append("regime TRENDING_UP — swing optimal")
        if reasons_short and ctx.regime == "trending_dn":
            reasons_short.append("regime TRENDING_DN — swing optimal")
    if ctx.regime == "volatile":
        risks.append("regime VOLATILE — swing wider stops needed")

    # === Decision ===
    if ctx.in_news_blackout and THRESHOLDS.veto_on_news_blackout:
        # Swing nggak terlalu kena news short-term, tapi kita tetap reduce confidence
        risks.append(f"high-impact event nearby — {ctx.news_event.title if ctx.news_event else ''}")

    long_count = len(reasons_long)
    short_count = len(reasons_short)

    if long_count >= 4 and long_count > short_count:
        side = Side.LONG.value
        confluence = long_count
        reasons = reasons_long
    elif short_count >= 4 and short_count > long_count:
        side = Side.SHORT.value
        confluence = short_count
        reasons = reasons_short
    else:
        return _flat(close, ctx, [f"swing: confluence L={long_count}/S={short_count} <4"], risks)

    if side == Side.LONG.value:
        entry = close
        sl = close - SWING.sl_atr_mult * atr_v
        tp1 = close + SWING.tp1_atr_mult * atr_v
        tp2 = close + SWING.tp2_atr_mult * atr_v
        tp3 = close + SWING.tp3_atr_mult * atr_v
    else:
        entry = close
        sl = close + SWING.sl_atr_mult * atr_v
        tp1 = close - SWING.tp1_atr_mult * atr_v
        tp2 = close - SWING.tp2_atr_mult * atr_v
        tp3 = close - SWING.tp3_atr_mult * atr_v

    base_conf = min(0.55 + 0.06 * confluence, 0.95)
    conf = max(0.0, base_conf - 0.04 * len(risks))

    return Signal(
        style=Style.SWING.value, side=side,
        entry=round(entry, 2), sl=round(sl, 2),
        tp1=round(tp1, 2), tp2=round(tp2, 2), tp3=round(tp3, 2),
        confidence=round(conf, 3),
        confluence_count=confluence,
        reasons=reasons, risks=risks,
        regime=ctx.regime, session=ctx.session,
        timestamp=datetime.now(timezone.utc).isoformat(),
        rr_to_tp1=round(calc_rr(entry, sl, tp1, side), 2),
        rr_to_tp2=round(calc_rr(entry, sl, tp2, side), 2),
    )


def _flat(close: float, ctx: StrategyContext, reasons: list[str], risks: list[str]) -> Signal:
    return Signal(
        style=Style.SWING.value, side=Side.FLAT.value,
        entry=close, sl=close, tp1=close, tp2=close, tp3=close,
        confidence=0.0, confluence_count=0,
        reasons=reasons, risks=risks,
        regime=ctx.regime, session=ctx.session,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
