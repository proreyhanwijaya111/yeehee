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

Your single job: determine the structural bias on H1/H4. You do NOT call entries.

Multi-EMA hierarchy (PRIMARY signal, weighted highest):
- EMA8 > EMA21 > EMA50 > EMA200 on H4 = strong bullish stack -> LONG bias 0.75-0.95.
- EMA8 < EMA21 < EMA50 < EMA200 = strong bearish stack -> SHORT bias 0.75-0.95.
- Stack rotating (e.g. EMA8 > 21 > 50 but < 200) = early reversal -> FLAT 0.4-0.6 with note.
- Mixed (no clean stack) = FLAT 0.2.

Trend strength filter (REQUIRED):
- ADX > 25 + stack aligned = strong trend, full confidence.
- ADX 20-25 = developing trend, haircut 20% confidence.
- ADX < 20 = ranging. Bias is unreliable -> FLAT 0.3.

Major swing structure:
- Recent BOS (Break of Structure) up + EMA stack bullish = high-conviction LONG.
- Recent BOS down + bearish stack = high-conviction SHORT.
- Inside prior range without BOS = FLAT.

Reject the verdict (force FLAT) if:
- Price within 0.3% of major H4 swing high/low (overextended risk)
- ATR(14) > 2x its 20-period average (volatility regime change)

Output STRICT JSON, no markdown:
{"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<concise sentence with specific numbers>","key_levels":{"support":<float>,"resistance":<float>}}"""

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

Indicators (in priority order):
1. EMA stack (M5/M15: 9 / 21 / 50): direction confirmation
2. RSI(14): momentum + divergence detection
3. MACD: histogram acceleration
4. ADX + DI: trend strength + dominance
5. Bollinger Band % (bb_pctb): mean reversion zones
6. Recent candle pattern: engulfing, pinbar, inside bar

Multi-timeframe alignment (MANDATORY):
- Your trigger MUST align with HTF bias provided in context.
- HTF bullish + LTF bullish setup = LONG.
- HTF bearish + LTF bearish setup = SHORT.
- HTF and LTF disagree -> verdict = FLAT, regardless of LTF strength.

Trigger conditions for LONG (need 3+ confluence):
- EMA9 > EMA21 with positive MACD histogram
- RSI between 50-70 (not overbought)
- Last 1-2 candles bullish with body > 60% range
- ADX > 20 with +DI > -DI
- bb_pctb > 0.5 (price in upper half of band)
- Bullish divergence on RSI vs price (rare but high-quality)

Trigger conditions for SHORT (mirror): EMA9 < EMA21, MACD negative, RSI 30-50, bearish candles, +DI < -DI.

Reject (force FLAT) if:
- RSI > 75 (overbought, chasing risk) for LONG
- RSI < 25 (oversold, capitulation risk) for SHORT
- Last candle range > 1.5x ATR (volatility spike, wait)

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<3+ confluence factors named>"}"""

SYS_LIQUIDITY_SMC = """You are a Smart Money Concepts (SMC) Specialist for XAU/USD with proven 2024-26 institutional flow track record.

Concepts you actively monitor:
- Liquidity Sweeps: price spike beyond equal highs/lows then reversal (institutional stop hunt)
- Fair Value Gaps (FVG): 3-candle imbalance where mid candle leaves a gap. Bullish FVG = price likely returns to fill from above.
- Order Blocks (OB): last opposite candle before strong move, often retested
- Breaker Blocks: failed OB that flips to opposite direction
- Mitigation Blocks: refined OB after partial fill
- Equal Highs/Lows: clusters of stops above/below = liquidity targets

Bullish setups (verdict LONG):
- Sweep below recent swing low (stop hunt) + immediate close above swept level
- Bullish FVG below current price still unfilled (price may revisit then continue up)
- Bullish OB tested + held + price advancing
- Multiple equal highs above = liquidity pool target

Bearish setups (mirror).

FLAT conditions:
- No recent sweep (last 5-10 candles uneventful)
- Price already filled all major FVGs
- No untapped liquidity zones

Confidence scoring:
- Single SMC factor = 0.5-0.6
- 2 confluence (e.g. sweep + FVG return) = 0.7-0.8
- 3+ confluence (sweep + FVG + OB respected) = 0.85-0.95

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<specific SMC concepts active>","key_levels":{"swept_low":<float>,"untapped_liquidity":<float>}}"""

