"""Single signal generation: fetch data → run 9-agent debate → push to Supabase."""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

from data.price_fetcher import fetch_xau, fetch_intermarket_bundle, fetch_realtime_xau_spot
from daemon.trade_tracker import open_trade_if_eligible, update_open_trades
from daemon.heartbeat import get_worker_id
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

# RCS — composite reference indicator (optional, gracefully skipped if package missing)
try:
    from rcs.composite import compute_rcs
    from rcs.persistence import push_rcs_signal
    RCS_AVAILABLE = True
except ImportError:
    RCS_AVAILABLE = False


def run_once(store: SettingsStore, settings: dict, log=print, trigger_reason: str = "scheduled") -> dict:
    """Run one signal cycle. Returns the bundle dict.

    Opsi B: trigger_reason indicates why this cycle ran ('scheduled', 'price_spike',
    'ema_cross', etc). Persisted to signal_bundles.trigger_reason for UI display.
    """
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

    # ── RCS composite reference indicator ─────────────────────────────────────
    # Computes single composite score [-1, +1] from existing features as
    # ADDITIONAL reference for 12-agent debate. Output also persisted to
    # rcs_signals table for monitoring + future EA consumption.
    rcs_result_dict = None
    if RCS_AVAILABLE:
        try:
            rcs_result = compute_rcs(
                df_4h=df_4h, df_15m=df_15m,
                intermarket=inter,
                session=sess,
                regime=regime_label,
            )
            rcs_result_dict = rcs_result.to_dict()
            log(f"[rcs] score={rcs_result.rcs_score:+.3f} dir={rcs_result.direction} conf={rcs_result.confidence_pct}% top={rcs_result.top_drivers[:1]}")
        except Exception as e:
            log(f"[rcs] compute failed: {e!r}")
            rcs_result_dict = None

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
            rcs_result=rcs_result_dict,   # RCS composite reference
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
        # RCS composite reference indicator (read by /signals UI as side panel)
        "rcs":            rcs_result_dict,
        # Opsi B: persisted to signal_bundles.trigger_reason
        "_trigger_reason": trigger_reason,
    }

    # ── Multi-PC active-passive lock (migration 007) ───────────────────────────
    # Election: only PRIMARY worker pushes signal_bundles + opens trades.
    # STANDBY workers still ran the analysis (above) for telemetry, but skip the
    # mutating operations to avoid duplicate rows. They do still push heartbeat.
    user_id   = settings.get("user_id", "default")
    worker_id = get_worker_id()
    is_primary, role_reason = store.is_primary_worker(user_id=user_id, worker_id=worker_id)
    role_label = "PRIMARY" if is_primary else "STANDBY"
    log(f"[runner] role={role_label} worker_id={worker_id} ({role_reason})")

    bundle_id = None
    if is_primary:
        bundle_id = store.push_signal_bundle(bundle)

        # ── Push RCS to rcs_signals (PRIMARY only) ────────────────────────────
        # Used by /more/rcs-monitor UI for history + accuracy tracking, and as
        # data source for future MT5 EA bot polling.
        if RCS_AVAILABLE and rcs_result_dict and bundle.get("xau_price"):
            try:
                from rcs.composite import RCSResult, ComponentScore
                # Reconstruct RCSResult from dict so we can pass to push helper
                comps = [ComponentScore(**c) for c in rcs_result_dict["components"]]
                result_obj = RCSResult(
                    rcs_score=rcs_result_dict["rcs_score"],
                    direction=rcs_result_dict["direction"],
                    confidence_pct=rcs_result_dict["confidence_pct"],
                    components=comps,
                    top_drivers=rcs_result_dict.get("top_drivers", []),
                    regime=rcs_result_dict.get("regime", regime_label),
                    session=rcs_result_dict.get("session", sess),
                )
                # Use intraday signal levels (15m) as default entry/sl/tp for RCS
                # (RCS itself doesn't compute levels — just direction. Levels are
                # for future EA consumption based on user's preferred TF.)
                sig_levels = sig_intraday.to_dict()
                push_rcs_signal(
                    store=store,
                    result=result_obj,
                    timeframe="M15",
                    spot_price=float(bundle["xau_price"]),
                    atr_14=float(df_15m["atr14"].iloc[-1]) if "atr14" in df_15m.columns else 0.0,
                    broker_symbol="XAUUSD",
                    entry=sig_levels.get("entry"),
                    sl=sig_levels.get("sl"),
                    tp1=sig_levels.get("tp1"),
                    tp2=sig_levels.get("tp2"),
                    log=log,
                )
            except Exception as e:
                log(f"[rcs] push_rcs_signal failed: {e!r}")
    else:
        log("[runner] STANDBY mode — skip push_signal_bundle (primary handles it)")

    # ── Per-style independence log (clarity for user) ──────────────────────────
    # Each style is analyzed independently every cycle. Confluence + side determined
    # solely from that style's own indicators. open_trade_if_eligible has per-style
    # UNIQUE INDEX so one style being OPEN doesn't block another style from opening.
    for style_name, sig_obj in (("scalper", sig_scalper), ("intraday", sig_intraday), ("swing", sig_swing)):
        sd = sig_obj.to_dict()
        log(
            f"[runner] {style_name:8s} → {sd.get('side', 'FLAT'):5s} "
            f"conf={sd.get('confidence', 0):.2f} confluence={sd.get('confluence_count', 0)}"
        )

    # ── Forward-test layer: ONLY PRIMARY mutates active_trades ────────────────
    # 1. update_open_trades FIRST (close trades that hit SL/TP since last cycle).
    # 2. THEN open_trade_if_eligible per style — UNIQUE INDEX (1 OPEN per style)
    #    will correctly allow new trade only after old one closed.
    if is_primary:
        try:
            modified = update_open_trades(store, df_5m, log=log)
            if modified > 0:
                log(f"[tracker] updated {modified} open trades")
        except Exception as e:
            log(f"[tracker] update phase error: {e!r}")
            traceback.print_exc()

        try:
            for style, sig_obj in (("scalper", sig_scalper), ("intraday", sig_intraday), ("swing", sig_swing)):
                sig_dict = sig_obj.to_dict()
                open_trade_if_eligible(
                    store=store,
                    style=style,
                    signal=sig_dict,
                    bundle_id=bundle_id,
                    regime=regime_label,
                    session=sess,
                    log=log,
                )
        except Exception as e:
            log(f"[tracker] open phase error: {e!r}")
            traceback.print_exc()
    else:
        log("[tracker] STANDBY mode — skip update_open_trades + open_trade_if_eligible")

    elapsed = time.time() - started
    log(f"[runner] done in {elapsed:.1f}s | role={role_label} action={debate_dict.get('final_action')} "
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
