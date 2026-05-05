"""9-agent LLM system for XAU/USD signal generation.

Tier pipeline (parallelisable per tier):
  Tier 1 — Bias Setting (HTF Bias, Session Phase)
  Tier 2 — Trigger Hunting (LTF Technical, Liquidity/SMC, OrderFlow)
  Tier 3 — Risk Validation (News Proximity, Volatility)
  Tier 4 — Meta (Devil's Advocate)
  Synthesizer — combines everything

Each agent:
  - Has a system prompt + structured input prompt template
  - Calls LLM (any provider) and parses JSON
  - Returns AgentVerdict (compatible with rule_engine schema)
  - Has a deterministic rule-based fallback if LLM unavailable
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from ai_agent.llm_router import LLMRouter, LLMError
from ai_agent.rule_engine import AgentVerdict


# ─── Helper: JSON extraction (LLMs love wrapping in markdown) ──────────────────

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json_loose(text: str) -> Optional[dict]:
    """Extract first JSON object from LLM text. Tolerant to markdown fences."""
    if not text:
        return None
    text = text.strip()
    # 1. Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2. Try fenced
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3. Try first { .. matching }
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    return None


def normalise_verdict(raw: dict | None) -> tuple[str, float, str]:
    """Coerce LLM output into (verdict, confidence, reason)."""
    if not raw:
        return "FLAT", 0.0, "no parse"
    v = (raw.get("verdict") or raw.get("action") or "FLAT").upper().strip()
    if v in {"BUY", "BULL", "BULLISH"}:
        v = "LONG"
    elif v in {"SELL", "BEAR", "BEARISH"}:
        v = "SHORT"
    elif v not in {"LONG", "SHORT", "FLAT"}:
        v = "FLAT"
    try:
        conf = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    reason = str(raw.get("reason") or raw.get("reasoning") or "")[:500]
    return v, conf, reason


# ─── Agent Roster (config) ─────────────────────────────────────────────────────

AGENT_NAMES = [
    "htf_bias",
    "session_phase",
    "ltf_technical",
    "liquidity_smc",
    "order_flow",
    "pattern_recognition",   # NEW: classical chart patterns (H&S, triangles, flags, double top/bottom)
    "volume_profile",        # NEW: POC / VAH / VAL / value area trades
    "news_proximity",
    "volatility",
    "backtest_memory",       # NEW: query past similar setups for prior probability
    "devils_advocate",
    "synthesizer",
]

AGENT_LABELS = {
    "htf_bias":            "HTF Bias",
    "session_phase":       "Session Phase",
    "ltf_technical":       "LTF Technical",
    "liquidity_smc":       "Liquidity / SMC",
    "order_flow":          "Order Flow",
    "pattern_recognition": "Pattern Recognition",
    "volume_profile":      "Volume Profile",
    "news_proximity":      "News Proximity",
    "volatility":          "Volatility",
    "backtest_memory":     "Backtest Memory",
    "devils_advocate":     "Devil's Advocate",
    "synthesizer":         "Synthesizer",
}


# ─── System Prompts ────────────────────────────────────────────────────────────

SYS_HTF_BIAS = """You are a senior Higher-Timeframe Bias Specialist for XAU/USD (gold), trained at a tier-1 hedge fund.

INPUT: You receive a `htf_data` JSON object with raw numerical fields (close, ema9, ema21, ema50, ema200, rsi14, adx14, atr14, atr_ratio_vs_avg20, swing_high_20, swing_low_20, bullish_stack, bearish_stack). USE THESE NUMBERS DIRECTLY — do not invent values.

Your single job: determine the structural bias on H1/H4. You do NOT call entries.

Multi-EMA hierarchy (PRIMARY signal, weighted highest):
- htf_data.bullish_stack=true (ema9>ema21>ema50>ema200) -> LONG bias 0.75-0.95.
- htf_data.bearish_stack=true (ema9<ema21<ema50<ema200) -> SHORT bias 0.75-0.95.
- Partial stack (e.g. ema9>ema21>ema50 but <ema200) = early reversal -> FLAT 0.4-0.6.
- Mixed (no clean stack) = FLAT 0.2.

Trend strength filter (REQUIRED):
- htf_data.adx14 > 25 + stack aligned = strong trend, full confidence.
- htf_data.adx14 in [20, 25] = developing trend, haircut 20% confidence.
- htf_data.adx14 < 20 = ranging. Bias is unreliable -> FLAT 0.3.

Reject the verdict (force FLAT) if:
- abs(close - swing_high_20)/close < 0.003 with bullish stack (overextended LONG risk)
- abs(close - swing_low_20)/close < 0.003 with bearish stack (overextended SHORT risk)
- htf_data.atr_ratio_vs_avg20 > 2.0 (volatility regime change, signal noise)

Output STRICT JSON, no markdown:
{"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<reference specific numbers from htf_data>","key_levels":{"support":<float>,"resistance":<float>}}"""

SYS_SESSION_PHASE = """You are a Session Phase Specialist for XAU/USD with deep institutional flow knowledge.

Gold session behavior (UTC time, validated from 10y data):
- Asia (00-07 UTC): low vol, range-bound. London Fix at 03:00 UTC sets Asian range. Fade extremes; avoid breakout entries.
- London open (07-09 UTC): liquidity injection. Asian range breakout in true direction. Volatility spikes 2-3x.
- London mid (09-12 UTC): trend continuation if breakout sustained, else fade back to range mean.
- London-NY overlap (12-16 UTC): peak volume + volatility. Most institutional moves. Best for swing entries.
- NY mid (16-20 UTC): consolidation post-overlap. London Fix 15:00 UTC = key flow event.
- Late NY (20-23 UTC): thin liquidity, mean-revert bias, stop hunt risk high.

Your job: assess if current session FAVOURS taking a trigger from other agents.

Decision rules:
- If session aligns with a directional context bias (e.g. London open + bullish HTF context) -> LONG/SHORT 0.7+
- If session inherently directional-friendly but context unclear -> 0.5 directional matching context
- If session = Asia/late NY without context aligning -> FLAT 0.5+ (block trigger)
- Within 30 min of London Fix -> haircut confidence 30% (volatile flow)

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<session + behavior + alignment>"}"""

