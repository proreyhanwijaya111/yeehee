"""Rule-based ensemble — works without API key. Acts as the 4-agent debate using deterministic logic.
Same output schema as Claude-based agent so dashboard tidak peduli mana yg jalan."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import Signal, Side, Style


@dataclass
class AgentVerdict:
    name: str
    verdict: str            # "LONG" | "SHORT" | "FLAT"
    confidence: float       # 0..1
    reasoning: list[str] = field(default_factory=list)


@dataclass
class DebateResult:
    final_action: str
    confidence: float
    signal_strength: str    # WEAK / NORMAL / STRONG / NEWS_STRONG / NEWS_AVOID
    agents: list[AgentVerdict] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    primary_driver: str = ""

    def to_dict(self) -> dict:
        return {
            "final_action": self.final_action,
            "confidence": self.confidence,
            "signal_strength": self.signal_strength,
            "agents": [asdict(a) for a in self.agents],
            "reasoning_chain": self.reasoning_chain,
            "risks": self.risks,
            "primary_driver": self.primary_driver,
        }


def _agent_technical(df: pd.DataFrame, df_htf: Optional[pd.DataFrame]) -> AgentVerdict:
    if df is None or len(df) < 50:
        return AgentVerdict("TechnicalAnalyst", "FLAT", 0.0, ["insufficient data"])

    last = df.iloc[-1]
    reasons: list[str] = []
    long_score = 0
    short_score = 0

    e9, e21, e50 = last.get("ema9"), last.get("ema21"), last.get("ema50")
    if pd.notna(e9) and pd.notna(e21) and pd.notna(e50):
        if e9 > e21 > e50:
            long_score += 2; reasons.append("EMA9>21>50 bullish stack")
        elif e9 < e21 < e50:
            short_score += 2; reasons.append("EMA9<21<50 bearish stack")

    rsi_v = last.get("rsi14")
    if pd.notna(rsi_v):
        if 50 < rsi_v < 70:
            long_score += 1; reasons.append(f"RSI {rsi_v:.0f} bullish zone")
        elif 30 < rsi_v < 50:
            short_score += 1; reasons.append(f"RSI {rsi_v:.0f} bearish zone")

    hist = last.get("hist")
    if pd.notna(hist):
        if hist > 0:
            long_score += 1; reasons.append("MACD hist > 0")
        elif hist < 0:
            short_score += 1; reasons.append("MACD hist < 0")

    adx_v = last.get("adx", 0)
    if pd.notna(adx_v) and adx_v > 25:
        plus_di, minus_di = last.get("plus_di", 0), last.get("minus_di", 0)
        if plus_di > minus_di:
            long_score += 1; reasons.append(f"ADX={adx_v:.0f} +DI lead")
        else:
            short_score += 1; reasons.append(f"ADX={adx_v:.0f} -DI lead")

    if last.get("bull_sweep", False):
        long_score += 1; reasons.append("SMC bullish liquidity sweep")
    if last.get("bear_sweep", False):
        short_score += 1; reasons.append("SMC bearish liquidity sweep")
    if last.get("fvg_bull", False):
        long_score += 0.5; reasons.append("Bullish FVG")
    if last.get("fvg_bear", False):
        short_score += 0.5; reasons.append("Bearish FVG")
    if last.get("bos_up", False):
        long_score += 1; reasons.append("BOS up")
    if last.get("bos_dn", False):
        short_score += 1; reasons.append("BOS down")

    if df_htf is not None and len(df_htf) > 50:
        htf = df_htf.iloc[-1]
        if pd.notna(htf.get("ema21")) and pd.notna(htf.get("ema50")):
            if htf["ema21"] > htf["ema50"]:
                long_score += 1; reasons.append("HTF trend bullish")
            else:
                short_score += 1; reasons.append("HTF trend bearish")

    if long_score >= short_score + 2:
        return AgentVerdict("TechnicalAnalyst", "LONG", min(0.5 + long_score * 0.06, 0.95), reasons)
    if short_score >= long_score + 2:
        return AgentVerdict("TechnicalAnalyst", "SHORT", min(0.5 + short_score * 0.06, 0.95), reasons)
    return AgentVerdict("TechnicalAnalyst", "FLAT", 0.3, reasons + ["no clear technical edge"])


def _agent_macro(intermarket: dict) -> AgentVerdict:
    score = intermarket.get("score", 0.0)
    components = intermarket.get("components", {})
    reasons = []
    primary = ""
    abs_max = 0.0
    for name, c in components.items():
        reasons.append(f"{name}: {c.get('note','')}")
        if abs(c.get("score", 0)) > abs_max:
            abs_max = abs(c.get("score", 0)); primary = name

    if score > 0.25:
        return AgentVerdict("MacroStrategist", "LONG", min(0.5 + abs(score), 0.95), reasons + [f"primary driver: {primary}"])
    if score < -0.25:
        return AgentVerdict("MacroStrategist", "SHORT", min(0.5 + abs(score), 0.95), reasons + [f"primary driver: {primary}"])
    return AgentVerdict("MacroStrategist", "FLAT", 0.3, reasons + ["macro mixed/neutral"])


def _agent_order_flow(df: pd.DataFrame, cot: dict, session: str) -> AgentVerdict:
    reasons: list[str] = []
    score = 0

    z = cot.get("z")
    if z is not None:
        reasons.append(f"COT MM net z52 = {z:+.2f}")
        if z > 1.5:
            score -= 2; reasons.append("extreme long → mean-revert SHORT bias")
        elif z < -1.5:
            score += 2; reasons.append("extreme short → mean-revert LONG bias")

    if df is not None and len(df) > 30:
        last = df.iloc[-1]
        prior_sh = last.get("prior_sh")
        prior_sl = last.get("prior_sl")
        close = float(last["close"])
        if pd.notna(prior_sh) and pd.notna(prior_sl):
            range_size = prior_sh - prior_sl
            if range_size > 0:
                pos = (close - prior_sl) / range_size
                if pos > 0.85:
                    reasons.append("near prior swing high (stops above)")
                    score -= 0.5
                elif pos < 0.15:
                    reasons.append("near prior swing low (stops below)")
                    score += 0.5

    if session == "asia":
        reasons.append("Asia session — range bias, breakout coming London")
    elif session == "london":
        reasons.append("London session — trend setup")
        score *= 1.2
    elif session == "lon_ny_overlap":
        reasons.append("Lon-NY overlap — highest liquidity")
        score *= 1.3

    if score > 1:
        return AgentVerdict("OrderFlowReader", "LONG", min(0.5 + score * 0.15, 0.9), reasons)
    if score < -1:
        return AgentVerdict("OrderFlowReader", "SHORT", min(0.5 + abs(score) * 0.15, 0.9), reasons)
    return AgentVerdict("OrderFlowReader", "FLAT", 0.35, reasons or ["no positioning extreme"])


def _agent_devils_advocate(other_verdicts: list[AgentVerdict], df: pd.DataFrame, in_news: bool, news_event) -> AgentVerdict:
    """Selalu argue against consensus. Returns 'FLAT' confidence = how strong the warning."""
    long_n = sum(1 for v in other_verdicts if v.verdict == "LONG")
    short_n = sum(1 for v in other_verdicts if v.verdict == "SHORT")
    consensus = "LONG" if long_n > short_n else "SHORT" if short_n > long_n else "FLAT"

    risks: list[str] = []
    risk_score = 0

    if in_news:
        risks.append(f"NEWS BLACKOUT: {news_event.title if news_event else ''}")
        risk_score += 3

    if df is not None and len(df) > 30:
        last = df.iloc[-1]
        rsi_v = last.get("rsi14", 50)
        if consensus == "LONG" and pd.notna(rsi_v) and rsi_v > 75:
            risks.append(f"RSI {rsi_v:.0f} overbought — long entry chasing")
            risk_score += 1
        if consensus == "SHORT" and pd.notna(rsi_v) and rsi_v < 25:
            risks.append(f"RSI {rsi_v:.0f} oversold — short entry chasing")
            risk_score += 1

        bb_pct = last.get("bb_pctb")
        if pd.notna(bb_pct):
            if consensus == "LONG" and bb_pct > 0.95:
                risks.append("price at BB upper — pullback risk")
                risk_score += 1
            if consensus == "SHORT" and bb_pct < 0.05:
                risks.append("price at BB lower — bounce risk")
                risk_score += 1

    confidences = [v.confidence for v in other_verdicts if v.confidence > 0]
    if confidences and max(confidences) - min(confidences) > 0.4:
        risks.append("agents disagree — low conviction")
        risk_score += 1

    if not risks:
        risks.append("no major red flag detected")

    if risk_score >= 3:
        return AgentVerdict("DevilsAdvocate", "FLAT", 0.85, risks + ["VETO consensus"])
    if risk_score >= 1:
        return AgentVerdict("DevilsAdvocate", consensus, max(0.0, 0.6 - risk_score * 0.1), risks)
    return AgentVerdict("DevilsAdvocate", consensus, 0.7, risks)


def _classify_strength(confidence: float, agree_count: int, in_news_strong: bool) -> str:
    if in_news_strong and confidence > 0.7 and agree_count >= 3:
        return "NEWS_STRONG"
    if confidence >= 0.80 and agree_count >= 4:
        return "STRONG"
    if confidence >= 0.65 and agree_count >= 3:
        return "NORMAL"
    if confidence >= 0.50:
        return "WEAK"
    return "FLAT"


def debate(
    df: pd.DataFrame,
    df_htf: Optional[pd.DataFrame],
    intermarket: dict,
    cot: dict,
    session: str,
    in_news_blackout: bool,
    news_event=None,
    news_clear_strong_direction: Optional[str] = None,
) -> DebateResult:
    """Run 4-agent debate. Returns DebateResult.
    `news_clear_strong_direction`: if news already released with clear direction, pass 'LONG' or 'SHORT'."""

    a_tech = _agent_technical(df, df_htf)
    a_macro = _agent_macro(intermarket)
    a_flow = _agent_order_flow(df, cot, session)
    others = [a_tech, a_macro, a_flow]
    a_devil = _agent_devils_advocate(others, df, in_news_blackout, news_event)

    agents = [a_tech, a_macro, a_flow, a_devil]

    # Vote tally (Devil counted only if not FLAT veto)
    if a_devil.verdict == "FLAT" and a_devil.confidence > 0.7:
        # Devil VETO — final FLAT
        chain = [
            f"{a_tech.name}: {a_tech.verdict} ({a_tech.confidence:.2f})",
            f"{a_macro.name}: {a_macro.verdict} ({a_macro.confidence:.2f})",
            f"{a_flow.name}: {a_flow.verdict} ({a_flow.confidence:.2f})",
            f"{a_devil.name}: VETO ({a_devil.confidence:.2f}) — {'; '.join(a_devil.reasoning)}",
        ]
        return DebateResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            agents=agents,
            reasoning_chain=chain,
            risks=a_devil.reasoning,
            primary_driver="risk veto",
        )

    long_n = sum(1 for v in agents if v.verdict == "LONG")
    short_n = sum(1 for v in agents if v.verdict == "SHORT")

    if long_n >= 3:
        action = "LONG"
        agree_conf = [v.confidence for v in agents if v.verdict == "LONG"]
        agree_count = long_n
    elif short_n >= 3:
        action = "SHORT"
        agree_conf = [v.confidence for v in agents if v.verdict == "SHORT"]
        agree_count = short_n
    else:
        return DebateResult(
            final_action="FLAT",
            confidence=0.0,
            signal_strength="FLAT",
            agents=agents,
            reasoning_chain=[f"{v.name}: {v.verdict} ({v.confidence:.2f})" for v in agents],
            risks=a_devil.reasoning,
            primary_driver="no consensus",
        )

    avg_conf = sum(agree_conf) / len(agree_conf)

    # Devil haircut
    if a_devil.verdict != action and a_devil.confidence > 0.5:
        avg_conf = max(0.0, avg_conf - 0.1)

    # News-strong boost
    if news_clear_strong_direction and news_clear_strong_direction == action:
        avg_conf = min(1.0, avg_conf + 0.05)
        in_news_strong = True
    else:
        in_news_strong = False

    strength = _classify_strength(avg_conf, agree_count, in_news_strong)

    primary = ""
    if a_macro.verdict == action and a_macro.confidence >= 0.6:
        primary = "macro/intermarket"
    elif a_tech.verdict == action and a_tech.confidence >= 0.6:
        primary = "technical structure"
    elif a_flow.verdict == action and a_flow.confidence >= 0.6:
        primary = "order flow / positioning"

    reasoning_chain = []
    for v in agents:
        reasoning_chain.append(f"[{v.name}] {v.verdict} conf={v.confidence:.2f}: {'; '.join(v.reasoning[:3])}")

    return DebateResult(
        final_action=action,
        confidence=round(avg_conf, 3),
        signal_strength=strength,
        agents=agents,
        reasoning_chain=reasoning_chain,
        risks=a_devil.reasoning,
        primary_driver=primary or "mixed",
    )
