"""Scalper M5: liquidity sweep + FVG fill + session momentum.
Best regime: VOLATILE atau awal trend (not deep into trend, not quiet).
Best session: London open (07-09 UTC) atau NY open (13-15 UTC)."""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from config.settings import SCALPER, THRESHOLDS
from strategies.base import Signal, Side, Style, StrategyContext, calc_rr


def generate(ctx: StrategyContext) -> Signal:
    df = ctx.df_primary
    if df is None or len(df) < 50:
        return Signal(Style.SCALPER.value, Side.FLAT.value, 0, 0, 0, 0, 0, 0, ["insufficient data"])

    last = df.iloc[-1]
    prev = df.iloc[-2]
    atr_v = float(last.get("atr14", df["close"].iloc[-1] * 0.002))
    df_close = float(last["close"])
    # Use real-time SPOT (Twelve Data or estimated GC=F minus premium) for
    # entry/SL/TP base so levels match broker quote, not GC=F futures premium.
    # Indicators below still computed from df (GC=F bars) — patterns are
    # relative measures, valid regardless of price level.
    close = float(ctx.spot_price) if ctx.spot_price else df_close

    reasons_long: list[str] = []
    reasons_short: list[str] = []
    risks: list[str] = []

    # 1. SMC: liquidity sweep last 3 bars (yes/no)
    recent3 = df.tail(3)
    if recent3.get("bull_sweep", pd.Series([False])).any():
        reasons_long.append("SMC: bullish liquidity sweep (stop hunt below prior low)")
    if recent3.get("bear_sweep", pd.Series([False])).any():
        reasons_short.append("SMC: bearish liquidity sweep (stop hunt above prior high)")

    # 2. FVG presence last 5 bars
    recent5 = df.tail(5)
    if recent5.get("fvg_bull", pd.Series([False])).any():
        reasons_long.append("FVG bullish (institutional buy imbalance)")
    if recent5.get("fvg_bear", pd.Series([False])).any():
        reasons_short.append("FVG bearish (institutional sell imbalance)")

    # 3. EMA9 vs EMA21 momentum (M5)
    ema9, ema21 = last.get("ema9"), last.get("ema21")
    if pd.notna(ema9) and pd.notna(ema21):
        if ema9 > ema21 and prev.get("ema9", ema9) <= prev.get("ema21", ema21):
            reasons_long.append("EMA9 cross above EMA21 (momentum flip up)")
        elif ema9 < ema21 and prev.get("ema9", ema9) >= prev.get("ema21", ema21):
            reasons_short.append("EMA9 cross below EMA21 (momentum flip down)")
        elif ema9 > ema21:
            reasons_long.append("EMA9>EMA21 (bullish momentum)")
        else:
            reasons_short.append("EMA9<EMA21 (bearish momentum)")

    # 4. RSI: not overbought/oversold extremes
    rsi = float(last.get("rsi14", 50))
    if 35 < rsi < 65:
        pass
    elif rsi >= 70:
        risks.append(f"RSI {rsi:.1f} overbought — long entry risky")
    elif rsi <= 30:
        risks.append(f"RSI {rsi:.1f} oversold — short entry risky")

    # 5. HTF (1h) trend filter
    if ctx.df_htf is not None and len(ctx.df_htf) >= 50:
        htf = ctx.df_htf.iloc[-1]
        htf_trend = htf.get("ema21", 0) > htf.get("ema50", 0)
        if htf_trend:
            reasons_long.append("HTF (1h) trend up — align")
        else:
            reasons_short.append("HTF (1h) trend down — align")

    # 6. Session boost
    if ctx.session in ("london", "lon_ny_overlap", "ny"):
        if reasons_long:
            reasons_long.append(f"session: {ctx.session} (high vol — scalper edge)")
        if reasons_short:
            reasons_short.append(f"session: {ctx.session} (high vol — scalper edge)")
    elif ctx.session in ("asia", "off_hours"):
        risks.append(f"session: {ctx.session} (low vol — scalper edge weak)")

    # 7. Regime check
    if ctx.regime == "quiet":
        risks.append("regime QUIET — scalper not optimal")
    if ctx.regime == "volatile":
        if reasons_long:
            reasons_long.append("regime VOLATILE — scalper sweet spot")
        if reasons_short:
            reasons_short.append("regime VOLATILE — scalper sweet spot")

    # 8. Intermarket alignment
    inter_score = ctx.intermarket.get("score", 0.0)
    if inter_score > 0.2:
        reasons_long.append(f"intermarket bullish (score={inter_score:+.2f})")
    elif inter_score < -0.2:
        reasons_short.append(f"intermarket bearish (score={inter_score:+.2f})")

    # === Decision ===
    long_count = len(reasons_long)
    short_count = len(reasons_short)

    if ctx.in_news_blackout and THRESHOLDS.veto_on_news_blackout:
        risks.append(f"NEWS BLACKOUT — {ctx.news_event.title if ctx.news_event else ''}")
        return _flat(close, atr_v, ctx, ["scalper vetoed: news blackout"], risks)

    if long_count >= 3 and long_count > short_count:
        side = Side.LONG.value
        confluence = long_count
        reasons = reasons_long
    elif short_count >= 3 and short_count > long_count:
        side = Side.SHORT.value
        confluence = short_count
        reasons = reasons_short
    else:
        return _flat(close, atr_v, ctx, ["scalper: confluence < 3"], risks)

    # Entry / SL / TP
    if side == Side.LONG.value:
        entry = close
        sl = close - SCALPER.sl_atr_mult * atr_v
        tp1 = close + SCALPER.tp1_atr_mult * atr_v
        tp2 = close + SCALPER.tp2_atr_mult * atr_v
        tp3 = close + SCALPER.tp3_atr_mult * atr_v
    else:
        entry = close
        sl = close + SCALPER.sl_atr_mult * atr_v
        tp1 = close - SCALPER.tp1_atr_mult * atr_v
        tp2 = close - SCALPER.tp2_atr_mult * atr_v
        tp3 = close - SCALPER.tp3_atr_mult * atr_v

    # Confidence: confluence-based + penalize risks
    base_conf = min(0.5 + 0.08 * confluence, 0.95)
    conf = max(0.0, base_conf - 0.05 * len(risks))

    return Signal(
        style=Style.SCALPER.value,
        side=side,
        entry=round(entry, 2),
        sl=round(sl, 2),
        tp1=round(tp1, 2),
        tp2=round(tp2, 2),
        tp3=round(tp3, 2),
        confidence=round(conf, 3),
        confluence_count=confluence,
        reasons=reasons,
        risks=risks,
        regime=ctx.regime,
        session=ctx.session,
        timestamp=datetime.now(timezone.utc).isoformat(),
        rr_to_tp1=round(calc_rr(entry, sl, tp1, side), 2),
        rr_to_tp2=round(calc_rr(entry, sl, tp2, side), 2),
    )


def _flat(close: float, atr_v: float, ctx: StrategyContext, reasons: list[str], risks: list[str]) -> Signal:
    return Signal(
        style=Style.SCALPER.value,
        side=Side.FLAT.value,
        entry=close, sl=close, tp1=close, tp2=close, tp3=close,
        confidence=0.0, confluence_count=0,
        reasons=reasons, risks=risks,
        regime=ctx.regime, session=ctx.session,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