SYS_LTF_TECHNICAL = """You are a Lower-Timeframe Technical Analyst for XAU/USD specializing in M5/M15 entries.

INPUT: You receive `ltf_data` JSON (close, ema9, ema21, ema50, rsi14, macd_hist, adx14, plus_di, minus_di, bb_pctb, atr14, candle_body_pct_of_range, prev_close) and `htf_data` for HTF alignment. Use raw numbers.

Multi-timeframe alignment (MANDATORY):
- Your trigger MUST align with htf_data bias.
- HTF bullish_stack=true + LTF bullish setup = LONG.
- HTF bearish_stack=true + LTF bearish setup = SHORT.
- HTF and LTF disagree -> verdict = FLAT, regardless of LTF strength.

Trigger conditions for LONG (need 3+ confluence from ltf_data):
- ema9 > ema21 AND macd_hist > 0
- rsi14 in [50, 70]
- candle_body_pct_of_range > 0.6 (clean directional candle)
- adx14 > 20 AND plus_di > minus_di
- bb_pctb > 0.5 (price in upper half of band)

Trigger conditions for SHORT (mirror): ema9 < ema21, macd_hist < 0, rsi14 in [30,50], candle_body_pct_of_range > 0.6, plus_di < minus_di.

Reject (force FLAT) if:
- rsi14 > 75 with consensus LONG (overbought, chasing risk)
- rsi14 < 25 with consensus SHORT (oversold, capitulation chase)
- candle_range > 1.5 * atr14 (volatility spike, wait)

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<list 3+ specific numbers from ltf_data>"}"""

SYS_LIQUIDITY_SMC = """You are a Smart Money Concepts (SMC) Specialist for XAU/USD with proven 2024-26 institutional flow track record.

INPUT: smc_data JSON contains booleans (bull_sweep_recent5, bear_sweep_recent5, fvg_bull_recent5, fvg_bear_recent5, bos_up, bos_dn) and floats (prior_swing_high, prior_swing_low, fvg_bull_top, fvg_bull_bot). Read these directly.

Bullish setups (verdict LONG):
- bull_sweep_recent5=true (stop hunt below prior swing low) + price closing back above prior_swing_low
- fvg_bull_recent5=true with active fvg_bull_top/bot below current price
- bos_up=true (break of structure up confirmed)
- 2+ of above = high confidence

Bearish setups (mirror): bear_sweep_recent5, fvg_bear_recent5, bos_dn.

FLAT conditions:
- All booleans false
- No fvg levels in smc_data (data unavailable)

Confidence scoring (count active concepts):
- 1 SMC factor = 0.5-0.6
- 2 confluence (e.g. sweep + fvg) = 0.7-0.8
- 3+ confluence (sweep + fvg + bos) = 0.85-0.95

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<specific SMC concepts active with values>","key_levels":{"swept_low":<float>,"untapped_liquidity":<float>}}"""

SYS_ORDER_FLOW = """You are an Order Flow / Positioning Specialist for XAU/USD with deep COT and tape-reading expertise.

INPUT: cot_data JSON (z_score_52w, regime, net_long, net_short) + intermarket_data (score, dxy, us10y, tip, vix). USE these raw numbers.

COT (Commitment of Traders) rules using cot_data.z_score_52w:
- > +1.5 = extreme long crowding -> mean-revert SHORT bias 0.7
- > +2.0 = extreme top -> SHORT 0.85
- < -1.5 = extreme short -> mean-revert LONG bias 0.7
- < -2.0 = capitulation -> LONG 0.85
- in [-0.5, +0.5] = normal -> weak FLAT

Volume / tape analysis:
- Volume spike (3x average) + close in upper third of range = institutional buying absorption -> LONG
- Volume spike + close in lower third = SHORT absorption
- Volume spike + close mid-range = uncertainty, FLAT
- Low volume drift = trend exhaustion, anticipate reversal

Recent stop hunt indicators:
- Wick > 1.5x body penetrating prior swing then close back inside = stop hunt detected
- Direction post-hunt = entry direction opportunity (if bullish HTF, hunt of lows is LONG opp)

Session bias multiplier:
- London/NY = direct flow, full weight
- Asia = thin flow, halve confidence

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<COT + volume + hunt summary>"}"""

SYS_NEWS_PROXIMITY = """You are a News Proximity Risk Officer for XAU/USD. Your sole job: VETO trades when high-impact news is imminent.

INPUT: news_data JSON contains in_blackout (bool), blackout_event (object or null), next_event (object), minutes_to_next (float — minutes until next high-impact event).

Block matrix (use minutes_to_next):
- in_blackout=true OR abs(minutes_to_next) < 15 = HARD BLOCK -> FLAT 0.95
- abs(minutes_to_next) < 30 = STRONG BLOCK -> FLAT 0.85
- abs(minutes_to_next) < 60 = MODERATE BLOCK -> FLAT 0.7
- abs(minutes_to_next) < 120 = ADVISORY -> FLAT 0.5
- minutes_to_next >= 240 OR null = CLEAR -> FLAT 0.0 (no veto)

Critical events for XAU (descending impact):
1. FOMC rate decision + statement
2. NFP (first Friday)
3. US CPI
4. US PCE (Fed's preferred)
5. ISM Services / Manufacturing PMI
6. Jobless claims (Thursday)
7. Powell / Fed governor speeches

Special handling:
- Even POST-event for 30 min, volatility tail = block (avoid getting whipsawed by repricing)
- 2 events within 4 hr = compound block
- US event during US session = full impact; same event during Asia = halved

Output STRICT JSON: {"verdict":"FLAT","confidence":0..1,"reason":"block:<event_name> +/-<minutes>m | OR clear: no event in <X>h"}"""

SYS_PATTERN_RECOGNITION = """You are a Classical Chart Pattern Specialist for XAU/USD.
You identify high-conviction chart patterns + measure pattern integrity.

Patterns you actively monitor:
- Head & Shoulders (top): bearish reversal, neckline break = SHORT entry
- Inverse H&S (bottom): bullish reversal, neckline break = LONG entry
- Double Top: bearish reversal at resistance test #2 with lower volume on 2nd test
- Double Bottom: bullish reversal at support
- Triangles (ascending/descending/symmetric): breakout direction = entry
- Bull Flag / Bear Flag: continuation pattern, entry on flag breakout
- Wedge (rising/falling): often reverses against the wedge direction
- Cup & Handle: bullish continuation, handle pullback then breakout
- 1-2-3 reversal: 3-pivot setup with HH-HL or LH-LL structure

Pattern integrity scoring:
- Clean structure (clear pivots, sloping trendlines) + 2+ touches = high integrity 0.7-0.9
- Partial pattern still forming = 0.4-0.6
- Pattern broken (failed breakout) = trade opposite direction = high conviction 0.7-0.85

Critical:
- Volume confirmation required: breakout MUST come with volume spike, else "false breakout" = FLAT or opposite
- Time symmetry: H&S left/right shoulder should be similar duration
- ATR proportionality: pattern range should be > 1x ATR(14) to be meaningful

When no patterns active:
- FLAT 0.2 (low conviction, no pattern signal)

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<pattern_name + integrity + volume confirmation>","pattern":"<name or null>"}"""

