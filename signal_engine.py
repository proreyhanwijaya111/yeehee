"""Top-level orchestrator. Pull data → compute features → run strategies + AI agents → return final signal bundle."""
from __future__ import annotations
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

from data.price_fetcher import fetch_xau, fetch_intermarket_bundle
from data.calendar_fetcher import fetch_calendar, in_news_blackout, upcoming_high_impact, CalEvent
from data.cot_fetcher import latest_cot_signal

from features.technical import add_all
from features.smc import add_all_smc
from features.regime import current_regime
from features.session import session_at, annotate_session, is_near_london_fix
from features.intermarket import intermarket_score

from strategies.base import StrategyContext, Signal
from strategies import scalper, intraday, swing

from ai_agent.rule_engine import debate, DebateResult
from ai_agent.pm_agent import enrich_with_pm_narrative, claude_available


@dataclass
class SignalBundle:
    timestamp: str
    xau_price: float
    regime: str
    session: str
    near_london_fix: tuple
    intermarket: dict
    cot: dict
    in_news_blackout: bool
    blackout_event: Optional[dict]
    upcoming_events: list[dict]
    scalper_signal: dict
    intraday_signal: dict
    swing_signal: dict
    debate: dict
    ai_pm_used: bool

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "xau_price": self.xau_price,
            "regime": self.regime,
            "session": self.session,
            "near_london_fix": self.near_london_fix,
            "intermarket": self.intermarket,
            "cot": self.cot,
            "in_news_blackout": self.in_news_blackout,
            "blackout_event": self.blackout_event,
            "upcoming_events": self.upcoming_events,
            "scalper": self.scalper_signal,
            "intraday": self.intraday_signal,
            "swing": self.swing_signal,
            "debate": self.debate,
            "ai_pm_used": self.ai_pm_used,
        }


_TIMEFRAMES = {
    "scalper":  {"primary": "5m",  "htf": "1h"},
    "intraday": {"primary": "15m", "htf": "4h"},
    "swing":    {"primary": "4h",  "htf": "1d"},
}


def _load_with_features(interval: str) -> pd.DataFrame:
    df = fetch_xau(interval)
    df = add_all(df)
    df = add_all_smc(df)
    return df


def generate_signals(
    use_pm_narrative: bool = True,
    debug: bool = False,
) -> SignalBundle:
    now = datetime.now(timezone.utc)

    # === Data layer ===
    df_5m = _load_with_features("5m")
    df_15m = _load_with_features("15m")
    df_1h = _load_with_features("1h")
    df_4h = _load_with_features("4h")
    df_1d = _load_with_features("1d")

    bundle = fetch_intermarket_bundle("1h")
    inter = intermarket_score(bundle)

    cot_sig = latest_cot_signal()
    upcoming = upcoming_high_impact(48)
    in_blackout, blackout_event = in_news_blackout(now)
    sess = session_at(now)
    fix = is_near_london_fix(now)

    df_4h_with_session = annotate_session(df_4h)
    regime_4h = current_regime(df_4h_with_session)

    # === Strategies ===
    scalper_ctx = StrategyContext(
        df_primary=df_5m, df_htf=df_1h,
        intermarket=inter, cot=cot_sig,
        in_news_blackout=in_blackout, news_event=blackout_event,
        session=sess, regime=regime_4h["regime"],
    )
    intraday_ctx = StrategyContext(
        df_primary=df_15m, df_htf=df_4h,
        intermarket=inter, cot=cot_sig,
        in_news_blackout=in_blackout, news_event=blackout_event,
        session=sess, regime=regime_4h["regime"],
    )
    swing_ctx = StrategyContext(
        df_primary=df_4h, df_htf=df_1d,
        intermarket=inter, cot=cot_sig,
        in_news_blackout=in_blackout, news_event=blackout_event,
        session=sess, regime=regime_4h["regime"],
    )

    sig_scalper = scalper.generate(scalper_ctx)
    sig_intraday = intraday.generate(intraday_ctx)
    sig_swing = swing.generate(swing_ctx)

    # === AI debate (uses intraday/H1 context as default — most relevant TF) ===
    debate_result: DebateResult = debate(
        df=df_1h, df_htf=df_4h,
        intermarket=inter, cot=cot_sig,
        session=sess, in_news_blackout=in_blackout,
        news_event=blackout_event,
        news_clear_strong_direction=None,
    )

    ai_used = False
    if use_pm_narrative and claude_available():
        try:
            ctx_for_pm = {
                "price": float(df_1h["close"].iloc[-1]),
                "regime": regime_4h["regime"],
                "session": sess,
                "intermarket_score": inter.get("score"),
                "cot_z": cot_sig.get("z"),
                "news_summary": "; ".join([f"{e.title} ({e.when_utc})" for e in upcoming[:3]]) or "none in 48h",
            }
            debate_result = enrich_with_pm_narrative(debate_result, ctx_for_pm)
            ai_used = True
        except Exception as e:
            if debug:
                print(f"[pm_narrative] failed: {e}")

    return SignalBundle(
        timestamp=now.isoformat(),
        xau_price=round(float(df_1h["close"].iloc[-1]), 2),
        regime=regime_4h["regime"],
        session=sess,
        near_london_fix=fix,
        intermarket=inter,
        cot=cot_sig,
        in_news_blackout=in_blackout,
        blackout_event=({
            "title": blackout_event.title,
            "when_utc": blackout_event.when_utc,
            "currency": blackout_event.currency,
        } if blackout_event else None),
        upcoming_events=[{
            "title": e.title, "when_utc": e.when_utc, "currency": e.currency, "impact": e.impact,
        } for e in upcoming[:10]],
        scalper_signal=sig_scalper.to_dict(),
        intraday_signal=sig_intraday.to_dict(),
        swing_signal=sig_swing.to_dict(),
        debate=debate_result.to_dict(),
        ai_pm_used=ai_used,
    )


if __name__ == "__main__":
    import json
    print("[engine] generating signals...")
    bundle = generate_signals(use_pm_narrative=False, debug=True)
    print(json.dumps(bundle.to_dict(), indent=2, default=str))
