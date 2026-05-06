"""Single signal generation: fetch data → run 9-agent debate → push to Supabase."""
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, timezone

from data.price_fetcher import fetch_xau, fetch_intermarket_bundle, fetch_realtime_xau_spot, fetch_yahoo_spot
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
    SettingsStore, run_llm_debate, run_debate, build_market_context,
)

# RCS — composite reference indicator (optional, gracefully skipped if package missing)
try:
    from rcs.composite import compute_rcs
    from rcs.persistence import push_rcs_signal
    from rcs.outcome_tracker import evaluate_pending_signals as rcs_evaluate_outcomes
    from rcs.confluence import evaluate_for_ea, promote_signal_for_ea, DEFAULT_MIN_CONFIDENCE
    RCS_AVAILABLE = True
except ImportError:
    RCS_AVAILABLE = False
    DEFAULT_MIN_CONFIDENCE = 0.55

# Drift detector (Phase v0.3, opt-in via training reference snapshot)
try:
    from rcs.src.drift_detector import quick_drift_check
    DRIFT_AVAILABLE = True
except ImportError:
    DRIFT_AVAILABLE = False

# Telegram push — optional, configured via env or app_settings
try:
    from notify.push import maybe_push_signal
    TG_PUSH_AVAILABLE = True
except ImportError:
    TG_PUSH_AVAILABLE = False

# Web Push (native browser notif) — optional, requires VAPID env + pywebpush
try:
    from notify.web_push import maybe_push_web_signal
    WEB_PUSH_AVAILABLE = True
