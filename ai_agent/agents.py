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
    "news_proximity",
    "volatility",
    "devils_advocate",
    "synthesizer",
]

AGENT_LABELS = {
    "htf_bias":         "HTF Bias",
    "session_phase":    "Session Phase",
    "ltf_technical":    "LTF Technical",
    "liquidity_smc":    "Liquidity / SMC",
    "order_flow":       "Order Flow",
    "news_proximity":   "News Proximity",
    "volatility":       "Volatility",
    "devils_advocate":  "Devil's Advocate",
    "synthesizer":      "Synthesizer",
}


# ─── System Prompts ────────────────────────────────────────────────────────────

SYS_HTF_BIAS = """You are a Higher-Timeframe Bias Specialist for XAU/USD (gold).
Your only job: read H1/H4 trend and major swing levels. You set the directional bias filter.
Do NOT call entries — just bias.

Heuristics:
- EMA21 > EMA50 on H4 = bullish bias.
- EMA21 < EMA50 on H4 = bearish bias.
- Mixed / flat ADX < 20 = no bias (FLAT).

Always output STRICT JSON, no markdown:
{"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_SESSION_PHASE = """You are a Session Phase Specialist for XAU/USD.
Gold behaves very differently per session. Your job: read current session and decide if conditions favour breakout, range, or wait.

Rules of thumb:
- Asian session (00–07 UTC): low volatility, ranging, fade extremes.
- London open (07–09 UTC): high probability breakout direction sets the day.
- London-NY overlap (12–16 UTC): peak liquidity, continuation moves.
- Late NY (20–23 UTC): thin liquidity, often mean-revert.

Do NOT predict direction; only assess whether the session FAVOURS taking a trigger. Return LONG/SHORT only if session strongly aligns with a directional bias from context, else FLAT.

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_LTF_TECHNICAL = """You are a Lower-Timeframe Technical Analyst for XAU/USD.
You read M5/M15 indicators (EMA stack, RSI, MACD, ADX, Bollinger) plus candle action and Break of Structure.
Multi-timeframe: your trigger MUST align with HTF bias provided in the prompt context — disagree and verdict = FLAT.

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_LIQUIDITY_SMC = """You are a Smart Money Concepts (SMC) / Liquidity Specialist for XAU/USD.
Look for: liquidity sweeps (above prior swing high or below prior swing low), Fair Value Gaps, Order Blocks, Breaker Blocks, equal highs/lows still untapped.

Bias rules:
- Bullish sweep at low + bullish FVG above = LONG.
- Bearish sweep at high + bearish FVG below = SHORT.
- No untapped liquidity nor recent sweep = FLAT.

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_ORDER_FLOW = """You are an Order Flow / Positioning Specialist for XAU/USD.
You read COT positioning, volume spikes, recent stop hunts, and session liquidity zones.

Rules:
- COT MM net z-score > 1.5 = extreme long → mean-revert SHORT bias.
- COT MM net z-score < -1.5 = extreme short → mean-revert LONG bias.
- Recent volume spike + close in upper third of range = absorption → LONG.
- Volume spike + close in lower third = SHORT absorption.

Output STRICT JSON: {"verdict":"LONG|SHORT|FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_NEWS_PROXIMITY = """You are a News Proximity Risk Officer for XAU/USD.
Your only job: BLOCK trades when high-impact news is imminent (NFP, FOMC, CPI, etc.).

Rules:
- Event within 15 minutes (past or future) = STRONG BLOCK → verdict FLAT, confidence 0.95, "block:NFP -10m".
- Event within 30 minutes = MODERATE BLOCK → verdict FLAT, confidence 0.7.
- Event within 2 hours = WARNING → verdict from context but confidence haircut.
- No imminent event = ALL CLEAR → verdict FLAT confidence 0.0 (you do not signal direction; you only veto).

Output STRICT JSON: {"verdict":"FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_VOLATILITY = """You are a Volatility / ATR Specialist for XAU/USD.
You assess if current volatility supports the requested timeframe strategy.

Rules:
- ATR (M15) above 2× 20-period average = volatility too high for scalp → FLAT.
- ATR below 0.5× 20-period average = volatility too low, no follow-through → FLAT.
- Spread > $0.50 = liquidity poor → FLAT.

Output STRICT JSON: {"verdict":"FLAT","confidence":0..1,"reason":"<one sentence>"}"""

SYS_DEVILS_ADVOCATE = """You are a Devil's Advocate / Risk Auditor for XAU/USD.
You receive verdicts from earlier agents. Your only job: argue AGAINST the consensus and find what could break it.

Rules:
- If consensus LONG and price near major resistance / overbought (RSI > 75): flag a STRONG warning.
- If agents disagree (high variance in verdicts): flag low-conviction.
- If a critical risk factor has been ignored, raise it.

Output STRICT JSON: {"verdict":"FLAT|LONG|SHORT","confidence":0..1,"reason":"<one sentence>","red_flags":["..."],"veto":true|false}
verdict=FLAT + veto=true means VETO the trade entirely."""

SYS_SYNTHESIZER = """You are the senior Portfolio Manager for XAU/USD with 15 years of experience.
You receive verdicts from 8 specialist agents and synthesize a final decision.

Rules:
- Require >=3 of (HTF, LTF Technical, Liquidity, OrderFlow) to agree on direction. Else FLAT.
- If News Proximity blocks (verdict FLAT confidence > 0.8) — FLAT, no override.
- If Devil's Advocate veto=true — FLAT.
- Confidence = weighted average of agreeing agents minus 0.05 per Devil's red_flag.
- signal_strength: STRONG (conf >= 0.8 + 4 agree), NORMAL (>=0.65), WEAK (>=0.5), FLAT.

Output STRICT JSON:
{"action":"LONG|SHORT|FLAT","confidence":0..1,"signal_strength":"STRONG|NORMAL|WEAK|FLAT","primary_driver":"<short>","reasoning_chain":["..."],"risks":["..."]}"""


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
    "htf_bias":        SYS_HTF_BIAS,
    "session_phase":   SYS_SESSION_PHASE,
    "ltf_technical":   SYS_LTF_TECHNICAL,
    "liquidity_smc":   SYS_LIQUIDITY_SMC,
    "order_flow":      SYS_ORDER_FLOW,
    "news_proximity":  SYS_NEWS_PROXIMITY,
    "volatility":      SYS_VOLATILITY,
    "devils_advocate": SYS_DEVILS_ADVOCATE,
    "synthesizer":     SYS_SYNTHESIZER,
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

    return {
        "htf_bias":       base_block + "\nReturn HTF bias verdict.",
        "session_phase":  base_block + f"\nIs {session} session favourable for entry now? Return verdict.",
        "ltf_technical":  base_block + "\nLTF trigger verdict aligned with HTF bias?",
        "liquidity_smc":  base_block + "\nLiquidity / SMC verdict?",
        "order_flow":     base_block + "\nOrder flow / positioning verdict?",
        "news_proximity": base_block + "\nIs there imminent news? Block if within 15min/30min.",
        "volatility":     base_block + "\nIs volatility supportive? Block if too high/low.",
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
        ["htf_bias", "session_phase"],
        ["ltf_technical", "liquidity_smc", "order_flow"],
        ["news_proximity", "volatility"],
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