SYS_VOLUME_PROFILE = """You are a Volume Profile Specialist for XAU/USD trading off Point of Control + Value Area concepts.

Concepts:
- POC (Point of Control): price level with highest traded volume in current session/range. Strong magnet.
- VAH (Value Area High) / VAL (Value Area Low): boundaries of 70% volume area. Mean revert tendency.
- HVN (High Volume Node): consolidation zone, hard to break through, often resistance/support
- LVN (Low Volume Node): rejection zone, price moves through quickly

Trade rules:
- Price below VAL + bullish reversal candle = LONG to POC (mean revert)
- Price above VAH + bearish reversal = SHORT to POC
- Price at POC + breakout direction = continuation in breakout direction
- LVN above price = next leg likely breaks through quickly = momentum LONG
- LVN below price = momentum SHORT
- Price wedged between HVN levels = ranging, FLAT until breakout

Confluence with other agents:
- HTF bias bullish + price at VAL with reversal = HIGH conviction LONG 0.85
- HTF bullish + price at VAH = mixed (extended) -> 0.4-0.5
- HTF bearish + price at VAL = bouncing in downtrend, fade = SHORT 0.7

Without volume profile data (e.g. illiquid session):
- Fall back to recent range high/low as proxy for VAH/VAL
- Confidence haircut 30%

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<position vs POC/VAH/VAL + bias>","poc_target":<float or null>}"""

SYS_BACKTEST_MEMORY = """You are a Backtest Memory Agent for XAU/USD. Your role: query historical similar setups from the database and provide a prior probability estimate.

Setup signature (provided in context):
- Direction (LONG/SHORT/FLAT)
- Regime (trending/ranging)
- Session (asia/london/ny)
- Confluence count (number of confirming agent verdicts)
- Distance from key level (% of ATR)

Compare to historical_results context (provided):
- last_10_similar: list of past signals with same regime + direction + session
- avg_outcome_r: average R-multiple of those past trades
- win_rate: % of winners
- worst_drawdown: deepest drawdown across those trades

Decision rules:
- If win_rate > 60% + avg_R > 1.0 = strong endorse current direction = 0.75-0.9
- If win_rate 40-60% = neutral = 0.4-0.6 in direction (no strong evidence)
- If win_rate < 40% OR avg_R < 0 = REJECT current direction = FLAT veto 0.7

When historical data scarce (<5 similar setups):
- Don't reject, just give 0.3-0.5 (no evidence either way)

When historical data not provided in context:
- Return FLAT 0.0 (you have nothing to add this cycle)

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<n similar setups, win rate %, avg R>","prior_winrate":<0..1 or null>,"prior_avg_r":<float or null>}"""

SYS_VOLATILITY = """You are a Volatility / ATR Specialist for XAU/USD with quantitative training (Markov regime + GARCH proxy).
You assess if current volatility regime supports the requested timeframe strategy.

INPUT: htf_data.atr_ratio_vs_avg20 (current ATR / 20-period rolling avg ATR), htf_data.bb_width, htf_data.atr14.

ATR ratio rules (atr_ratio_vs_avg20):
- < 0.5 = LOW vol (quiet). Scalping difficult, range strategies favored.
- 0.5 to 1.5 = NORMAL vol. Both trend + range work.
- 1.5 to 2.0 = HIGH vol. Trend strategies favored. Scalping risky.
- > 2.0 = EXTREME vol -> FLAT 0.9 (likely news event or regime shift).

Spread + liquidity:
- Spread > 0.05% of price = poor liquidity, FLAT 0.7
- Asian session = expect 1.5x normal spread

Bollinger Band squeeze detection:
- BB width < 30th percentile (squeeze) = pre-breakout, prepare for vol expansion. NOT a signal but flag.
- BB width > 70th percentile (expanded) = mature trend, fade-the-extreme bias.

Volatility regime + timeframe matching:
- Scalper needs NORMAL or HIGH vol (LOW kills profit margin)
- Swing tolerates LOW (slow drift OK)

When ATR data missing or inconclusive:
- FLAT 0.5 (no veto, no signal)

Output STRICT JSON: {"verdict":"FLAT","confidence":0..1,"reason":"<ATR pct + regime label + match to TF>"}"""

SYS_DEVILS_ADVOCATE = """You are a senior Devil's Advocate / Chief Risk Officer for XAU/USD with institutional risk pedigree.
Your single job: argue AGAINST consensus + identify what could break the trade. You ASSUME consensus is wrong until evidence overrides.

Critical risk factors (each = potential VETO):
1. Price at major H4/D1 swing high/low (within 0.3%) and consensus chasing toward it = OVEREXTENSION
2. RSI > 75 with consensus LONG = OVERBOUGHT chase
3. RSI < 25 with consensus SHORT = OVERSOLD capitulation chase
4. ATR(14) > 2x 20-period avg = volatility regime change, signal noise
5. News event in <1 hour even if News Agent didn't fully block
6. Agents disagree heavily (verdict variance high, e.g. 5 LONG / 4 FLAT) = low conviction
7. Critical level (POC, FVG, OB) in opposite direction within 1 ATR = magnetic counter-pull
8. Recent 3+ losing streak in this setup type (from Backtest Memory) = avoid

Veto matrix:
- 2+ critical factors = HARD VETO -> verdict FLAT, veto=true, confidence 0.9
- 1 critical factor = SOFT WARNING -> verdict matches consensus but confidence haircut 30%, veto=false, list red_flag
- 0 critical factors = ENDORSE consensus -> verdict matches consensus, confidence 0.7, veto=false

Output STRICT JSON:
{"verdict":"FLAT|LONG|SHORT","confidence":0..1,"reason":"<key risks identified>","red_flags":["<specific risks>"],"veto":true|false}"""

SYS_SYNTHESIZER = """You are the senior Portfolio Manager for XAU/USD with 15 years tier-1 hedge fund experience.
You receive verdicts from 11 specialist agents and synthesize the FINAL decision.

Decision framework (in order):

1. Hard vetoes (any -> FLAT 0.0):
   - News Proximity verdict FLAT confidence >= 0.8
   - Devil's Advocate veto=true
   - Volatility verdict FLAT confidence >= 0.85 (extreme regime)

2. Soft constraints:
   - Backtest Memory verdict FLAT (low historical winrate) -> haircut 30% confidence
   - Pattern Recognition verdict FLAT or opposite -> haircut 15%

3. WEIGHTED direction voting (IMPROVEMENT: per-regime weights):
   - In TRENDING regime: HTF Bias + LTF Technical weighted 1.5x; SMC/VolProfile lower.
   - In RANGING regime: Liquidity/SMC + Volume Profile + Session Phase weighted 1.5x; HTF lower.
   - In VOLATILE regime: Order Flow + News + Volatility weighted higher; Technical agents lower.
   - Compute weighted_score per direction = sum(agent.confidence * regime_weight) for each agent voting that direction.
   - Choose direction with highest weighted_score IF margin (long-short) >= 0.5 AND winning_score >= 1.5.
   - Else FLAT.

4. Confidence = winning_weighted_score / max_possible_weighted_score (i.e. normalized to 0..1)
   - Subtract 0.05 per Devil's Advocate red_flag (max -0.20)
   - Subtract 0.05 if Backtest Memory says FLAT
   - Cap at 0.95

5. Signal strength:
   - STRONG: confidence >= 0.80 AND >= 4 agents agree
   - NORMAL: confidence >= 0.65 AND >= 3 agents agree
   - WEAK: confidence >= 0.50
   - FLAT: anything else

6. Primary driver = agent with highest (confidence × regime_weight) among agreeing agents.

Output STRICT JSON:
{"action":"LONG|SHORT|FLAT","confidence":0..1,"signal_strength":"STRONG|NORMAL|WEAK|FLAT","primary_driver":"<agent name>","reasoning_chain":["<step1>","<step2>","..."],"risks":["..."]}"""