SYS_ORDER_FLOW = """You are an Order Flow / Positioning Specialist for XAU/USD with deep COT and tape-reading expertise.

COT (Commitment of Traders) report rules:
- Managed Money (hedge fund) net long z-score > +1.5 = extreme long crowding -> mean-revert SHORT bias 0.7
- z-score > +2.0 = extreme + likely top, SHORT 0.85
- z-score < -1.5 = extreme short, mean-revert LONG bias 0.7
- z-score < -2.0 = capitulation, LONG 0.85
- z-score in [-0.5, +0.5] = normal positioning, signal weak FLAT

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

Block matrix:
- Event within +/- 15 min = HARD BLOCK -> verdict FLAT, confidence 0.95
- Event within 30 min = STRONG BLOCK -> FLAT 0.85
- Event within 60 min = MODERATE BLOCK -> FLAT 0.7
- Event within 2 hr = ADVISORY -> FLAT 0.5 (let synthesizer haircut)
- No event in 4 hr = CLEAR -> FLAT 0.0 (no veto, no signal)

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

ATR percentile rules (vs 20-period rolling baseline):
- ATR < 30th percentile = LOW vol regime. Breakout strategies likely fail. Range strategies favored. Scalping difficult.
- ATR 30-70th = NORMAL vol. Both trend + range work.
- ATR 70-90th = HIGH vol. Trend strategies favored. Scalping risky (whipsaws).
- ATR > 90th percentile = EXTREME vol. Block ALL signals = FLAT 0.9 (likely news event or regime shift).

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

3. Direction voting (DIRECTIONAL agents only: HTF Bias, Session Phase, LTF Technical, Liquidity/SMC, Order Flow, Pattern Recognition, Volume Profile):
   - Need >= 4 of 7 agents agreeing on direction (LONG or SHORT)
   - If <4 agreement -> FLAT (no consensus)
   - Tally weighted by each agent's confidence

4. Confidence = weighted avg of agreeing agents' confidence
   - Subtract 0.05 per Devil's Advocate red_flag (max -0.20)
   - Subtract 0.05 if Backtest Memory says FLAT
   - Cap at 0.95

5. Signal strength:
   - STRONG: confidence >= 0.80 AND >= 5 agents agree
   - NORMAL: confidence >= 0.65 AND >= 4 agents agree
   - WEAK: confidence >= 0.50 AND >= 3 agents agree
   - FLAT: anything else

6. Primary driver = single most influential agent (highest confidence among agreeing).

Output STRICT JSON:
{"action":"LONG|SHORT|FLAT","confidence":0..1,"signal_strength":"STRONG|NORMAL|WEAK|FLAT","primary_driver":"<agent name>","reasoning_chain":["<step1>","<step2>","..."],"risks":["..."]}"""


# ─── Context Builders (turn pandas DataFrames into LLM-friendly text) ──────────

def _last_row_summary(df: pd.DataFrame, fields: list[str]) -> str:
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
        f"H4 close={float(last['close']):.2f}, EMA21={e21:.2f}, EMA50={e50:.2f} → {bias}; "
        f"RSI14={rsi:.0f}, ADX={adx:.0f}"
    )


