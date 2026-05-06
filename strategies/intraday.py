"""Intraday M15-H1: trend + S/R + DXY confirmation.
Best regime: TRENDING (ADX>25). Worst: ranging/quiet."""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from config.settings import INTRADAY, THRESHOLDS
from strategies.base import Signal, Side, Style, StrategyContext, calc_rr


def generate(ctx: StrategyContext) -> Signal:
    df = ctx.df_primary
    if df is None or len(df) < 100:
        return Signal(Style.INTRADAY.value, Side.FLAT.value, 0, 0, 0, 0, 0, 0, ["insufficient data"])

    last = df.iloc[-1]
    prev = df.iloc[-2]
    atr_v = float(last.get("atr14", df["close"].iloc[-1] * 0.002))
    df_close = float(last["close"])
    # Real-time SPOT for entry/SL/TP base (see runner.py spot_for_entry).
    close = float(ctx.spot_price) if ctx.spot_price else df_close

    reasons_long: list[str] = []
    reasons_short: list[str] = []
    risks: list[str] = []

    # 1. EMA stack
    e21, e50, e200 = last.get("ema21"), last.get("ema50"), last.get("ema200")
    if pd.notna(e21) and pd.notna(e50) and pd.notna(e200):
        if close > e21 > e50 > e200:
            reasons_long.append("EMA stack bullish (close>21>50>200)")
        elif close < e21 < e50 < e200:
            reasons_short.append("EMA stack bearish (close<21<50<200)")
        elif e21 > e50:
            reasons_long.append("EMA21>EMA50 (mid-trend up)")
        elif e21 < e50:
            reasons_short.append("EMA21<EMA50 (mid-trend down)")

    # 2. MACD histogram momentum
    hist = last.get("hist")
    prev_hist = prev.get("hist")
    if pd.notna(hist) and pd.notna(prev_hist):
        if hist > 0 and hist > prev_hist:
            reasons_long.append("MACD hist rising (momentum accelerating up)")
        elif hist < 0 and hist < prev_hist:
            reasons_short.append("MACD hist falling (momentum accelerating down)")

    # 3. ADX trending
    adx_v = last.get("adx", 0)
    if pd.notna(adx_v):
        if adx_v > 25:
            plus_di, minus_di = last.get("plus_di", 0), last.get("minus_di", 0)
            if plus_di > minus_di:
                reasons_long.append(f"ADX={adx_v:.1f} trending +DI>-DI")
            else:
                reasons_short.append(f"ADX={adx_v:.1f} trending -DI>+DI")
        else:
            risks.append(f"ADX {adx_v:.1f} weak trend (intraday strategy needs >25)")

    # 4. Bollinger position
    pctb = last.get("bb_pctb")
    if pd.notna(pctb):
        if pctb > 0.95:
            risks.append("Price at upper BB — pullback risk")
        elif pctb < 0.05:
            risks.append("Price at lower BB — bounce risk")

    # 5. SMC: BOS direction
    if last.get("bos_up", False):
        reasons_long.append("SMC BOS up (structure broken bullish)")
    if last.get("bos_dn", False):
        reasons_short.append("SMC BOS down (structure broken bearish)")

    # 6. HTF (4h) trend
    if ctx.df_htf is not None and len(ctx.df_htf) >= 50:
        htf = ctx.df_htf.iloc[-1]
        if htf.get("ema21", 0) > htf.get("ema50", 0):
            reasons_long.append("HTF (4h) trend up — align")
        else:
            reasons_short.append("HTF (4h) trend down — align")

    # 7. Intermarket — STRONG weight for intraday
    inter_score = ctx.intermarket.get("score", 0.0)
    if inter_score > 0.3:
        reasons_long.append(f"intermarket strongly bullish ({inter_score:+.2f})")
    elif inter_score > 0.1:
        reasons_long.append(f"intermarket bullish ({inter_score:+.2f})")
    elif inter_score < -0.3:
        reasons_short.append(f"intermarket strongly bearish ({inter_score:+.2f})")
    elif inter_score < -0.1:
        reasons_short.append(f"intermarket bearish ({inter_score:+.2f})")

    # 8. COT positioning
    cot = ctx.cot or {}
    if cot.get("signal", 0) == 1:
        reasons_long.append(f"COT extreme short → mean revert long bias (z={cot.get('z',0):+.2f})")
    elif cot.get("signal", 0) == -1:
        reasons_short.append(f"COT extreme long → mean revert short bias (z={cot.get('z',0):+.2f})")

    # 9. Regime
    if ctx.regime == "ranging":
        risks.append("regime RANGING — intraday trend strategy weak")
    if ctx.regime in ("trending_up", "trending_dn"):
        if reasons_long and ctx.regime == "trending_up":
            reasons_long.append("regime TRENDING_UP — intraday sweet spot")
        if reasons_short and ctx.regime == "trending_dn":
            reasons_short.append("regime TRENDING_DN — intraday sweet spot")

    # === Decision ===
    if ctx.in_news_blackout and THRESHOLDS.veto_on_news_blackout:
        risks.append(f"NEWS BLACKOUT — {ctx.news_event.title if ctx.news_event else ''}")
        return _flat(close, ctx, ["intraday vetoed: news blackout"], risks)

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
        return _flat(close, ctx, [f"intraday: confluence L={long_count}/S={short_count} <4"], risks)

    if side == Side.LONG.value:
        entry = close
        sl = close - INTRADAY.sl_atr_mult * atr_v
        tp1 = close + INTRADAY.tp1_atr_mult * atr_v
        tp2 = close + INTRADAY.tp2_atr_mult * atr_v
        tp3 = close + INTRADAY.tp3_atr_mult * atr_v
    else:
        entry = close
        sl = close + INTRADAY.sl_atr_mult * atr_v
        tp1 = close - INTRADAY.tp1_atr_mult * atr_v
        tp2 = close - INTRADAY.tp2_atr_mult * atr_v
        tp3 = close - INTRADAY.tp3_atr_mult * atr_v

    base_conf = min(0.55 + 0.06 * confluence, 0.95)
    conf = max(0.0, base_conf - 0.04 * len(risks))

    return Signal(
        style=Style.INTRADAY.value,
        side=side,
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
        style=Style.INTRADAY.value, side=Side.FLAT.value,
        entry=close, sl=close, tp1=close, tp2=close, tp3=close,
        confidence=0.0, confluence_count=0,
        reasons=reasons, risks=risks,
        regime=ctx.regime, session=ctx.session,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