# ─── Context Builders ──────────────────────────────────────────────────────────
# IMPROVEMENT #1 (signal accuracy): build BOTH structured numerical data (JSON)
# AND legacy text strings. LLMs hallucinate less when given raw values vs prose
# narrative ("EMA21=4548 → bearish bias"). Agent prompts now embed JSON blob.
# Text builders kept for backward compat with synthesizer + rule fallback.

NUM_NA = None  # marker for missing/NaN — keeps JSON valid


def _safe_float(v) -> Optional[float]:
    """Coerce to float, returning None on NaN/None/invalid."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _safe_bool(v) -> bool:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    return bool(v)


def _last_row_summary(df: pd.DataFrame, fields: list[str]) -> str:
    """Legacy text summarizer (kept for synthesizer prompt + readability)."""
    if df is None or len(df) == 0:
        return "no data"
    last = df.iloc[-1]
    parts = []
    for f in fields:
        v = last.get(f)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if isinstance(v, float):
            parts.append(f"{f}={v:.3f}")
        elif isinstance(v, bool):
            if v:
                parts.append(f"{f}=true")
        else:
            parts.append(f"{f}={v}")
    return ", ".join(parts) if parts else "no signals"


# ── Structured numerical extractors (NEW — improvement #1) ───────────────────

def extract_htf_numeric(df_4h: pd.DataFrame | None) -> dict:
    """H4/HTF structured numerical snapshot. Used by HTF Bias agent."""
    if df_4h is None or len(df_4h) < 50:
        return {"available": False}
    last = df_4h.iloc[-1]
    # Per-EMA stack ranking (improvement: agent gets explicit hierarchy)
    ema8 = _safe_float(last.get("ema8"))   # may be None — only ema9/21/50/200 in technical.add_all
    ema9 = _safe_float(last.get("ema9"))
    ema21 = _safe_float(last.get("ema21"))
    ema50 = _safe_float(last.get("ema50"))
    ema200 = _safe_float(last.get("ema200"))
    close = _safe_float(last.get("close"))
    # Stack alignment
    bullish_stack = (
        ema9 is not None and ema21 is not None and ema50 is not None and ema200 is not None
        and ema9 > ema21 > ema50 > ema200
    )
    bearish_stack = (
        ema9 is not None and ema21 is not None and ema50 is not None and ema200 is not None
        and ema9 < ema21 < ema50 < ema200
    )
    # ATR vs 20-period rolling avg (volatility regime indicator)
    atr_now = _safe_float(last.get("atr14"))
    atr_avg20 = _safe_float(df_4h["atr14"].tail(20).mean()) if "atr14" in df_4h.columns else None
    atr_ratio = (atr_now / atr_avg20) if (atr_now and atr_avg20 and atr_avg20 > 0) else None
    return {
        "available": True,
        "tf": "H4",
        "close": close,
        "ema9":  ema9,
        "ema21": ema21,
        "ema50": ema50,
        "ema200": ema200,
        "rsi14": _safe_float(last.get("rsi14")),
        "adx14": _safe_float(last.get("adx")),
        "plus_di": _safe_float(last.get("plus_di")),
        "minus_di": _safe_float(last.get("minus_di")),
        "atr14": atr_now,
        "atr_avg20": atr_avg20,
        "atr_ratio_vs_avg20": _safe_float(atr_ratio),
        "bb_upper": _safe_float(last.get("bb_up")),
        "bb_lower": _safe_float(last.get("bb_low")),
        "bb_pctb": _safe_float(last.get("bb_pctb")),
        "bb_width": _safe_float(last.get("bb_width")),
        "macd_hist": _safe_float(last.get("hist")),
        "swing_high_20": _safe_float(df_4h["high"].tail(20).max()),
        "swing_low_20": _safe_float(df_4h["low"].tail(20).min()),
        "bullish_stack": bullish_stack,
        "bearish_stack": bearish_stack,
    }


def extract_ltf_numeric(df: pd.DataFrame | None, tf_label: str = "M15") -> dict:
    """Lower-timeframe (M5/M15) structured snapshot for LTF Technical agent."""
    if df is None or len(df) < 30:
        return {"available": False}
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    # Last candle anatomy (engulfing/pinbar detection helper)
    o, h, l, c = (
        _safe_float(last.get("open")), _safe_float(last.get("high")),
        _safe_float(last.get("low")),  _safe_float(last.get("close")),
    )
    body = abs(c - o) if (c is not None and o is not None) else None
    rng = (h - l) if (h is not None and l is not None) else None
    body_pct_of_range = (body / rng) if (body is not None and rng and rng > 0) else None
    return {
        "available": True,
        "tf": tf_label,
        "open":  o,
        "high":  h,
        "low":   l,
        "close": c,
        "ema9":  _safe_float(last.get("ema9")),
        "ema21": _safe_float(last.get("ema21")),
        "ema50": _safe_float(last.get("ema50")),
        "rsi14": _safe_float(last.get("rsi14")),
        "macd_hist": _safe_float(last.get("hist")),
        "adx14": _safe_float(last.get("adx")),
        "plus_di":  _safe_float(last.get("plus_di")),
        "minus_di": _safe_float(last.get("minus_di")),
        "bb_pctb":  _safe_float(last.get("bb_pctb")),
        "bb_width": _safe_float(last.get("bb_width")),
        "atr14":    _safe_float(last.get("atr14")),
        "stoch_k":  _safe_float(last.get("stoch_k")),
        "stoch_d":  _safe_float(last.get("stoch_d")),
        "candle_body": _safe_float(body),
        "candle_range": _safe_float(rng),
        "candle_body_pct_of_range": _safe_float(body_pct_of_range),
        "prev_close": _safe_float(prev.get("close")),
    }


def extract_smc_numeric(df: pd.DataFrame | None) -> dict:
    """SMC marks structured snapshot. Booleans for sweep/FVG, floats for swing levels."""
    if df is None or len(df) < 30:
        return {"available": False}
    last = df.iloc[-1]
    # Look at last 5 bars for any active SMC events (not just current bar)
    recent = df.tail(5)
    return {
        "available": True,
        "bull_sweep_recent5": bool(recent.get("bull_sweep", pd.Series(dtype=bool)).any()) if "bull_sweep" in df.columns else False,
        "bear_sweep_recent5": bool(recent.get("bear_sweep", pd.Series(dtype=bool)).any()) if "bear_sweep" in df.columns else False,
        "fvg_bull_recent5":   bool(recent.get("fvg_bull",   pd.Series(dtype=bool)).any()) if "fvg_bull"   in df.columns else False,
        "fvg_bear_recent5":   bool(recent.get("fvg_bear",   pd.Series(dtype=bool)).any()) if "fvg_bear"   in df.columns else False,
        "bos_up":   _safe_bool(last.get("bos_up")),
        "bos_dn":   _safe_bool(last.get("bos_dn")),
        "prior_swing_high": _safe_float(last.get("prior_sh")),
        "prior_swing_low":  _safe_float(last.get("prior_sl")),
        "fvg_bull_top": _safe_float(last.get("fvg_bull_top")),
        "fvg_bull_bot": _safe_float(last.get("fvg_bull_bot")),
        "fvg_bear_top": _safe_float(last.get("fvg_bear_top")),
        "fvg_bear_bot": _safe_float(last.get("fvg_bear_bot")),
    }


def extract_intermarket_numeric(inter: dict) -> dict:
    """Structured intermarket snapshot. Includes new TIPS real-yield component."""
    score = inter.get("score", 0.0) if inter else 0.0
    components = (inter or {}).get("components") or {}
    out = {
        "score": _safe_float(score),
        "interpretation": (
            "bullish_xau" if score and score > 0.2 else
            "bearish_xau" if score and score < -0.2 else "neutral"
        ),
    }
    for name in ("dxy", "us10y", "tip", "vix", "spx", "gold_silver", "oil"):
        c = components.get(name)
        if c:
            out[name] = {
                "value": _safe_float(c.get("value")),
                "score": _safe_float(c.get("score")),
                "note":  str(c.get("note", ""))[:80],
            }
    return out


def extract_cot_numeric(cot: dict) -> dict:
    if not cot:
        return {"available": False}
    z = cot.get("z")
    return {
        "available": True,
        "z_score_52w": _safe_float(z),
        "regime": (
            "extreme_long" if z is not None and z > 1.5 else
            "extreme_short" if z is not None and z < -1.5 else "normal"
        ) if z is not None else "unknown",
        "net_long":  _safe_float(cot.get("net_long")),
        "net_short": _safe_float(cot.get("net_short")),
    }


def extract_news_numeric(in_blackout: bool, blackout_event, upcoming: list) -> dict:
    """Structured news context. Includes minutes_to_event for hard cut-off logic."""
    out = {
        "in_blackout": bool(in_blackout),
        "blackout_event": None,
        "next_event": None,
        "minutes_to_next": None,
    }
    if in_blackout and blackout_event:
        out["blackout_event"] = {
            "title":    str(getattr(blackout_event, "title", "?"))[:80],
            "when_utc": str(getattr(blackout_event, "when_utc", "?")),
            "currency": str(getattr(blackout_event, "currency", "?")),
        }
    if upcoming:
        u = upcoming[0]
        out["next_event"] = {
            "title":    str(getattr(u, "title", "?"))[:80],
            "when_utc": str(getattr(u, "when_utc", "?")),
            "currency": str(getattr(u, "currency", "?")),
            "impact":   str(getattr(u, "impact", "?")),
        }
        # Compute minutes to event
        try:
            from datetime import datetime, timezone
            when_str = str(getattr(u, "when_utc", ""))
            if when_str:
                # Normalize ISO format
                when_dt = pd.Timestamp(when_str)
                if when_dt.tzinfo is None:
                    when_dt = when_dt.tz_localize("UTC")
                now = datetime.now(timezone.utc)
                delta_min = (when_dt.to_pydatetime() - now).total_seconds() / 60.0
                out["minutes_to_next"] = round(delta_min, 1)
        except Exception:
            pass
    return out


# ── Legacy text builders (kept for back-compat) ──────────────────────────────

def build_htf_context(df_4h: pd.DataFrame | None) -> str:
    if df_4h is None or len(df_4h) < 50:
        return "HTF data unavailable"
    last = df_4h.iloc[-1]
    e21, e50 = last.get("ema21"), last.get("ema50")
    rsi = last.get("rsi14")
    adx = last.get("adx")
    bias = "neutral"
    if pd.notna(e21) and pd.notna(e50):
        bias = "bullish" if e21 > e50 else "bearish"
    return (
        f"H4 close={float(last['close']):.2f}, EMA21={e21:.2f}, EMA50={e50:.2f} -> {bias}; "
        f"RSI14={rsi:.0f}, ADX={adx:.0f}"
    )


def build_ltf_context(df: pd.DataFrame | None) -> str:
    if df is None or len(df) < 30:
        return "LTF data unavailable"
    return (
        "LTF: " + _last_row_summary(
            df,
            ["close", "ema9", "ema21", "ema50", "rsi14", "hist", "adx", "plus_di", "minus_di",
             "bb_pctb", "atr14"],
        )
    )


def build_smc_context(df: pd.DataFrame | None) -> str:
    if df is None or len(df) < 30:
        return "SMC data unavailable"
    last = df.iloc[-1]
    parts = []
    for k in ["bull_sweep", "bear_sweep", "fvg_bull", "fvg_bear", "bos_up", "bos_dn"]:
        if last.get(k):
            parts.append(k)
    if pd.notna(last.get("prior_sh")):
        parts.append(f"prior_sh={float(last['prior_sh']):.2f}")
    if pd.notna(last.get("prior_sl")):
        parts.append(f"prior_sl={float(last['prior_sl']):.2f}")
    return "SMC marks: " + (", ".join(parts) if parts else "none active")


def build_intermarket_context(inter: dict) -> str:
    score = inter.get("score", 0.0)
    notes = []
    for name, c in (inter.get("components") or {}).items():
        if c.get("note"):
            notes.append(f"{name}: {c['note']}")
    return f"intermarket_score={score:+.2f}; " + "; ".join(notes[:5])


def build_cot_context(cot: dict) -> str:
    if not cot:
        return "no COT data"
    z = cot.get("z")
    if z is None:
        return f"COT data partial (no z-score)"
    label = 'extreme long' if z > 1.5 else 'extreme short' if z < -1.5 else 'normal'
    return f"COT MM net z52={z:+.2f} ({label})"


def build_news_context(in_blackout: bool, blackout_event, upcoming: list) -> str:
    if in_blackout and blackout_event:
        return f"IN BLACKOUT NOW: {getattr(blackout_event, 'title', '?')} ({getattr(blackout_event, 'when_utc', '?')})"
    if upcoming:
        u = upcoming[0]
        return (
            f"next high-impact event: {getattr(u, 'title', '?')} at {getattr(u, 'when_utc', '?')} "
            f"({getattr(u, 'currency', '?')}, {getattr(u, 'impact', '?')})"
        )
    return "no high-impact event in 48h"


# ─── Single-agent invoker ──────────────────────────────────────────────────────

@dataclass
class AgentRunConfig:
    enabled: bool = True
    provider: Optional[str] = None  # if None, use default
    model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 400
    weight: float = 1.0
    custom_prompt: Optional[str] = None  # override system prompt


SYSTEM_PROMPTS = {
    "htf_bias":            SYS_HTF_BIAS,
    "session_phase":       SYS_SESSION_PHASE,
    "ltf_technical":       SYS_LTF_TECHNICAL,
    "liquidity_smc":       SYS_LIQUIDITY_SMC,
    "order_flow":          SYS_ORDER_FLOW,
    "pattern_recognition": SYS_PATTERN_RECOGNITION,
    "volume_profile":      SYS_VOLUME_PROFILE,
    "news_proximity":      SYS_NEWS_PROXIMITY,
    "volatility":          SYS_VOLATILITY,
    "backtest_memory":     SYS_BACKTEST_MEMORY,
    "devils_advocate":     SYS_DEVILS_ADVOCATE,
    "synthesizer":         SYS_SYNTHESIZER,
}


def run_agent(
    name: str,
    user_prompt: str,
    router: LLMRouter,
    cfg: AgentRunConfig,
    default_provider: str,
    default_model: str,
) -> AgentVerdict:
    """Call a single agent, return AgentVerdict. Falls back to FLAT on any error."""
    label = AGENT_LABELS.get(name, name)
    if not cfg.enabled:
        return AgentVerdict(label, "FLAT", 0.0, ["agent disabled"])

    provider = cfg.provider or default_provider
    model = cfg.model or default_model
    system = cfg.custom_prompt or SYSTEM_PROMPTS.get(name, "")

    try:
        resp = router.chat(
            provider=provider,
            model=model,
            system=system,
            prompt=user_prompt,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            json_mode=False,
        )
    except LLMError as e:
        return AgentVerdict(label, "FLAT", 0.0, [f"LLM error: {e}"])
    except Exception as e:
        return AgentVerdict(label, "FLAT", 0.0, [f"unexpected error: {e}"])

    parsed = parse_json_loose(resp.text)
    if not parsed:
        return AgentVerdict(label, "FLAT", 0.0, [f"unparseable response: {resp.text[:160]}"])

    v, conf, reason = normalise_verdict(parsed)
    extras = []
    for k in ("red_flags", "key_levels", "primary_driver"):
        if parsed.get(k):
            extras.append(f"{k}={parsed[k]}")

    return AgentVerdict(
        label,
        v,
        conf,
        ([reason] if reason else []) + extras,
    )


# ─── Multi-agent orchestrator ──────────────────────────────────────────────────

@dataclass
class TierRunResult:
    verdicts: list[AgentVerdict] = field(default_factory=list)
    raw_outputs: dict[str, str] = field(default_factory=dict)


def _build_user_prompts(market_ctx: dict) -> dict[str, str]:
    """Build per-agent user prompts.

    IMPROVEMENT #1: each prompt now embeds STRUCTURED JSON of raw numerical
    values (close, ema21, atr14, rsi14, ...) instead of pre-formatted prose.
    LLMs hallucinate less when fed raw numbers vs narrative descriptions.

    The legacy text fields (htf_text, ltf_text, ...) are kept as a redundant
    human-readable layer so the agent has both views.
    """

    # Structured numerical dicts (new — primary signal source for agents)
    htf_num   = market_ctx.get("htf_numeric")   or {"available": False}
    ltf_num   = market_ctx.get("ltf_numeric")   or {"available": False}
    smc_num   = market_ctx.get("smc_numeric")   or {"available": False}
    inter_num = market_ctx.get("inter_numeric") or {}
    cot_num   = market_ctx.get("cot_numeric")   or {"available": False}
    news_num  = market_ctx.get("news_numeric")  or {}

    # Legacy text (back-compat, redundant context for readability)
    htf_text = market_ctx.get("htf_text", "")
    ltf_text = market_ctx.get("ltf_text", "")
    smc_text = market_ctx.get("smc_text", "")
    inter_text = market_ctx.get("inter_text", "")
    cot_text = market_ctx.get("cot_text", "")
    news_text = market_ctx.get("news_text", "")
    session = market_ctx.get("session", "?")
    regime = market_ctx.get("regime", "?")
    price = market_ctx.get("price", 0)
    timeframe_focus = market_ctx.get("timeframe_focus", "intraday")

    # Compact JSON to keep token count tight — we don't pretty-print
    def _j(d: dict) -> str:
        return json.dumps(d, separators=(",", ":"), default=str)

    base_block = (
        f"Market context (XAU/USD):\n"
        f"- price={price}, session={session}, regime={regime}, focus={timeframe_focus}\n"
        f"\n[STRUCTURED DATA - use these raw numbers for analysis, not the text below]\n"
        f"htf_data={_j(htf_num)}\n"
        f"ltf_data={_j(ltf_num)}\n"
        f"smc_data={_j(smc_num)}\n"
        f"intermarket_data={_j(inter_num)}\n"
        f"cot_data={_j(cot_num)}\n"
        f"news_data={_j(news_num)}\n"
        f"\n[Text summary - human-readable redundancy, prefer JSON above]\n"
        f"- HTF: {htf_text}\n"
        f"- LTF: {ltf_text}\n"
        f"- SMC: {smc_text}\n"
        f"- intermarket: {inter_text}\n"
        f"- COT: {cot_text}\n"
        f"- news: {news_text}\n"
    )

    backtest_text = market_ctx.get("backtest_text", "no historical data")

    return {
        "htf_bias":            base_block + "\nUsing htf_data JSON: check ema9/21/50/200 stack alignment, ADX strength, atr_ratio_vs_avg20 for vol regime, distance to swing_high_20/swing_low_20. Return HTF bias verdict.",
        "session_phase":       base_block + f"\nIs {session} session favourable for entry now? Use minutes_to_next from news_data to detect London Fix proximity. Return verdict.",
        "ltf_technical":       base_block + "\nUsing ltf_data JSON: confirm EMA stack agrees with HTF bias, check rsi14 not in extreme zone, candle_body_pct_of_range > 0.6 for momentum. Need 3+ confluence.",
        "liquidity_smc":       base_block + "\nUsing smc_data JSON: identify bull_sweep_recent5/bear_sweep_recent5, active FVGs, distance from prior_swing_high/prior_swing_low. Return verdict.",
        "order_flow":          base_block + "\nUsing cot_data + intermarket_data: check z_score_52w for positioning extremes, intermarket score for confluence. Return verdict.",
        "pattern_recognition": base_block + "\nIdentify any active classical chart pattern (H&S, triangles, flags, double top/bottom) from price action. Use ltf_data + htf_data for context. Return pattern name + verdict.",
        "volume_profile":      base_block + "\nWhere is price relative to POC / VAH / VAL? Without volume profile data, fall back to swing_high_20/swing_low_20 from htf_data as proxy. Return verdict + target.",
        "news_proximity":      base_block + "\nUsing news_data JSON: if minutes_to_next is within 15/30/60 min of high-impact event, block. If in_blackout=true, hard veto.",
        "volatility":          base_block + "\nUsing htf_data.atr_ratio_vs_avg20: >2.0 = extreme block. <0.5 = quiet, scalper-unfriendly. Check bb_width regime too.",
        "backtest_memory":     base_block + f"\nHistorical similar setups context: {backtest_text}\nReturn prior probability verdict based on past performance.",
    }


def run_pipeline(
    router: LLMRouter,
    agent_configs: dict[str, AgentRunConfig],
    market_ctx: dict,
    default_provider: str,
    default_model: str,
    parallel: bool = True,
) -> dict[str, AgentVerdict]:
    """Run tiers 1-3 + Devil's Advocate. Synthesizer is optional and called separately.

    Returns dict keyed by agent_name -> AgentVerdict.
    """
    prompts = _build_user_prompts(market_ctx)
    tier_agents = [
        # Tier 1: Bias setting
        ["htf_bias", "session_phase"],
        # Tier 2: Trigger hunting (5 specialists in parallel)
        ["ltf_technical", "liquidity_smc", "order_flow", "pattern_recognition", "volume_profile"],
        # Tier 3: Risk validation + historical prior
        ["news_proximity", "volatility", "backtest_memory"],
    ]

    results: dict[str, AgentVerdict] = {}

    def _invoke(name: str) -> tuple[str, AgentVerdict]:
        cfg = agent_configs.get(name, AgentRunConfig())
        v = run_agent(name, prompts[name], router, cfg, default_provider, default_model)
        return name, v

    for tier in tier_agents:
        if parallel:
            with ThreadPoolExecutor(max_workers=len(tier)) as ex:
                futs = [ex.submit(_invoke, n) for n in tier]
                for f in as_completed(futs):
                    name, v = f.result()
                    results[name] = v
        else:
            for n in tier:
                name, v = _invoke(n)
                results[name] = v

    # Devil's advocate uses the prior verdicts in its prompt
    others_summary = "\n".join(
        f"- {AGENT_LABELS[k]}: {results[k].verdict} conf={results[k].confidence:.2f} — {' '.join(results[k].reasoning[:2])}"
        for k in results
    )
    devil_prompt = (
        prompts["htf_bias"].split("\n\nReturn")[0]  # reuse base context
        + "\n\nPrior agents' verdicts:\n"
        + others_summary
        + "\n\nArgue against consensus. Decide if VETO."
    )
    devil_cfg = agent_configs.get("devils_advocate", AgentRunConfig())
    _, devil = _invoke_with_prompt(
        "devils_advocate", devil_prompt, router, devil_cfg, default_provider, default_model
    )
    results["devils_advocate"] = devil

    return results


def _invoke_with_prompt(name, prompt, router, cfg, default_provider, default_model):
    v = run_agent(name, prompt, router, cfg, default_provider, default_model)
    return name, v


# ─── Synthesizer (final decision) ──────────────────────────────────────────────

@dataclass
class SynthResult:
    final_action: str
    confidence: float
    signal_strength: str
    primary_driver: str
    reasoning_chain: list[str]
    risks: list[str]
    agents_summary: list[dict]

    def to_dict(self) -> dict:
        return {
            "final_action": self.final_action,
            "confidence": round(self.confidence, 3),
            "signal_strength": self.signal_strength,
            "primary_driver": self.primary_driver,
            "reasoning_chain": self.reasoning_chain,
            "risks": self.risks,
            "agents": self.agents_summary,
        }


def synthesize(
    results: dict[str, AgentVerdict],
    market_ctx: dict,
    router: LLMRouter,
    cfg: AgentRunConfig,
    default_provider: str,
    default_model: str,
    use_llm: bool = True,
) -> SynthResult:
    """Combine all agent verdicts into a final decision.
    If use_llm, ask synthesizer LLM. Otherwise apply rule-based aggregation.
    """
    # Always compute the rule-based baseline first (fallback / sanity).
    # IMPROVEMENT #3: pass market_ctx so rule synth can weight per regime.
    rule_synth = _rule_synthesize(results, market_ctx)

    if not use_llm or not cfg.enabled:
        return rule_synth

    others_summary = "\n".join(
        f"- {AGENT_LABELS[k]}: {results[k].verdict} (conf={results[k].confidence:.2f}, weight={cfg.weight}) — {' '.join(results[k].reasoning[:2])}"
        for k in results
    )

    base_block = (
        f"Market context: price={market_ctx.get('price')}, session={market_ctx.get('session')}, "
        f"regime={market_ctx.get('regime')}, focus={market_ctx.get('timeframe_focus')}\n"
        f"HTF: {market_ctx.get('htf_text','')}\n"
        f"LTF: {market_ctx.get('ltf_text','')}\n"
        f"SMC: {market_ctx.get('smc_text','')}\n"
        f"news: {market_ctx.get('news_text','')}\n"
    )

    prompt = (
        base_block
        + "\nAgent verdicts:\n"
        + others_summary
        + "\n\nProduce final decision."
    )

    try:
        resp = router.chat(
            provider=cfg.provider or default_provider,
            model=cfg.model or default_model,
            system=cfg.custom_prompt or SYS_SYNTHESIZER,
            prompt=prompt,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            json_mode=False,
        )
        parsed = parse_json_loose(resp.text)
        if not parsed:
            return rule_synth
        action = (parsed.get("action") or parsed.get("verdict") or "FLAT").upper()
        if action not in {"LONG", "SHORT", "FLAT"}:
            action = "FLAT"
        try:
            conf = float(parsed.get("confidence", rule_synth.confidence))
        except (TypeError, ValueError):
            conf = rule_synth.confidence
        conf = max(0.0, min(1.0, conf))
        strength = parsed.get("signal_strength") or _classify_strength(conf, _agree_count(results, action))
        return SynthResult(
            final_action=action,
            confidence=conf,
            signal_strength=strength,
            primary_driver=parsed.get("primary_driver") or rule_synth.primary_driver,
            reasoning_chain=list(parsed.get("reasoning_chain") or rule_synth.reasoning_chain),
            risks=list(parsed.get("risks") or rule_synth.risks),
            agents_summary=rule_synth.agents_summary,
        )
    except Exception:
        return rule_synth


def _agree_count(results: dict[str, AgentVerdict], action: str) -> int:
    return sum(1 for v in results.values() if v.verdict == action)


def _classify_strength(conf: float, agree: int) -> str:
    if conf >= 0.80 and agree >= 4:
        return "STRONG"
    if conf >= 0.65 and agree >= 3:
        return "NORMAL"
    if conf >= 0.50:
        return "WEAK"
    return "FLAT"


# IMPROVEMENT #3: Per-regime agent weights.
# Different regimes favor different signal sources:
#  - Trending: HTF bias + LTF technical dominate (trend-following).
#  - Ranging:  Liquidity/SMC + Volume Profile + session phase dominate (mean-reversion).
#  - Volatile: News + Volatility weights up (risk control), trend signals down.
#  - Quiet:    Same as ranging but with overall confidence haircut.
#
# Weights normalize to ~1.0 baseline. Higher = more influence in vote+confidence.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "trending_up": {
        "htf_bias":            1.6,
        "ltf_technical":       1.4,
        "session_phase":       0.9,
        "liquidity_smc":       1.0,
        "order_flow":          1.1,
        "pattern_recognition": 1.0,
        "volume_profile":      0.8,
    },
    "trending_dn": {
        "htf_bias":            1.6,
        "ltf_technical":       1.4,
        "session_phase":       0.9,
        "liquidity_smc":       1.0,
        "order_flow":          1.1,
        "pattern_recognition": 1.0,
        "volume_profile":      0.8,
    },
    "ranging": {
        "htf_bias":            0.7,   # trend agents lose value in chop
        "ltf_technical":       0.9,
        "session_phase":       1.3,
        "liquidity_smc":       1.5,   # SMC sweeps shine in range
        "order_flow":          1.1,
        "pattern_recognition": 1.0,
        "volume_profile":      1.5,   # POC/VAH/VAL most useful here
    },
    "volatile": {
        "htf_bias":            0.8,
        "ltf_technical":       0.7,   # whipsaw risk
        "session_phase":       1.0,
        "liquidity_smc":       1.2,
        "order_flow":          1.3,
        "pattern_recognition": 0.8,
        "volume_profile":      0.9,
    },
    "quiet": {
        "htf_bias":            0.9,
        "ltf_technical":       0.9,
        "session_phase":       1.0,
        "liquidity_smc":       1.2,
        "order_flow":          1.1,
        "pattern_recognition": 1.0,
        "volume_profile":      1.4,
    },
}

# Default weights when regime unknown
DEFAULT_REGIME_WEIGHTS = {
    "htf_bias":            1.0,
    "ltf_technical":       1.0,
    "session_phase":       1.0,
    "liquidity_smc":       1.0,
    "order_flow":          1.0,
    "pattern_recognition": 1.0,
    "volume_profile":      1.0,
}

DIRECTIONAL_AGENTS = (
    "htf_bias", "session_phase", "ltf_technical", "liquidity_smc",
    "order_flow", "pattern_recognition", "volume_profile",
)


def _regime_weights(regime: str | None) -> dict[str, float]:
    if not regime:
        return DEFAULT_REGIME_WEIGHTS
    return REGIME_WEIGHTS.get(regime, DEFAULT_REGIME_WEIGHTS)


def _rule_synthesize(results: dict[str, AgentVerdict], market_ctx: dict | None = None) -> SynthResult:
    """Deterministic fallback synthesizer with regime-aware weighted voting.

    IMPROVEMENT #3: replaces flat majority (need 3 of 5 agents) with weighted
    score per regime. An agent's "vote weight" = its confidence × regime_weight.
    Action chosen by highest total weight; FLAT if no clear winner (margin < 1.0).
    """
    devil = results.get("devils_advocate")
    news = results.get("news_proximity")
    regime = (market_ctx or {}).get("regime", "")
    weights = _regime_weights(regime)

    # ── Hard veto: news ────────────────────────────────────────────────────
    if news and news.verdict == "FLAT" and news.confidence >= 0.7:
        return SynthResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            primary_driver="news block",
            reasoning_chain=[f"News block: {news.reasoning[0] if news.reasoning else ''}"],
            risks=[news.reasoning[0] if news.reasoning else "imminent news"],
            agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
        )

    # ── Hard veto: devil's advocate ────────────────────────────────────────
    if devil and devil.verdict == "FLAT" and devil.confidence >= 0.8:
        return SynthResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            primary_driver="devil veto",
            reasoning_chain=[f"Devil veto: {devil.reasoning[0] if devil.reasoning else ''}"],
            risks=devil.reasoning[:3],
            agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
        )

    # ── Weighted directional voting (IMPROVEMENT #3) ───────────────────────
    long_score  = 0.0
    short_score = 0.0
    long_n  = 0
    short_n = 0
    for k in DIRECTIONAL_AGENTS:
        v = results.get(k)
        if not v:
            continue
        w = weights.get(k, 1.0)
        if v.verdict == "LONG":
            long_score += v.confidence * w
            long_n += 1
        elif v.verdict == "SHORT":
            short_score += v.confidence * w
            short_n += 1

    # Decide direction by which side has more weighted score (margin must be > 0.5)
    margin = abs(long_score - short_score)
    min_margin = 0.5    # require meaningful weight diff to avoid coinflips
    min_score  = 1.5    # at least 1.5 cumulative weighted-confidence (e.g. 2 agents with 0.75)

    if long_score > short_score and margin >= min_margin and long_score >= min_score:
        action = "LONG"
        agree = long_n
        winning_score = long_score
    elif short_score > long_score and margin >= min_margin and short_score >= min_score:
        action = "SHORT"
        agree = short_n
        winning_score = short_score
    else:
        return SynthResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            primary_driver="no_weighted_consensus",
            reasoning_chain=[
                f"regime={regime} long_score={long_score:.2f} short_score={short_score:.2f} "
                f"margin={margin:.2f} (need >={min_margin} and winner>={min_score})"
            ],
            risks=[],
            agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
        )

    # Normalized confidence: winning_score / max possible weighted score for that side
    # max_possible = sum of all weights (if every agent had conf=1.0 in this direction)
    max_possible = sum(weights.get(k, 1.0) for k in DIRECTIONAL_AGENTS if k in results)
    normalized_conf = winning_score / max_possible if max_possible > 0 else 0.0
    normalized_conf = max(0.0, min(1.0, normalized_conf))

    # Devil haircut
    if devil and devil.verdict != action:
        red_flag_count = len([r for r in (devil.reasoning or []) if r])
        normalized_conf = max(0.0, normalized_conf - 0.05 - 0.03 * red_flag_count)

    # Backtest memory haircut (if it disagrees → reduce conf)
    bt = results.get("backtest_memory")
    if bt and bt.verdict == "FLAT" and bt.confidence >= 0.5:
        normalized_conf = max(0.0, normalized_conf - 0.05)

    strength = _classify_strength(normalized_conf, agree)

    # Primary driver: highest weighted contribution toward action
    primary_key = max(
        (k for k in DIRECTIONAL_AGENTS
         if k in results and results[k].verdict == action),
        key=lambda k: results[k].confidence * weights.get(k, 1.0),
        default=None,
    )
    primary = AGENT_LABELS.get(primary_key, "mixed") if primary_key else "mixed"

    chain = [
        f"regime={regime}, weights tuned for this regime",
        f"weighted_long={long_score:.2f} weighted_short={short_score:.2f} margin={margin:.2f}",
    ]
    chain.extend(
        f"[{v.name}] {v.verdict} conf={v.confidence:.2f} w={weights.get(k, 1.0):.1f}: {' '.join(v.reasoning[:1])}"
        for k, v in results.items()
    )
    risks = list(devil.reasoning) if devil and devil.reasoning else []

    return SynthResult(
        final_action=action,
        confidence=round(normalized_conf, 3),
        signal_strength=strength,
        primary_driver=primary,
        reasoning_chain=chain,
        risks=risks,
        agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
    )