except ImportError:
    WEB_PUSH_AVAILABLE = False


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

    # SPOT XAU/USD for ENTRY/SL/TP base (not df['close'] which = GC=F futures).
    # Indicators stay from df_p (GC=F bars) — patterns are RELATIVE so
    # futures-vs-spot doesn't change validity, only price level.
    #
    # Resolution flow (adaptive premium):
    #   1. Twelve Data real-time spot (most accurate, matches broker ±$0.50)
    #      → also CAPTURE gap (GC=F close - spot) and persist to state file
    #        so future fallback is data-driven, not hardcoded
    #   2. Twelve Data fail → load last persisted gap, apply: spot = GC=F - gap
    #   3. No state file → fall back to env XAU_FUTURES_PREMIUM_USD (default 7)
    spot_for_entry = None
    df_close_now = float(df_5m["close"].iloc[-1]) if df_5m is not None and len(df_5m) > 0 else None
    DEFAULT_PREMIUM = float(os.environ.get("XAU_FUTURES_PREMIUM_USD") or 7.0)

    from pathlib import Path as _Path
    PREMIUM_STATE = _Path(__file__).resolve().parent.parent / "data_cache" / "futures_premium_gap.txt"

    def _load_premium_gap() -> float:
        try:
            if PREMIUM_STATE.exists():
                txt = PREMIUM_STATE.read_text(encoding="utf-8").strip()
                v = float(txt)
                if 1.0 < v < 30.0:  # sanity: gold premium realistic range
                    return v
        except Exception:
            pass
        return DEFAULT_PREMIUM

    def _save_premium_gap(g: float) -> None:
        try:
            PREMIUM_STATE.parent.mkdir(parents=True, exist_ok=True)
            PREMIUM_STATE.write_text(f"{g:.2f}", encoding="utf-8")
        except Exception:
            pass

    if realtime.get("source") == "twelvedata":
        v = float(realtime.get("price") or 0)
        if v > 0:
            spot_for_entry = v
            # Capture gap for future fallback (when twelvedata quota hits etc.)
            if df_close_now is not None:
                gap = df_close_now - v
                if 1.0 < gap < 30.0:
                    _save_premium_gap(gap)
            log(f"[runner] entry-base spot=${v:.2f} (twelvedata real-time)")

    # Tier 2: Yahoo HTTPS XAUUSD=X spot (no API key, no quota, matches broker
    # ±$0.50 typically). yfinance Python lib 404s on this symbol but the
    # underlying /v8/finance/chart endpoint works fine.
    if spot_for_entry is None:
        yahoo_spot = fetch_yahoo_spot()
        if yahoo_spot and yahoo_spot > 0:
            spot_for_entry = yahoo_spot
            # Also calibrate adaptive premium from this gap
            if df_close_now is not None:
                gap = df_close_now - yahoo_spot
                if 1.0 < gap < 30.0:
                    _save_premium_gap(gap)
            log(f"[runner] entry-base spot=${yahoo_spot:.2f} (yahoo XAUUSD=X HTTPS)")

    if spot_for_entry is None and df_close_now is not None:
        gap = _load_premium_gap()
        spot_for_entry = round(df_close_now - gap, 2)
        log(f"[runner] entry-base spot=${spot_for_entry:.2f} (estimated: GC=F ${df_close_now:.2f} - ${gap:.2f} premium [adaptive])")

    # Per-style strategy results (rule-based, deterministic)
    def _ctx(df_p, df_h):
        return StrategyContext(
            df_primary=df_p, df_htf=df_h,
            intermarket=inter, cot=cot,
            in_news_blackout=in_blk, news_event=blk_evt,
            session=sess, regime=regime_label,
            spot_price=spot_for_entry,
        )
    sig_scalper  = scalper.generate(_ctx(df_5m, df_1h))
    sig_intraday = intraday.generate(_ctx(df_15m, df_4h))
    sig_swing    = swing.generate(_ctx(df_4h, df_1d))

    # NOTE: signals are NEVER suppressed — Home/Sinyal page must always show
    # the latest analysis so the user (or family doing manual execution) can
    # see what the system thinks NOW. Trade-running de-duplication happens at
    # the trade-tracker layer (open_trade_if_eligible has UNIQUE INDEX per
    # style, so a 2nd OPEN trade for the same style is rejected without
    # affecting the displayed signal). Portfolio page is where users see the
    # status of their currently-open trade.

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

    # ── Debate engine: route via orchestrator.run_debate ──────────────────────
    # Local 12-agent (default after migration 015) | LLM 12-agent | rule fallback
    use_llm_legacy = not bool(settings.get("use_local_agents", True))
    use_llm_master = bool(settings.get("use_llm_agents", True))
    debate_dict: dict
    provider_keys = store.provider_keys()
    agent_cfgs    = store.agent_configs()
    ctx = build_market_context(
        df_15m=df_15m, df_4h=df_4h,
        intermarket=inter, cot=cot, session=sess, regime=regime_label,
        in_blackout=in_blk, blackout_event=blk_evt,
        upcoming_events=upc,
        timeframe_focus=settings.get("timeframe_focus") or "intraday",
        rcs_result=rcs_result_dict,
        df_5m=df_5m, df_1h=df_1h, df_1d=df_1d,
        near_london_fix=fix,
        xau_price=float(realtime.get("price") or (df_1h["close"].iloc[-1] if df_1h is not None and len(df_1h) else 0.0)),
        store=store,
    )

    if not use_llm_master:
        log("[runner] LLM master toggle OFF — rule engine 4-agent")
        debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)
    else:
        try:
            engine_label = "local-12-agent" if not use_llm_legacy else "llm-12-agent"
            log(f"[runner] running {engine_label} debate...")
            debate_dict = run_debate(
                market_ctx=ctx,
                settings=settings,
                provider_keys=provider_keys,
                agent_configs=agent_cfgs,
                parallel=True,
                log=log,
            )
            if debate_dict.get("error") in ("no_credential", "all_providers_failed"):
                log(f"[runner] debate engine error: {debate_dict.get('error')} — fallback to rule")
                debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)
        except Exception as e:
            log(f"[runner] debate failed: {e!r}")
            traceback.print_exc()
            debate_dict = _rule_debate_dict(df_1h, df_4h, inter, cot, sess, in_blk, blk_evt)

    # xau_price: use the SAME spot estimate as strategy entry base (consistent
    # with signal levels). Hero card "big price" should match signal entries,
    # not GC=F futures close (was the source of "$4709.70 vs entry $4705.50"
    # confusion the user flagged).
    if spot_for_entry and spot_for_entry > 0:
        xau_price_value = spot_for_entry
        if realtime.get("source") != "twelvedata":
            realtime["source"] = "estimated_spot"
    else:
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
        "ai_pm_used":     use_llm_master,
        # Migration 016: per-agent audit trail. Local-12-agent populates
        # agent_verdicts list + engine_meta dict; legacy LLM/rule path may not.
        "agent_verdicts": debate_dict.get("agents") if isinstance(debate_dict, dict) else None,
        "engine_meta":    debate_dict.get("engine_meta") if isinstance(debate_dict, dict) else None,
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

        # Push RCS to rcs_signals — one row per style (M5/M15/H1) with that
        # style's entry/sl/tp. The EA picks up rows that pass evaluate_for_ea.
        rcs_ids_per_style: dict[str, int] = {}
        if RCS_AVAILABLE and rcs_result_dict and bundle.get("xau_price"):
            try:
                from rcs.composite import RCSResult, ComponentScore
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
                # Per-style: each style has its own TF + levels
                style_to_tf = {"scalper": "M5", "intraday": "M15", "swing": "H1"}
                style_to_atr = {
                    "scalper":  float(df_5m["atr14"].iloc[-1])  if "atr14" in df_5m.columns  else 0.0,
                    "intraday": float(df_15m["atr14"].iloc[-1]) if "atr14" in df_15m.columns else 0.0,
                    "swing":    float(df_4h["atr14"].iloc[-1])  if "atr14" in df_4h.columns  else 0.0,
                }
                for style_name, sig_obj in (
                    ("scalper",  sig_scalper),
                    ("intraday", sig_intraday),
                    ("swing",    sig_swing),
                ):
                    sig_levels = sig_obj.to_dict()
                    rcs_id = push_rcs_signal(
                        store=store,
                        result=result_obj,
                        timeframe=style_to_tf[style_name],
                        spot_price=float(bundle["xau_price"]),
                        atr_14=style_to_atr[style_name],
                        broker_symbol="XAUUSD",
                        entry=sig_levels.get("entry"),
                        sl=sig_levels.get("sl"),
                        tp1=sig_levels.get("tp1"),
                        tp2=sig_levels.get("tp2"),
                        log=log,
                    )
                    if rcs_id:
                        rcs_ids_per_style[style_name] = rcs_id
            except Exception as e:
                log(f"[rcs] push_rcs_signal failed: {e!r}")

            # ── EA gate (Opsi A): per-style direct check, no multi-source agree ──
            # Single rule: if strategy says LONG/SHORT with conf ≥ threshold, promote.
            # RCS becomes display-only reference. 12-agent debate informs UI but
            # doesn't block per-style EA execution (debate already aggregated 12
            # specialists; layering more filters compounds away every signal).
            try:
                ea_min_conf = float(settings.get("ea_min_confidence_pct") or 55) / 100.0
                if ea_min_conf <= 0:
                    ea_min_conf = DEFAULT_MIN_CONFIDENCE
                for style_name, sig_obj in (
                    ("scalper",  sig_scalper),
                    ("intraday", sig_intraday),
                    ("swing",    sig_swing),
                ):
                    decision = evaluate_for_ea(
                        style=style_name,
                        style_signal=sig_obj.to_dict(),
                        min_confidence=ea_min_conf,
                    )
                    if decision.is_executable:
                        rcs_id = rcs_ids_per_style.get(style_name)
                        if rcs_id:
                            promote_signal_for_ea(store, rcs_id, decision, log=log)
                        else:
                            log(f"[ea] {style_name} eligible but no rcs_id — skip")
                    elif decision.side in ("LONG", "SHORT"):
                        # Only log directional rejections — FLAT is silent (already shown above)
                        log(f"[ea] {style_name} {decision.side} not promoted: {decision.reason}")
            except Exception as e:
                log(f"[ea] gate error: {e!r}")
    else:
        log("[runner] STANDBY mode — skip push_signal_bundle (primary handles it)")

    # Per-style summary (each runs independently; UNIQUE INDEX ensures
    # 1 OPEN per style; styles do not block each other).
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

        # ── RCS outcome tracker: evaluate pending rcs_signals ─────────────
        # Marks TP1_HIT/TP2_HIT/SL_HIT/EXPIRED on any pending signals based
        # on price action since signal was generated. Critical for v0.2 ML
        # training data + accuracy metrics on /more/rcs-monitor.
        if RCS_AVAILABLE:
            try:
                outcomes_modified = rcs_evaluate_outcomes(store, df_5m, log=log)
                if outcomes_modified > 0:
                    log(f"[outcome] evaluated {outcomes_modified} rcs_signals")
            except Exception as e:
                log(f"[outcome] evaluation error: {e!r}")

        # ── Telegram push (high-confidence alerts) ────────────────────────
        # Pushed only when STRONG debate OR strong RCS, with debounce.
        if TG_PUSH_AVAILABLE:
            try:
                push_result = maybe_push_signal(store, bundle, log=log)
                if push_result.get("pushed"):
                    log(f"[telegram] pushed: {push_result['reason']}")
                # else silent (most cycles don't trigger; spam-protected)
            except Exception as e:
                log(f"[telegram] push error: {e!r}")

        # ── Web Push (native browser notification) ─────────────────────────
        # Eligibility mirrors notify/push.py:
        #   A) Debate STRONG conf ≥0.65, OR
        #   B) RCS direction conf ≥70%, OR
        #   C) Any per-style signal directional with conf ≥ ea_min_confidence_pct
        #      (so notif fires whenever EA would promote a trade)
        if WEB_PUSH_AVAILABLE:
            try:
                debate_   = bundle.get("debate") or {}
                rcs_      = bundle.get("rcs") or {}
                strength_ = debate_.get("signal_strength", "FLAT")
                conf_     = float(debate_.get("confidence") or 0)
                rcs_dir_  = (rcs_ or {}).get("direction") or "WAIT"
                rcs_conf_ = int((rcs_ or {}).get("confidence_pct") or 0)
                ea_min    = float(settings.get("ea_min_confidence_pct") or 55) / 100.0
                eligible_style = any(
                    (bundle.get(k) or {}).get("side") in ("LONG", "SHORT")
                    and float((bundle.get(k) or {}).get("confidence") or 0) >= ea_min
                    for k in ("scalper", "intraday", "swing")
                )
                eligible = (
                    (strength_ in ("STRONG", "NEWS_STRONG") and conf_ >= 0.65)
                    or (rcs_dir_ in ("LONG", "SHORT") and rcs_conf_ >= 70)
                    or eligible_style
                )
                if eligible:
                    web_result = maybe_push_web_signal(store, bundle, log=log)
                    if web_result.get("pushed"):
                        log(f"[web-push] pushed: {web_result['reason']}")
                    elif web_result.get("reason") not in ("no subscriptions",):
                        log(f"[web-push] skipped: {web_result['reason']}")
            except Exception as e:
                log(f"[web-push] error: {e!r}")

        # ── Drift detection (Phase v0.3) ──────────────────────────────────
        # Compare live feature distribution vs training reference snapshot.
        # If severe drift → log warning + indicate retraining needed.
        if DRIFT_AVAILABLE:
            try:
                drift = quick_drift_check(df_15m, tf="M15")
                if drift and drift.get("level") in ("moderate", "severe"):
                    log(f"[drift] {drift['level'].upper()} score={drift['score']} max={drift['max_score']} drifted={drift.get('per_feature', {}).keys() if drift['level'] == 'severe' else 'see report'}")
            except Exception as e:
                log(f"[drift] check error: {e!r}")

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


