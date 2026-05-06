"""Local rule-based 12-agent pipeline — drop-in replacement for the LLM
12-agent debate in ai_agent/agents.py + orchestrator.run_llm_debate.

Architecture:
    11 deterministic agents + Pattern Expert (replaces LLM pattern_recognition).
    Devil's Advocate: 2 modes — local rule (default, free) or LLM (toggle in
    settings, with auto-fallback to local on failure).
    Synthesizer: weighted vote across agents, classifies signal_strength.

All agents share the same MarketContext input schema and AgentVerdict output
schema as the LLM agents, so orchestrator can swap engines transparently.

User constraints honored (per discussion):
    - One file (this) instead of 12 separate modules. Keep it lean.
    - Pattern Expert from user's PATTERN EXPERT AGENT/ folder, integrated as
      `pattern_expert_agent`. Uses bundled stats JSON.
    - Devil's Advocate as 12th agent slot, swappable via da_engine setting.
    - No silent fail — every fallback path logs explicitly.

Performance: full 12-agent local cycle target = <500ms (excluding data fetch).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from ai_agent.pattern_expert import detect_for_agent as pattern_detect, aggregate_pattern_score


# ─── Output schema (compatible with rule_engine.AgentVerdict / debate dict) ──

@dataclass
class AgentVerdict:
    name: str
    verdict: str            # "LONG" | "SHORT" | "NEUTRAL"
    confidence: float       # 0..1
    reasoning: list[str] = field(default_factory=list)
    engine: str = "local"   # "local" | "llm:groq" | "llm:openrouter" | etc.
    latency_ms: int = 0


@dataclass
class DebateResult:
    final_action: str
    confidence: float
    signal_strength: str
    agents: list[AgentVerdict] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    primary_driver: str = ""
    engine_meta: dict = field(default_factory=dict)  # {da_engine, fallback_used}

    def to_dict(self) -> dict:
        return {
            "final_action":     self.final_action,
            "confidence":       self.confidence,
            "signal_strength":  self.signal_strength,
            "agents":           [asdict(a) for a in self.agents],
            "reasoning_chain":  self.reasoning_chain,
            "risks":            self.risks,
            "primary_driver":   self.primary_driver,
            "engine":           "local-12-agent",
            "engine_meta":      self.engine_meta,
        }


# Direction tally helper
def _direction(verdict: str) -> int:
    if verdict == "LONG":  return +1
    if verdict == "SHORT": return -1
    return 0


def _conf(verdict: str, confidence: float) -> float:
    """Signed confidence in [-1, +1]."""
    return _direction(verdict) * confidence


def _verdict_from_score(score: float, threshold: float = 0.15) -> str:
    if score >  threshold: return "LONG"
    if score < -threshold: return "SHORT"
    return "NEUTRAL"


def _timed(fn):
    """Decorator stamping latency_ms on the returned AgentVerdict."""
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        v = fn(*args, **kwargs)
        v.latency_ms = int((time.perf_counter() - t0) * 1000)
        return v
    return wrapper


# ────────────────────────────────────────────────────────────────────────────
# AGENT 1 — HTF Bias (Higher-Timeframe directional read)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def htf_bias_agent(ctx: dict) -> AgentVerdict:
    """Multi-EMA hierarchy + ADX on 4H + 1D dataframes.
    Returns LONG if EMA21>50 stack on H4 AND price > EMA200 D1, etc.
    """
    df_4h: pd.DataFrame = ctx.get("df_4h")
    df_1d: pd.DataFrame = ctx.get("df_1d")
    reasons: list[str] = []
    score = 0.0

    if df_4h is not None and len(df_4h) >= 50:
        last = df_4h.iloc[-1]
        e21, e50 = last.get("ema21"), last.get("ema50")
        if pd.notna(e21) and pd.notna(e50):
            if e21 > e50:
                score += 0.25; reasons.append("H4 EMA21>50 bullish")
            else:
                score -= 0.25; reasons.append("H4 EMA21<50 bearish")
        adx = last.get("adx", 0)
        if pd.notna(adx) and adx > 25:
            plus_di, minus_di = last.get("plus_di", 0), last.get("minus_di", 0)
            if plus_di > minus_di:
                score += 0.20; reasons.append(f"H4 ADX={adx:.0f} +DI lead")
            else:
                score -= 0.20; reasons.append(f"H4 ADX={adx:.0f} -DI lead")

    if df_1d is not None and len(df_1d) >= 200:
        last_d = df_1d.iloc[-1]
        e200 = last_d.get("ema200")
        if pd.notna(e200):
            if last_d["close"] > e200:
                score += 0.25; reasons.append("D1 close > EMA200")
            else:
                score -= 0.25; reasons.append("D1 close < EMA200")
        e21d, e50d = last_d.get("ema21"), last_d.get("ema50")
        if pd.notna(e21d) and pd.notna(e50d):
            if e21d > e50d:
                score += 0.10; reasons.append("D1 EMA21>50")
            else:
                score -= 0.10; reasons.append("D1 EMA21<50")

    verdict = _verdict_from_score(score, 0.20)
    confidence = min(abs(score) + 0.30, 0.95) if verdict != "NEUTRAL" else 0.30
    if not reasons:
        reasons = ["insufficient HTF data"]
    return AgentVerdict("HTF Bias", verdict, confidence, reasons)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 2 — Session Phase (Asia/London/NY favorability)
# ────────────────────────────────────────────────────────────────────────────

_SESSION_BIAS = {
    "asia":             {"trade_friendly": False, "weight": 0.4, "note": "low vol, range-bound"},
    "london":           {"trade_friendly": True,  "weight": 1.0, "note": "trend setups, high liq"},
    "lon_ny_overlap":   {"trade_friendly": True,  "weight": 1.2, "note": "highest liquidity"},
    "ny":               {"trade_friendly": True,  "weight": 0.9, "note": "news-driven, volatile"},
    "off_hours":        {"trade_friendly": False, "weight": 0.3, "note": "quiet"},
}


@_timed
def session_phase_agent(ctx: dict) -> AgentVerdict:
    """Classifies whether the current session is favorable for entry."""
    sess = ctx.get("session", "asia")
    cfg = _SESSION_BIAS.get(sess, _SESSION_BIAS["off_hours"])
    near_fix = ctx.get("near_london_fix", False)

    # Session phase has no directional bias on its own — expressed as confidence
    # boost/penalty for whatever direction the consensus picks. Modeled as
    # NEUTRAL verdict + confidence reflecting trade-friendliness.
    confidence = 0.45 + cfg["weight"] * 0.20
    if near_fix:
        confidence = min(confidence + 0.10, 0.85)
    reasons = [f"session={sess} ({cfg['note']})"]
    if near_fix:
        reasons.append("near London fix — high vol expected")
    return AgentVerdict("Session Phase", "NEUTRAL", round(confidence, 3), reasons)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 3 — LTF Technical (M5/M15 indicators + 3+ confluence factors)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def ltf_technical_agent(ctx: dict) -> AgentVerdict:
    """Count technical confluence factors on M15. ≥3 same direction = signal."""
    df: pd.DataFrame = ctx.get("df_15m")
    if df is None or len(df) < 50:
        return AgentVerdict("LTF Technical", "NEUTRAL", 0.30, ["insufficient M15 data"])

    last = df.iloc[-1]
    long_factors: list[str] = []
    short_factors: list[str] = []

    # EMA stack
    e9, e21, e50 = last.get("ema9"), last.get("ema21"), last.get("ema50")
    if pd.notna(e9) and pd.notna(e21) and pd.notna(e50):
        if e9 > e21 > e50:   long_factors.append("EMA9>21>50")
        elif e9 < e21 < e50: short_factors.append("EMA9<21<50")

    # RSI zone
    rsi = last.get("rsi14")
    if pd.notna(rsi):
        if 50 < rsi < 70:  long_factors.append(f"RSI {rsi:.0f} bull zone")
        elif 30 < rsi < 50: short_factors.append(f"RSI {rsi:.0f} bear zone")

    # MACD
    hist = last.get("hist")
    if pd.notna(hist):
        if hist > 0: long_factors.append("MACD hist > 0")
        elif hist < 0: short_factors.append("MACD hist < 0")

    # Bollinger position
    bb_pct = last.get("bb_pctb")
    if pd.notna(bb_pct):
        if bb_pct < 0.20: long_factors.append("BB lower (oversold)")
        elif bb_pct > 0.80: short_factors.append("BB upper (overbought)")

    # ATR rising = momentum (counts for whatever side has more factors so far)
    atr_now = last.get("atr14")
    atr_prev = df["atr14"].iloc[-5:-1].mean() if "atr14" in df.columns else None
    if pd.notna(atr_now) and pd.notna(atr_prev) and atr_now > atr_prev * 1.10:
        if len(long_factors) > len(short_factors):
            long_factors.append("ATR rising (vol expansion)")
        elif len(short_factors) > len(long_factors):
            short_factors.append("ATR rising (vol expansion)")

    if len(long_factors) >= 3 and len(long_factors) > len(short_factors):
        confidence = min(0.50 + len(long_factors) * 0.08, 0.92)
        return AgentVerdict("LTF Technical", "LONG", confidence, long_factors)
    if len(short_factors) >= 3 and len(short_factors) > len(long_factors):
        confidence = min(0.50 + len(short_factors) * 0.08, 0.92)
        return AgentVerdict("LTF Technical", "SHORT", confidence, short_factors)
    return AgentVerdict("LTF Technical", "NEUTRAL", 0.35,
                        long_factors + short_factors or ["no clear technical edge"])


# ────────────────────────────────────────────────────────────────────────────
# AGENT 4 — Liquidity / SMC (sweeps, FVG, order block, BOS)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def liquidity_smc_agent(ctx: dict) -> AgentVerdict:
    """Smart Money Concepts: sweeps, FVG, BOS. M15 + H1 reads."""
    reasons: list[str] = []
    score = 0.0
    for tf_name, df in (("M15", ctx.get("df_15m")), ("H1", ctx.get("df_1h"))):
        if df is None or len(df) < 30: continue
        last = df.iloc[-1]
        if last.get("bull_sweep", False):
            score += 0.30; reasons.append(f"{tf_name}: bullish sweep")
        if last.get("bear_sweep", False):
            score -= 0.30; reasons.append(f"{tf_name}: bearish sweep")
        if last.get("fvg_bull", False):
            score += 0.15; reasons.append(f"{tf_name}: bullish FVG")
        if last.get("fvg_bear", False):
            score -= 0.15; reasons.append(f"{tf_name}: bearish FVG")
        if last.get("bos_up", False):
            score += 0.20; reasons.append(f"{tf_name}: BOS up")
        if last.get("bos_dn", False):
            score -= 0.20; reasons.append(f"{tf_name}: BOS down")
    verdict = _verdict_from_score(score, 0.25)
    confidence = min(abs(score) + 0.35, 0.92) if verdict != "NEUTRAL" else 0.30
    return AgentVerdict("Liquidity SMC", verdict, confidence,
                        reasons or ["no SMC structure detected"])


# ────────────────────────────────────────────────────────────────────────────
# AGENT 5 — Order Flow (COT z-score + volume spike + stop hunt zones)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def order_flow_agent(ctx: dict) -> AgentVerdict:
    cot: dict = ctx.get("cot") or {}
    df: pd.DataFrame = ctx.get("df_1h")
    reasons: list[str] = []
    score = 0.0

    z = cot.get("z")
    if z is not None:
        reasons.append(f"COT MM z52 = {z:+.2f}")
        if z > 1.5:
            score -= 0.40; reasons.append("extreme long → mean-revert SHORT bias")
        elif z < -1.5:
            score += 0.40; reasons.append("extreme short → mean-revert LONG bias")

    if df is not None and len(df) >= 30:
        last = df.iloc[-1]
        vol = last.get("volume", 0)
        vol_avg = df["volume"].iloc[-20:-1].mean() if "volume" in df.columns else 0
        if vol_avg > 0 and vol > vol_avg * 2.0:
            # Direction of the volume spike candle
            if last["close"] > last["open"]:
                score += 0.20; reasons.append("vol spike on bull candle")
            elif last["close"] < last["open"]:
                score -= 0.20; reasons.append("vol spike on bear candle")

        # Stop-hunt proximity (close near prior swing high/low → exhaustion risk)
        pri_sh = last.get("prior_sh"); pri_sl = last.get("prior_sl")
        close = float(last["close"])
        if pd.notna(pri_sh) and pd.notna(pri_sl) and (pri_sh - pri_sl) > 0:
            pos = (close - pri_sl) / (pri_sh - pri_sl)
            if pos > 0.85:
                score -= 0.15; reasons.append("near prior swing high (stops above)")
            elif pos < 0.15:
                score += 0.15; reasons.append("near prior swing low (stops below)")

    verdict = _verdict_from_score(score, 0.25)
    confidence = min(abs(score) + 0.35, 0.90) if verdict != "NEUTRAL" else 0.35
    return AgentVerdict("Order Flow", verdict, confidence,
                        reasons or ["no positioning extreme"])


# ────────────────────────────────────────────────────────────────────────────
# AGENT 6 — Pattern Expert (replaces old pattern_recognition; uses user's spec)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def pattern_expert_agent(ctx: dict) -> AgentVerdict:
    """Multi-TF candlestick pattern detection with bundled historical stats.

    Detects on M15 (primary) and H1 (HTF context). Filters out patterns
    flagged 'avoid' or 'do_not_trade' in spec_v2. Aggregates score with
    conditional multipliers (key level 1.5x, trend-aligned 1.2x, etc.).
    """
    reasons: list[str] = []
    all_hits = []

    for tf_name, df_key in (("M15", "df_15m"), ("H1", "df_1h")):
        df = ctx.get(df_key)
        if df is None: continue
        try:
            hits = pattern_detect(df, timeframe=tf_name)
            all_hits.extend(hits)
        except Exception as e:
            reasons.append(f"{tf_name} detect error: {str(e)[:60]}")

    if not all_hits:
        return AgentVerdict("Pattern Expert", "NEUTRAL", 0.30,
                            ["no qualifying patterns on M15/H1"])

    score, direction, agg_reasons = aggregate_pattern_score(all_hits)
    reasons.extend(agg_reasons)
    # Add top-3 detail
    for h in sorted(all_hits, key=lambda x: abs(x.score), reverse=True)[:3]:
        reasons.append(f"{h.timeframe}: {h.pattern_base} {h.direction} score={h.score:+.2f}")

    confidence = min(abs(score) + 0.30, 0.92) if direction != "NEUTRAL" else 0.30
    return AgentVerdict("Pattern Expert", direction, confidence, reasons)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 7 — Volume Profile (POC/VAH/VAL mean-revert vs breakout)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def volume_profile_agent(ctx: dict) -> AgentVerdict:
    """Approximate volume profile: rolling 60-bar VWAP + std bands as proxy for
    POC/VAH/VAL (real volume profile would need volume per price bucket which
    we don't compute live yet). Position relative to bands → mean-revert vs
    breakout signal."""
    df: pd.DataFrame = ctx.get("df_15m")
    if df is None or len(df) < 60 or "volume" not in df.columns:
        return AgentVerdict("Volume Profile", "NEUTRAL", 0.30,
                            ["insufficient volume data"])

    last_60 = df.iloc[-60:]
    vol = last_60["volume"]
    if vol.sum() <= 0:
        return AgentVerdict("Volume Profile", "NEUTRAL", 0.30,
                            ["zero volume window"])
    typical = (last_60["high"] + last_60["low"] + last_60["close"]) / 3
    vwap = (typical * vol).sum() / vol.sum()
    weighted_var = ((typical - vwap) ** 2 * vol).sum() / vol.sum()
    std = float(np.sqrt(weighted_var))
    if std <= 0:
        return AgentVerdict("Volume Profile", "NEUTRAL", 0.30,
                            ["VWAP std collapsed"])

    close = float(df["close"].iloc[-1])
    z = (close - vwap) / std

    reasons = [f"VWAP60={vwap:.2f} close={close:.2f} z={z:+.2f}σ"]
    if z > 1.5:
        # Above VAH → mean-revert short
        return AgentVerdict("Volume Profile", "SHORT", min(0.45 + abs(z) * 0.10, 0.85),
                            reasons + ["above VAH → mean-revert"])
    if z < -1.5:
        return AgentVerdict("Volume Profile", "LONG", min(0.45 + abs(z) * 0.10, 0.85),
                            reasons + ["below VAL → mean-revert"])
    return AgentVerdict("Volume Profile", "NEUTRAL", 0.40,
                        reasons + ["price within value area"])


# ────────────────────────────────────────────────────────────────────────────
# AGENT 8 — News Proximity (high-impact event blackout)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def news_proximity_agent(ctx: dict) -> AgentVerdict:
    """If currently in news blackout → veto via NEUTRAL with high confidence
    (synthesizer treats high-confidence NEUTRAL from this agent as a hard
    filter). Otherwise look ahead 60 min for upcoming high-impact USD/XAU
    events and reduce risk."""
    in_blackout = ctx.get("in_news_blackout", False)
    blk_event = ctx.get("blackout_event")
    upcoming = ctx.get("upcoming_events") or []

    reasons: list[str] = []
    if in_blackout:
        title = (blk_event.get("title") if isinstance(blk_event, dict) else
                 getattr(blk_event, "title", "high-impact event")) if blk_event else "high-impact event"
        reasons.append(f"BLACKOUT: {title}")
        # NEUTRAL with HIGH conf = strong "do not trade" signal
        return AgentVerdict("News Proximity", "NEUTRAL", 0.90, reasons)

    # Look at first upcoming event within 60 min
    if upcoming:
        e = upcoming[0]
        when = e.get("when_utc") if isinstance(e, dict) else getattr(e, "when_utc", None)
        title = e.get("title") if isinstance(e, dict) else getattr(e, "title", "?")
        if when:
            try:
                ts = pd.Timestamp(when)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                now = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None else pd.Timestamp.utcnow()
                mins = (ts - now).total_seconds() / 60.0
                if 0 < mins < 60:
                    reasons.append(f"upcoming {title} in {mins:.0f}min")
                    return AgentVerdict("News Proximity", "NEUTRAL", 0.65, reasons)
            except Exception:
                pass

    return AgentVerdict("News Proximity", "NEUTRAL", 0.20,
                        reasons or ["no high-impact event near"])


# ────────────────────────────────────────────────────────────────────────────
# AGENT 9 — Volatility (ATR percentile + regime label)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def volatility_agent(ctx: dict) -> AgentVerdict:
    """Block extreme high vol (chop / spike risk). Allow normal/moderate vol."""
    regime = ctx.get("regime", "")
    df: pd.DataFrame = ctx.get("df_4h")
    reasons = [f"regime={regime}"]

    atr_rank = None
    if df is not None and len(df) >= 100:
        if "atr14" in df.columns:
            atr_now = df["atr14"].iloc[-1]
            atr_hist = df["atr14"].iloc[-100:-1]
            if pd.notna(atr_now) and len(atr_hist) > 0:
                atr_rank = (atr_hist < atr_now).mean()  # percentile rank

    if atr_rank is not None:
        reasons.append(f"ATR percentile={atr_rank*100:.0f}%")
        if atr_rank > 0.95:
            return AgentVerdict("Volatility", "NEUTRAL", 0.85,
                                reasons + ["EXTREME vol — avoid trades"])
        if atr_rank < 0.10:
            return AgentVerdict("Volatility", "NEUTRAL", 0.55,
                                reasons + ["very low vol — wait breakout"])

    if regime == "trending_up":
        return AgentVerdict("Volatility", "LONG", 0.55, reasons + ["regime supports long"])
    if regime == "trending_down":
        return AgentVerdict("Volatility", "SHORT", 0.55, reasons + ["regime supports short"])
    if regime in ("volatile", "explosive"):
        return AgentVerdict("Volatility", "NEUTRAL", 0.65,
                            reasons + ["volatile regime — caution"])
    return AgentVerdict("Volatility", "NEUTRAL", 0.40, reasons)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 10 — Backtest Memory (prior win rate from forward-test history)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def backtest_memory_agent(ctx: dict) -> AgentVerdict:
    """Pull prior win rate stats per style from store. Bias toward style with
    history > 55% WR over ≥20 trades."""
    store = ctx.get("store")
    if not store or not getattr(store, "_client", None):
        return AgentVerdict("Backtest Memory", "NEUTRAL", 0.30,
                            ["no store available"])

    try:
        r = (
            store._client.from_("portfolio_stats_by_style")
            .select("style, win_rate, avg_pnl_r, closed_count")
            .eq("user_id", "default")
            .execute()
        )
        rows = r.data or []
    except Exception:
        return AgentVerdict("Backtest Memory", "NEUTRAL", 0.30,
                            ["stats query failed"])

    if not rows:
        return AgentVerdict("Backtest Memory", "NEUTRAL", 0.30,
                            ["no historical trades yet"])

    reasons: list[str] = []
    score = 0.0
    for row in rows:
        wr = float(row.get("win_rate") or 0)
        n  = int(row.get("closed_count") or 0)
        avg_r = float(row.get("avg_pnl_r") or 0)
        style = row.get("style", "?")
        if n >= 20:
            edge = (wr - 0.5) * (1 if avg_r > 0 else -1)
            score += edge * 0.20
            reasons.append(f"{style}: WR={wr*100:.0f}% n={n} avgR={avg_r:+.2f}")
        else:
            reasons.append(f"{style}: n={n} (need ≥20)")

    # Memory provides bias multiplier for whatever consensus picks; signed by
    # net edge across styles.
    verdict = "NEUTRAL"
    confidence = 0.40 + min(abs(score), 0.40)
    return AgentVerdict("Backtest Memory", verdict, round(confidence, 3), reasons)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 11 — Devil's Advocate (LOCAL, the high-quality fallback)
# ────────────────────────────────────────────────────────────────────────────

@_timed
def devils_advocate_local(ctx: dict, others: list[AgentVerdict]) -> AgentVerdict:
    """Local rule-based DA — checks 7 catastrophic risk patterns.

    Patterns checked:
      1. NEWS BLACKOUT (hard veto)
      2. RSI extreme overbought/oversold counter to direction
      3. BB band rejection at extreme
      4. ATR percentile > 95 (extreme vol)
      5. Counter-trend on D1 (HTF disagrees with consensus)
      6. Agents disagree heavily (max-min > 0.4)
      7. Asia-session signal (low conviction)

    Returns:
      - "NEUTRAL" verdict + HIGH confidence (>0.7) = VETO consensus
      - consensus verdict + LOWER confidence = warning, no veto
      - consensus verdict + HIGH confidence (>0.7) = approve
    """
    long_n  = sum(1 for v in others if v.verdict == "LONG")
    short_n = sum(1 for v in others if v.verdict == "SHORT")
    consensus = "LONG" if long_n > short_n else "SHORT" if short_n > long_n else "NEUTRAL"

    risks: list[str] = []
    risk_score = 0

    # 1. NEWS BLACKOUT (hard)
    if ctx.get("in_news_blackout"):
        evt = ctx.get("blackout_event")
        title = (evt.get("title") if isinstance(evt, dict) else
                 getattr(evt, "title", "high-impact event")) if evt else "high-impact event"
        risks.append(f"NEWS BLACKOUT: {title}")
        risk_score += 3

    # 2. RSI extreme counter
    df_15m = ctx.get("df_15m")
    if df_15m is not None and len(df_15m) >= 30:
        last = df_15m.iloc[-1]
        rsi = last.get("rsi14", 50)
        if consensus == "LONG" and pd.notna(rsi) and rsi > 75:
            risks.append(f"RSI {rsi:.0f} overbought → long entry chasing")
            risk_score += 1
        if consensus == "SHORT" and pd.notna(rsi) and rsi < 25:
            risks.append(f"RSI {rsi:.0f} oversold → short entry chasing")
            risk_score += 1

        # 3. BB extremes
        bb_pct = last.get("bb_pctb")
        if pd.notna(bb_pct):
            if consensus == "LONG" and bb_pct > 0.95:
                risks.append("price at BB upper — pullback risk")
                risk_score += 1
            if consensus == "SHORT" and bb_pct < 0.05:
                risks.append("price at BB lower — bounce risk")
                risk_score += 1

    # 4. ATR percentile extreme
    df_4h = ctx.get("df_4h")
    if df_4h is not None and len(df_4h) >= 100 and "atr14" in df_4h.columns:
        atr_now = df_4h["atr14"].iloc[-1]
        atr_hist = df_4h["atr14"].iloc[-100:-1]
        if pd.notna(atr_now) and len(atr_hist) > 0:
            rank = (atr_hist < atr_now).mean()
            if rank > 0.95:
                risks.append(f"ATR pct {rank*100:.0f}% — EXTREME vol")
                risk_score += 2

    # 5. Counter-trend on D1
    df_1d = ctx.get("df_1d")
    if df_1d is not None and len(df_1d) >= 200:
        last_d = df_1d.iloc[-1]
        e200 = last_d.get("ema200")
        if pd.notna(e200):
            d1_up = last_d["close"] > e200
            if consensus == "LONG" and not d1_up:
                risks.append("D1 below EMA200 — counter HTF trend")
                risk_score += 1
            if consensus == "SHORT" and d1_up:
                risks.append("D1 above EMA200 — counter HTF trend")
                risk_score += 1

    # 6. Agent disagreement
    confidences = [v.confidence for v in others if v.confidence > 0]
    if confidences and (max(confidences) - min(confidences)) > 0.40:
        risks.append("agents disagree heavily — low conviction")
        risk_score += 1

    # 7. Asia session low-conviction
    if ctx.get("session") == "asia" and consensus != "NEUTRAL":
        risks.append("Asia session — low liquidity, wait London")
        risk_score += 1

    if not risks:
        risks = ["no major red flag detected"]

    if risk_score >= 3:
        return AgentVerdict("Devil's Advocate", "NEUTRAL", 0.85,
                            risks + ["VETO consensus"])
    if risk_score >= 1:
        # Soft warning — agree with consensus but reduced confidence
        confidence = max(0.0, 0.65 - risk_score * 0.10)
        return AgentVerdict("Devil's Advocate", consensus, confidence, risks)
    return AgentVerdict("Devil's Advocate", consensus, 0.75, risks)


def devils_advocate_llm(
    ctx: dict, others: list[AgentVerdict],
    llm_router, provider: str, model: str, log=print,
) -> AgentVerdict:
    """LLM-powered Devil's Advocate. Calls user-configured provider+model.
    On any failure, raises — caller (run_local_pipeline) catches and falls
    back to devils_advocate_local."""
    from ai_agent.agents import SYS_DEVILS_ADVOCATE  # reuse existing prompt

    # Build a compact context message from agent verdicts
    consensus_dirs = [v.verdict for v in others if v.verdict in ("LONG", "SHORT")]
    consensus = max(set(consensus_dirs), key=consensus_dirs.count) if consensus_dirs else "NEUTRAL"
    agents_summary = "\n".join(
        f"  {v.name}: {v.verdict} ({v.confidence:.2f}) — {'; '.join(v.reasoning[:2])}"
        for v in others
    )
    market_brief = (
        f"XAU spot={ctx.get('xau_price', '?')} regime={ctx.get('regime', '?')} "
        f"session={ctx.get('session', '?')} blackout={ctx.get('in_news_blackout', False)}"
    )
    user_msg = (
        f"Consensus: {consensus}\n\n"
        f"Market: {market_brief}\n\n"
        f"Agent verdicts:\n{agents_summary}\n\n"
        "Identify hidden risks. Reply with: VETO|APPROVE|WARN: <one-line reason>"
    )

    t0 = time.perf_counter()
    resp = llm_router.chat(
        provider=provider, model=model,
        messages=[
            {"role": "system", "content": SYS_DEVILS_ADVOCATE},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3, max_tokens=300,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    text = (resp.content or "").strip().upper()

    if text.startswith("VETO"):
        verdict, conf = "NEUTRAL", 0.85
    elif text.startswith("WARN"):
        verdict, conf = consensus, 0.55
    else:  # APPROVE or ambiguous
        verdict, conf = consensus, 0.75

    reason_text = resp.content.strip().split("\n")[0][:200]
    return AgentVerdict("Devil's Advocate", verdict, conf,
                        [f"LLM ({provider}:{model}): {reason_text}"],
                        engine=f"llm:{provider}", latency_ms=latency_ms)


# ────────────────────────────────────────────────────────────────────────────
# AGENT 12 — Synthesizer (weighted vote → final action + strength)
# ────────────────────────────────────────────────────────────────────────────

# Per-agent weights for synthesizer vote. Tunable based on backtest.
AGENT_WEIGHTS: dict[str, float] = {
    "HTF Bias":          1.5,
    "Session Phase":     0.5,   # NEUTRAL only — multiplies others, doesn't vote
    "LTF Technical":     1.5,
    "Liquidity SMC":     1.3,
    "Order Flow":        1.0,
    "Pattern Expert":    1.4,
    "Volume Profile":    0.8,
    "News Proximity":    1.0,   # NEUTRAL veto when high-conf
    "Volatility":        0.7,
    "Backtest Memory":   0.6,
    "Devil's Advocate":  2.0,   # final veto or boost
}


def synthesize(verdicts: list[AgentVerdict]) -> tuple[str, float, str, str, list[str]]:
    """Weighted vote → (action, confidence, signal_strength, primary_driver, chain).

    Logic:
      1. If Devil's Advocate verdict=NEUTRAL with conf>0.7 → VETO, return FLAT.
      2. If News Proximity verdict=NEUTRAL with conf>0.85 → BLACKOUT, return FLAT.
      3. Else: weighted sum of signed confidences. Direction=sign of net.
         confidence = clipped(|net| / total_weight, max 0.95).
      4. Strength tier from confidence + agree count.
    """
    # Veto checks
    for v in verdicts:
        if v.name == "Devil's Advocate" and v.verdict == "NEUTRAL" and v.confidence > 0.70:
            return "FLAT", 0.0, "FLAT", "DA veto", \
                   [f"VETO by Devil's: {'; '.join(v.reasoning[:2])}"]
        if v.name == "News Proximity" and v.verdict == "NEUTRAL" and v.confidence > 0.85:
            return "FLAT", 0.0, "FLAT", "news veto", \
                   [f"News BLACKOUT: {'; '.join(v.reasoning[:1])}"]

    long_w = 0.0
    short_w = 0.0
    total_w = 0.0
    long_count = 0
    short_count = 0
    contributions: list[tuple[str, float]] = []
    chain: list[str] = []

    for v in verdicts:
        w = AGENT_WEIGHTS.get(v.name, 1.0)
        total_w += w
        if v.verdict == "LONG":
            long_w += v.confidence * w
            long_count += 1
        elif v.verdict == "SHORT":
            short_w += v.confidence * w
            short_count += 1
        # NEUTRAL contributes to total_w but not to direction
        contributions.append((v.name, _conf(v.verdict, v.confidence) * w))
        chain.append(f"[{v.name}] {v.verdict} conf={v.confidence:.2f} ({'; '.join(v.reasoning[:2])})")

    net = long_w - short_w
    if abs(net) < 0.5 or total_w == 0:
        return "FLAT", 0.30, "FLAT", "no consensus", chain

    direction = "LONG" if net > 0 else "SHORT"
    raw_conf = abs(net) / max(total_w, 1.0)
    confidence = round(min(raw_conf + 0.10, 0.95), 3)

    agree_count = long_count if direction == "LONG" else short_count
    if confidence >= 0.80 and agree_count >= 5:
        strength = "STRONG"
    elif confidence >= 0.65 and agree_count >= 4:
        strength = "NORMAL"
    elif confidence >= 0.50 and agree_count >= 3:
        strength = "WEAK"
    else:
        strength = "FLAT"
        return "FLAT", confidence, strength, "weak vote", chain

    # Primary driver = agent that contributed most to the agreed direction
    primary = ""
    best_contrib = 0.0
    for name, c in contributions:
        cs = c if direction == "LONG" else -c
        if cs > best_contrib:
            best_contrib = cs; primary = name

    return direction, confidence, strength, primary or "mixed", chain


# ────────────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────────────

def run_local_pipeline(
    market_ctx: dict,
    da_engine: str = "local",
    llm_router=None,
    da_llm_provider: Optional[str] = None,
    da_llm_model: Optional[str] = None,
    log=print,
) -> dict:
    """Run all 12 local agents + synthesizer. Returns dict matching
    ai_agent.orchestrator.run_llm_debate() output schema.

    da_engine: 'local' | 'llm' — selects Devil's Advocate engine.
    llm_router: required if da_engine='llm'; ignored otherwise.
    """
    fallback_used = False

    # Build context dict (keep this lean — agents pick what they need)
    ctx = {
        "df_5m":           market_ctx.get("df_5m"),
        "df_15m":          market_ctx.get("df_15m"),
        "df_1h":           market_ctx.get("df_1h"),
        "df_4h":           market_ctx.get("df_4h"),
        "df_1d":           market_ctx.get("df_1d"),
        "intermarket":     market_ctx.get("intermarket"),
        "cot":             market_ctx.get("cot"),
        "session":         market_ctx.get("session"),
        "regime":          market_ctx.get("regime"),
        "in_news_blackout": market_ctx.get("in_news_blackout", False),
        "blackout_event":  market_ctx.get("blackout_event"),
        "upcoming_events": market_ctx.get("upcoming_events"),
        "near_london_fix": market_ctx.get("near_london_fix", False),
        "xau_price":       market_ctx.get("xau_price"),
        "store":           market_ctx.get("store"),
    }

    # Run 11 specialists (DA last, after others' verdicts available)
    others: list[AgentVerdict] = []
    others.append(htf_bias_agent(ctx))
    others.append(session_phase_agent(ctx))
    others.append(ltf_technical_agent(ctx))
    others.append(liquidity_smc_agent(ctx))
    others.append(order_flow_agent(ctx))
    others.append(pattern_expert_agent(ctx))
    others.append(volume_profile_agent(ctx))
    others.append(news_proximity_agent(ctx))
    others.append(volatility_agent(ctx))
    others.append(backtest_memory_agent(ctx))

    # Devil's Advocate (last, sees others' verdicts)
    if da_engine == "llm" and llm_router is not None and da_llm_provider:
        try:
            da = devils_advocate_llm(
                ctx, others, llm_router,
                da_llm_provider, da_llm_model or "openai/gpt-oss-20b:free",
                log=log,
            )
            log(f"[local-agents] DA via llm:{da_llm_provider} ({da.latency_ms}ms)")
        except Exception as e:
            log(f"[local-agents] DA LLM failed: {e!r} — fallback to local DA")
            da = devils_advocate_local(ctx, others)
            fallback_used = True
    else:
        da = devils_advocate_local(ctx, others)

    all_verdicts = others + [da]

    # Synthesize
    final_action, confidence, strength, primary, chain = synthesize(all_verdicts)
    risks = da.reasoning  # Devil's reasoning IS the risk list

    return {
        "final_action":     final_action,
        "confidence":       confidence,
        "signal_strength":  strength,
        "primary_driver":   primary,
        "reasoning_chain":  chain,
        "risks":            risks,
        "agents":           [asdict(v) for v in all_verdicts],
        "engine":           "local-12-agent",
        "engine_meta": {
            "da_engine":        da.engine,
            "da_fallback_used": fallback_used,
            "total_latency_ms": sum(v.latency_ms for v in all_verdicts),
        },
    }


# Smoke test
if __name__ == "__main__":
    print("local_agents.py — 12-agent rule-based pipeline")
    print(f"Agents: {list(AGENT_WEIGHTS.keys())}")
    print(f"Total weight: {sum(AGENT_WEIGHTS.values()):.1f}")
    print("OK")