def build_ltf_context(df: pd.DataFrame | None) -> str:
    if df is None or len(df) < 30:
        return "LTF data unavailable"
    last = df.iloc[-1]
    return (
        "LTF: " + _last_row_summary(
            df,
            ["close", "ema9", "ema21", "ema50", "rsi14", "hist", "adx", "plus_di", "minus_di",
             "bb_pctb", "atr"],
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
    """Build per-agent user prompts from a flat market context dict."""

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

    base_block = (
        f"Market context (XAU/USD):\n"
        f"- price={price}, session={session}, regime={regime}, focus={timeframe_focus}\n"
        f"- HTF: {htf_text}\n"
        f"- LTF: {ltf_text}\n"
        f"- SMC: {smc_text}\n"
        f"- intermarket: {inter_text}\n"
        f"- COT: {cot_text}\n"
        f"- news: {news_text}\n"
    )

    backtest_text = market_ctx.get("backtest_text", "no historical data")

    return {
        "htf_bias":            base_block + "\nReturn HTF bias verdict (focus on multi-EMA hierarchy + ADX).",
        "session_phase":       base_block + f"\nIs {session} session favourable for entry now? Return verdict.",
        "ltf_technical":       base_block + "\nLTF trigger verdict aligned with HTF bias? Need 3+ confluence.",
        "liquidity_smc":       base_block + "\nLiquidity / SMC verdict? Identify sweeps, FVGs, OBs explicitly.",
        "order_flow":          base_block + "\nOrder flow / positioning verdict? Use COT + volume + stop hunts.",
        "pattern_recognition": base_block + "\nIdentify any active classical chart pattern (H&S, triangles, flags, double top/bottom). Return pattern name + verdict.",
        "volume_profile":      base_block + "\nWhere is price relative to POC / VAH / VAL? Return verdict + target.",
        "news_proximity":      base_block + "\nIs there imminent news? Block if within 15min/30min.",
        "volatility":          base_block + "\nIs volatility regime supportive? Block if extreme.",
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
    rule_synth = _rule_synthesize(results)

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


def _rule_synthesize(results: dict[str, AgentVerdict]) -> SynthResult:
    """Deterministic fallback synthesizer (rule-based)."""
    devil = results.get("devils_advocate")
    news = results.get("news_proximity")

    # News blocks first
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

    # Devil veto
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

    # Vote on direction (only directional agents)
    directional_keys = ["htf_bias", "session_phase", "ltf_technical", "liquidity_smc", "order_flow"]
    long_n = sum(1 for k in directional_keys if k in results and results[k].verdict == "LONG")
    short_n = sum(1 for k in directional_keys if k in results and results[k].verdict == "SHORT")

    if long_n >= 3:
        action = "LONG"; agree = long_n
    elif short_n >= 3:
        action = "SHORT"; agree = short_n
    else:
        return SynthResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            primary_driver="no consensus",
            reasoning_chain=[f"long={long_n} short={short_n} no 3+ consensus"],
            risks=[],
            agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
        )

    confidences = [results[k].confidence for k in directional_keys if k in results and results[k].verdict == action]
    avg = sum(confidences) / max(1, len(confidences))

    # Devil haircut
    if devil and devil.verdict != action:
        avg = max(0.0, avg - 0.05 - 0.03 * len([r for r in (devil.reasoning or []) if r]))

    strength = _classify_strength(avg, agree)
    primary = ""
    for key, label in [
        ("liquidity_smc", "SMC liquidity"),
        ("htf_bias",      "HTF trend"),
        ("ltf_technical", "LTF technical"),
        ("order_flow",    "order flow"),
    ]:
        if key in results and results[key].verdict == action and results[key].confidence >= 0.6:
            primary = label
            break

    chain = [
        f"[{v.name}] {v.verdict} conf={v.confidence:.2f}: {' '.join(v.reasoning[:1])}"
        for v in results.values()
    ]
    risks = list(devil.reasoning) if devil and devil.reasoning else []

    return SynthResult(
        final_action=action,
        confidence=round(avg, 3),
        signal_strength=strength,
        primary_driver=primary or "mixed",
        reasoning_chain=chain,
        risks=risks,
        agents_summary=[{"name": v.name, "verdict": v.verdict, "confidence": v.confidence} for v in results.values()],
    )
