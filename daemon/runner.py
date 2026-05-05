"""Single signal generation: fetch data → run 9-agent debate → push to Supabase."""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

from data.price_fetcher import fetch_xau, fetch_intermarket_bundle, fetch_realtime_xau_spot
from data.calendar_fetcher import in_news_blackout, upcoming_high_impact
from data.cot_fetcher import latest_cot_signal
from features.technical import add_all
from features.smc import add_all_smc
from features.regime import current_regime
from features.session import session_at, annotate_session, is_near_london_fix
from features.intermarket import intermarket_score
from strategies.base import StrategyContext
from strategies import scalper, intraday, swing
from ai_agent.rule_engine import debate as rule_debate
from ai_agent.orchestrator import (
    SettingsStore, run_llm_debate, build_market_context,
)


def run_once(store: SettingsStore, settings: dict, log=print) -> dict:
    """Run one signal cycle. Returns the bundle dict."""
    started = time.time()
    now = datetime.now(timezone.utc)

    log("[runner] fetching XAU + intermarket + COT + calendar...")
    df_5m  = add_all_smc(add_all(fetch_xau("5m")))
    df_15m = add_all_smc(add_all(fetch_xau("15m")))
    df_1h  = add_all_smc(add_all(fetch_xau("1h")))
    df_4h  = add_all_smc(add_all(fetch_xau("4h")))
    df_1d  = add_all_smc(add_all(fetch_xau("1d")))

    # Real-time spot price (Twelve Data, fallback to yfinance close)
    realtime = fetch_realtime_xau_spot()
    log(f"[runner] xau spot: ${realtime['price']} (src: {realtime['source']})")

    inter = intermarket_score(fetch_intermarket_bundle("1h"))
    cot   = latest_cot_signal()
    upc   = upcoming_high_impact(48)
    in_blk, blk_evt = in_news_blackout(now) if settings.get("enable_news_blackout", True) else (False, None)
    sess  = session_at(now)
    fix   = is_near_london_fix(now)
    regime_4h = current_regime(annotate_session(df_4h))
    regime_label = regime_4h["regime"]

    # Per-style strategy results (rule-based, deterministic)
    def _ctx(df_p, df_h):
        return StrategyContext(
            df_primary=df_p, df_htf=df_h,
            intermarket=inter, cot=cot,
            in_news_blackout=in_blk, news_event=blk_evt,
            session=sess, regime=regime_label,
        )
    sig_scalper  = scalper.generate(_ctx(df_5m, df_1h))
    sig_intraday = intraday.generate(_ctx(df_15m, df_4h))
    sig_swing    = swing.generate(_ctx(df_4h, df_1d))

    # 9-agent debate (LLM) or fallback rule debate
    use_llm = bool(settings.get("use_llm_agents", True))
    debate_dict: dict
    if use_llm:
        log("[runner] running 9-agent LLM debate...")
        provider_keys = store.provider_keys()
        agent_cfgs    = store.agent_configs()
        ctx = build_market_context(
            df_15m=df_15m, df_4h=df_4h,
            intermarket=inter, cot=cot, session=sess, regime=regime_label,
            in_blackout=in_blk, blackout_event=blk_evt,
            upcoming_events=upc,
            timeframe_focus=settings.get("timeframe_focus") or "intraday",
        )
        try:
            debate_dict = run_llm_debate(
                market_ctx=ctx,
                settings=settings,
                provider_keys=provider_keys,
                agent_configs=agent_cfgs,
                parallel=True,
            )
            if debate_dict.get("error") == "no_credential":
                log("[runner] no LLM credential — fallback to rule engine")
                debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)
        except Exception as e:
            log(f"[runner] LLM debate failed: {e!r}")
            traceback.print_exc()
            debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)
    else:
        log("[runner] running rule-engine debate (LLM disabled)")
        debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)

    # xau_price: prefer real-time spot, fallback to last 1h close
    xau_price_value = realtime.get("price")
    if xau_price_value is None or xau_price_value <= 0:
        xau_price_value = float(df_1h["close"].iloc[-1])
        realtime["source"] = "yfinance_close"

    bundle = {
        "timestamp":         now.isoformat(),
        "xau_price":         round(float(xau_price_value), 2),
        "xau_price_source":  realtime["source"],
        "xau_price_at_utc":  realtime["timestamp"],
        "regime":         regime_label,
        "session":        sess,
        "near_london_fix": fix,
        "intermarket":    inter,
        "cot":            cot,
        "in_news_blackout": in_blk,
        "blackout_event": ({
            "title": getattr(blk_evt, "title", None),
            "when_utc": getattr(blk_evt, "when_utc", None),
            "currency": getattr(blk_evt, "currency", None),
        } if blk_evt else None),
        "upcoming_events": [{
            "title": getattr(e, "title", None),
            "when_utc": getattr(e, "when_utc", None),
            "currency": getattr(e, "currency", None),
            "impact": getattr(e, "impact", None),
        } for e in upc[:10]],
        "scalper":        sig_scalper.to_dict(),
        "intraday":       sig_intraday.to_dict(),
        "swing":          sig_swing.to_dict(),
        "debate":         debate_dict,
        "ai_pm_used":     use_llm,
    }

    bundle_id = store.push_signal_bundle(bundle)
    elapsed = time.time() - started
    log(f"[runner] done in {elapsed:.1f}s | action={debate_dict.get('final_action')} "
        f"conf={debate_dict.get('confidence')} pushed_id={bundle_id}")
    bundle["_bundle_id"] = bundle_id
    bundle["_elapsed_s"] = round(elapsed, 1)
    return bundle


def _rule_debate_dict(df, df_htf, inter, cot, sess, in_blk, blk_evt) -> dict:
    res = rule_debate(
        df=df, df_htf=df_htf,
        intermarket=inter, cot=cot,
        session=sess, in_news_blackout=in_blk,
        news_event=blk_evt, news_clear_strong_direction=None,
    )
    out = res.to_dict()
    out["engine"] = "rule"
    return out
