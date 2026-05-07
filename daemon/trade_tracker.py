"""Forward-test trade tracker.

Lifecycle:
1. open_trade_if_eligible(bundle, style, signal_dict, store)
   - Per style (scalper/intraday/swing), if signal LONG/SHORT with non-zero
     confidence AND no existing OPEN trade for same style, INSERT new row
     with entry/sl/tp from signal. Unique index in DB enforces 1-OPEN-per-style.
   - IMPROVEMENT #4: also computes Kelly fractional risk_pct based on
     historical win_rate + avg_win_r for this style + confidence.
2. update_open_trades(store, df_5m)
   - For each OPEN trade, examine candles since last_check_at.
   - Detect SL hit (low <= sl for LONG, high >= sl for SHORT).
   - Detect TP1/TP2/TP3 hit (high >= tpN for LONG, low <= tpN for SHORT).
   - Update hit_tpN flags + high_after_open + low_after_open.
   - Close trade if SL hit OR TP3 hit OR past expiry_at.
   - pnl_r computed from levels: tp_n hit -> +2/+3 R, sl hit -> -1 R, expired -> mark-to-market.

Caveats / honest limitations:
- Daemon refresh = 5 min. Between cycles, price might cross both SL and TP intra-bar.
  Resolution: iterate 5m candles between last_check_at and now. SL has priority over TP if
  same bar (worst-case fill). Conservative.
- Slippage not modeled — assume entry/sl/tp fill exactly. Real broker may slip.
- Spread not modeled — pip costs ignored.

Same Supabase service_role key used by daemon for all writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

import pandas as pd

from config.settings import RISK_PROFILES, DEFAULT_RISK_PROFILE
from risk.sizing import kelly_fractional


# Trade expiry per style. After this duration, daemon force-closes trade
# (mark-to-market). Set conservatively — scalp shouldn't run for days.
EXPIRY_HOURS = {
    "scalper":  4,    # 4h max — scalper is intra-session
    "intraday": 24,   # 1d max — intraday end-of-day usually closes
    "swing":    24 * 7,  # 7d max — swing trades can hold days
}


# Minimum confidence to open a trade. Below this = "weak signal", skip.
# Default fallback only — actual value read from app_settings.ea_min_confidence_pct
# at runtime to keep paper sim and broker EA in lockstep (user spec 2026-05-07:
# "logic dalemnya sama antara paper dan broker").
MIN_CONFIDENCE = 0.65

# IMPROVEMENT #4: Kelly sizing constants.
# Need at least N closed trades for this style before Kelly is statistically meaningful.
# Below threshold we fall back to: risk_pct = profile_cap × confidence.
KELLY_MIN_CLOSED = 20

# Quarter-Kelly is the conservative default — full Kelly is too volatile.
# RISK_PROFILES contains per-profile kelly_frac override (0.15 / 0.25 / 0.4 / 1.0).
DEFAULT_KELLY_FRACTION = 0.25

# Floor risk_pct (don't size below this even if Kelly says zero — it's still a paper trade).
RISK_PCT_FLOOR = 0.001  # 0.1% minimum

# Sanity range for gold spot prices. Used to reject GLD ETF fallback (~$430)
# leaking through the yfinance fallback chain (FALLBACK_TICKERS["xau"]
# = GC=F -> GLD -> IAU). Gold has been $1500-5000 historically; we use a
# wide $1000-10000 window to future-proof.
GOLD_PRICE_MIN = 1000.0
GOLD_PRICE_MAX = 10000.0

def _is_gold_price(p) -> bool:
    """True if `p` is in realistic gold spot range (rejects GLD/IAU fallback)."""
    try:
        v = float(p)
        return GOLD_PRICE_MIN < v < GOLD_PRICE_MAX
    except (TypeError, ValueError):
        return False


# 2026-05-06: confidence multiplier disabled per user explicit request
# ("risk trade 1%"). Weak signals already filtered upstream by MIN_CONFIDENCE
# gate (0.50). Risk per trade is now flat = profile_cap; Kelly still active
# when sufficient history (>=KELLY_MIN_CLOSED) but no longer scaled by
# per-signal confidence.
def _confidence_multiplier(confidence: float) -> float:
    """Deprecated: returns 1.0 unconditionally. Kept for back-compat."""
    return 1.0


def compute_risk_sizing(
    store,
    style: str,
    confidence: float,
    profile: str = "moderat",
) -> dict:
    """IMPROVEMENT #4: compute risk_pct using Kelly + confidence + profile cap.

    Returns:
      {
        "risk_pct": 0.005,            # final fraction of equity to risk
        "kelly_fraction": 0.12,        # raw Kelly suggestion
        "prior_winrate": 0.55,         # historical win rate snapshot
        "prior_avg_win_r": 1.85,
        "prior_n_closed": 12,
        "profile": "moderat",
        "method": "kelly" | "confidence_only" | "floor",
      }
    """
    profile_cfg = RISK_PROFILES.get(profile, RISK_PROFILES.get("moderat", {}))
    profile_cap = float(profile_cfg.get("risk_per_trade", 0.01))
    kelly_frac = float(profile_cfg.get("kelly_frac", DEFAULT_KELLY_FRACTION))

    # Default snapshot
    out = {
        "risk_pct": max(profile_cap * _confidence_multiplier(confidence), RISK_PCT_FLOOR),
        "kelly_fraction": None,
        "prior_winrate": None,
        "prior_avg_win_r": None,
        "prior_n_closed": 0,
        "profile": profile,
        "method": "confidence_only",
    }

    # Try to fetch historical stats for this style
    if not store or not getattr(store, "has_db", False):
        return out

    try:
        r = (
            store._client.from_("portfolio_stats_by_style")
            .select("win_rate, avg_win_r, closed_count")
            .eq("user_id", "default")
            .eq("style", style)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            return out
        row = rows[0]
        n_closed = int(row.get("closed_count") or 0)
        win_rate = float(row.get("win_rate") or 0)
        avg_win_r = float(row.get("avg_win_r") or 0)

        out.update({
            "prior_winrate": round(win_rate, 4),
            "prior_avg_win_r": round(avg_win_r, 3),
            "prior_n_closed": n_closed,
        })

        # Need enough samples + positive avg_win_r for Kelly
        if n_closed < KELLY_MIN_CLOSED or avg_win_r <= 0 or win_rate <= 0:
            return out

        # Compute fractional Kelly
        f = kelly_fractional(win_rate=win_rate, avg_win_r=avg_win_r, fraction=kelly_frac)
        out["kelly_fraction"] = round(f, 5)

        # Final risk_pct = min(profile_cap, kelly × confidence_multiplier).
        # i.e. profile cap is the hard ceiling — Kelly can only reduce, not exceed.
        kelly_with_conf = f * _confidence_multiplier(confidence)
        risk_pct = min(profile_cap, max(kelly_with_conf, RISK_PCT_FLOOR))
        out["risk_pct"] = round(risk_pct, 5)
        out["method"] = "kelly"
    except Exception as e:
        # Graceful: if view doesn't exist (old schema) or query fails, fall back
        out["method"] = f"confidence_only_fallback ({type(e).__name__})"

    return out


@dataclass
class TradeUpdate:
    """Computed update for one trade. Returns None on no-change."""
    hit_tp1: bool = False
    hit_tp2: bool = False
    hit_tp3: bool = False
    hit_sl:  bool = False
    high_after_open: Optional[float] = None
    low_after_open:  Optional[float] = None
    # Migration 013: SL movement (BEP / lock-TP1). When set, the active_trades
    # row's `sl` column is updated to this value. Original SL stays in
    # `original_sl` for R-unit normalization.
    sl_new:    Optional[float] = None
    closed:    bool = False
    status:    Optional[str] = None         # 'OPEN' | 'TP1' | 'TP2' | 'TP3' | 'SL' | 'EXPIRED'
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    closed_at: Optional[str] = None
    pnl_r:     Optional[float] = None
    pnl_pct:   Optional[float] = None


def _expiry_at(opened_at: datetime, style: str) -> datetime:
    return opened_at + timedelta(hours=EXPIRY_HOURS.get(style, 24))


# ─── Open new trade ─────────────────────────────────────────────────────────────

def open_trade_if_eligible(
    store,
    style: str,
    signal: dict,
    bundle_id: Optional[str],
    regime: Optional[str] = None,
    session: Optional[str] = None,
    log=print,
) -> Optional[str]:
    """Try to open new trade. Returns trade id or None if skipped.

    Skip reasons:
    - Signal side is not LONG/SHORT (FLAT)
    - Confidence < MIN_CONFIDENCE
    - Existing OPEN trade for same (user, style) — DB unique index will reject anyway
    - Levels invalid (entry/sl/tp == 0)
    """
    if not store.has_db:
        return None

    side = (signal.get("side") or signal.get("action") or "FLAT").upper()
    if side not in ("LONG", "SHORT"):
        return None

    # Threshold from app_settings (mirror EA gating). 2026-05-07: user spec
    # "logic dalemnya sama antara paper dan broker". Read same source EA uses.
    min_conf = MIN_CONFIDENCE
    try:
        if getattr(store, "has_db", False):
            r = (
                store._client.from_("app_settings")
                .select("ea_min_confidence_pct")
                .eq("user_id", "default")
                .limit(1)
                .execute()
            )
            if r.data and r.data[0].get("ea_min_confidence_pct"):
                min_conf = float(r.data[0]["ea_min_confidence_pct"]) / 100.0
    except Exception:
        pass  # use fallback constant
    confidence = float(signal.get("confidence") or 0)
    if confidence < min_conf:
        log(f"[tracker] skip {style}: confidence {confidence:.2f} < {min_conf:.2f} (app_settings)")
        return None

    entry = float(signal.get("entry") or 0)
    sl    = float(signal.get("sl") or 0)
    tp1   = float(signal.get("tp1") or 0)
    if entry <= 0 or sl <= 0 or tp1 <= 0:
        log(f"[tracker] skip {style}: invalid levels entry={entry} sl={sl} tp1={tp1}")
        return None

    # Sanity: SL must be on opposite side of entry vs TP
    if side == "LONG" and (sl >= entry or tp1 <= entry):
        log(f"[tracker] skip {style} LONG: sl={sl} not below entry={entry} or tp1={tp1} not above")
        return None
    if side == "SHORT" and (sl <= entry or tp1 >= entry):
        log(f"[tracker] skip {style} SHORT: sl={sl} not above entry={entry} or tp1={tp1} not below")
        return None

    # Check existing OPEN trade for this style (avoid unique-index error noise)
    try:
        existing = (
            store._client.from_("active_trades")
            .select("id")
            .eq("user_id", "default")
            .eq("style", style)
            .eq("status", "OPEN")
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            log(f"[tracker] skip {style}: existing OPEN trade {existing.data[0]['id'][:8]}")
            return None
    except Exception as e:
        log(f"[tracker] check existing failed: {e}")

    now = datetime.now(timezone.utc)
    expiry = _expiry_at(now, style)

    # IMPROVEMENT #4: compute Kelly fractional risk_pct based on confidence + history.
    # Defaults to DEFAULT_RISK_PROFILE (moderat) — user can override via app_settings.
    profile = DEFAULT_RISK_PROFILE
    sizing = compute_risk_sizing(store=store, style=style, confidence=confidence, profile=profile)
    log(
        f"[tracker] {style} sizing: risk={sizing['risk_pct']*100:.2f}% "
        f"method={sizing['method']} kelly={sizing.get('kelly_fraction')} "
        f"prior_n={sizing['prior_n_closed']} prior_wr={sizing.get('prior_winrate')}"
    )

    payload = {
        "user_id":         "default",
        "bundle_id":       bundle_id,
        "style":           style,
        "side":            side,
        "signal_strength": signal.get("signal_strength"),
        "confidence":      confidence,
        "entry":           round(entry, 2),
        "sl":              round(sl, 2),
        # Migration 013: freeze original SL for pnl_r normalization (1R = original risk).
        "original_sl":     round(sl, 2),
        "tp1":             round(tp1, 2),
        "tp2":             round(float(signal.get("tp2") or 0), 2) or None,
        "tp3":             round(float(signal.get("tp3") or 0), 2) or None,
        "status":          "OPEN",
        "high_after_open": round(entry, 2),
        "low_after_open":  round(entry, 2),
        "last_check_at":   now.isoformat(),
        "opened_at":       now.isoformat(),
        "expiry_at":       expiry.isoformat(),
        "reasons":         signal.get("reasons", []),
        "risks":           signal.get("risks", []),
        "regime":          regime,
        "session":         session,
        # IMPROVEMENT #4: Kelly sizing snapshot
        "risk_pct":        sizing["risk_pct"],
        "kelly_fraction":  sizing.get("kelly_fraction"),
        "profile":         sizing["profile"],
        "prior_winrate":   sizing.get("prior_winrate"),
        "prior_avg_win_r": sizing.get("prior_avg_win_r"),
        "prior_n_closed":  sizing["prior_n_closed"],
    }

    # IMPROVEMENT #4: graceful degrade if migration 004 not yet applied.
    # New columns (risk_pct, kelly_fraction, profile, prior_*) only exist after
    # migration 004 — fall back to legacy schema if INSERT fails with column error.
    # Migration 013 adds original_sl — also drop on legacy retry.
    KELLY_FIELDS = ("risk_pct", "kelly_fraction", "profile",
                    "prior_winrate", "prior_avg_win_r", "prior_n_closed",
                    "original_sl", "sl_moved_at")

    try:
        r = store._client.from_("active_trades").insert(payload).execute()
        new_id = (r.data or [{}])[0].get("id")
        log(f"[tracker] OPENED {style} {side} @ {entry} sl={sl} tp1={tp1} id={str(new_id)[:8]}")
        return new_id
    except Exception as e:
        msg = str(e).lower()
        # If error mentions a column that's missing, retry without Kelly fields
        is_missing_col = any(f in msg for f in KELLY_FIELDS) or "column" in msg or "schema" in msg
        if is_missing_col:
            log(f"[tracker] open {style}: legacy schema detected, retrying without Kelly fields")
            legacy_payload = {k: v for k, v in payload.items() if k not in KELLY_FIELDS}
            try:
                r = store._client.from_("active_trades").insert(legacy_payload).execute()
                new_id = (r.data or [{}])[0].get("id")
                log(f"[tracker] OPENED {style} {side} @ {entry} sl={sl} tp1={tp1} id={str(new_id)[:8]} "
                    f"(legacy schema; apply migration 004 to enable Kelly sizing)")
                return new_id
            except Exception as e2:
                log(f"[tracker] open {style} failed (even legacy): {e2}")
                return None
        log(f"[tracker] open {style} failed: {e}")
        return None


# ─── Monitor + close existing OPEN trades ──────────────────────────────────────

def update_open_trades(store, df_5m: pd.DataFrame, log=print) -> int:
    """Iterate all OPEN trades, check SL/TP/expiry, update or close.
    df_5m: latest 5min OHLCV (must have columns: high, low, close)
    Returns number of trades modified.
    """
    if not store.has_db or df_5m is None or len(df_5m) == 0:
        return 0

    try:
        r = (
            store._client.from_("active_trades")
            .select("*")
            .eq("user_id", "default")
            .eq("status", "OPEN")
            .execute()
        )
        open_trades = r.data or []
    except Exception as e:
        log(f"[tracker] fetch open failed: {e}")
        return 0

    if not open_trades:
        return 0

    now = datetime.now(timezone.utc)
    modified = 0

    for trade in open_trades:
        # 2026-05-07: skip broker-mirror rows. Their lifecycle is driven by
        # /api/ea/report mirror callbacks, not by candle-bar evaluation here.
        # Without this skip, daemon would close paper rows from yfinance bars
        # while broker still holds OPEN → desync between paper UI and reality.
        # Marker = "broker_mirror" tag in reasons array (added by
        # execution_api._mirror_to_active_trades on insert).
        reasons = trade.get("reasons") or []
        if "broker_mirror" in reasons:
            continue
        try:
            update = _evaluate_trade(trade, df_5m, now)
            if update is None:
                continue
            patch = _update_to_dict(update)
            if not patch:
                continue
            try:
                store._client.from_("active_trades").update(patch).eq("id", trade["id"]).execute()
            except Exception as e:
                # Migration 013 not applied → drop sl_moved_at and retry
                if "sl_moved_at" in str(e).lower() or "column" in str(e).lower():
                    patch.pop("sl_moved_at", None)
                    store._client.from_("active_trades").update(patch).eq("id", trade["id"]).execute()
                else:
                    raise
            modified += 1
            if update.sl_new is not None and not update.closed:
                bep_label = "BEP" if abs(update.sl_new - float(trade["entry"])) < 0.01 else "lock-TP1"
                log(f"[tracker] {trade['style']} SL moved to {update.sl_new:.2f} ({bep_label}) "
                    f"id={str(trade['id'])[:8]}")
            if update.closed:
                log(f"[tracker] CLOSED {trade['style']} {trade['side']} -> {update.status} pnl={update.pnl_r}R "
                    f"reason={update.exit_reason} id={str(trade['id'])[:8]}")
        except Exception as e:
            log(f"[tracker] update trade {trade.get('id','?')[:8]} failed: {e}")

    return modified


def _trail_sl_long(entry: float, original_sl: float, tp1: float, tp2: float,
                   tp3: float, high: float, current_sl: float) -> float:
    """Stepped trailing stop for LONG. SL only ever moves UP (toward profit).

    Steps (each milestone locks more profit, never reverses):
        high < 50% TP1:    SL = current (typically original)
        high ≥ 50% TP1:    SL = entry             (BEP, locks 0R minimum)
        high ≥ TP1:        SL = halfway(E, TP1)   (+0.5R locked)
        high ≥ TP2:        SL = TP1               (+1R locked)
        high ≥ 50% TP2-3:  SL = halfway(TP1, TP2) (+1.5R locked)
        high ≥ TP3:        close at TP3 (+full R) — handled separately
    """
    new_sl = current_sl
    if high <= entry or tp1 <= entry:
        return new_sl

    half_tp1 = entry + 0.5 * (tp1 - entry)
    if high >= half_tp1:
        new_sl = max(new_sl, entry)                       # BEP
    if high >= tp1:
        new_sl = max(new_sl, entry + 0.5 * (tp1 - entry)) # +0.5R
    if tp2 > 0 and high >= tp2:
        new_sl = max(new_sl, tp1)                         # +1R lock TP1
    if tp2 > 0 and tp3 > 0:
        half_tp23 = tp2 + 0.5 * (tp3 - tp2)
        if high >= half_tp23:
            new_sl = max(new_sl, tp1 + 0.5 * (tp2 - tp1)) # +1.5R
    return new_sl


def _trail_sl_short(entry: float, original_sl: float, tp1: float, tp2: float,
                    tp3: float, low: float, current_sl: float) -> float:
    """Mirror of _trail_sl_long. For SHORT, SL only ever moves DOWN."""
    new_sl = current_sl
    if low >= entry or tp1 >= entry:
        return new_sl

    half_tp1 = entry - 0.5 * (entry - tp1)
    if low <= half_tp1:
        new_sl = min(new_sl, entry)                       # BEP
    if low <= tp1:
        new_sl = min(new_sl, entry - 0.5 * (entry - tp1)) # +0.5R
    if tp2 > 0 and low <= tp2:
        new_sl = min(new_sl, tp1)                         # +1R lock TP1
    if tp2 > 0 and tp3 > 0:
        half_tp23 = tp2 - 0.5 * (tp2 - tp3)
        if low <= half_tp23:
            new_sl = min(new_sl, tp1 - 0.5 * (tp1 - tp2)) # +1.5R
    return new_sl


def _evaluate_trade(trade: dict, df_5m: pd.DataFrame, now: datetime) -> Optional[TradeUpdate]:
    """Decide what to update for this trade based on candles since last_check_at.

    User-aligned trailing SL (5-step stepped lock — see _trail_sl_long doc):
        50% TP1 → SL = entry (BEP)
        TP1 hit → SL = halfway(E, TP1) — +0.5R
        TP2 hit → SL = TP1              — +1R
        50% TP2-TP3 → SL = halfway(TP1, TP2) — +1.5R
        TP3 hit → close at TP3 — +full R
    Profit can never turn back to loss once 50% TP1 is reached.
    """
    side = trade["side"]
    sl   = float(trade["sl"])
    # Migration 013: original_sl preserved for R-unit normalization. Falls back
    # to current sl for legacy rows without the column or null backfill.
    original_sl_raw = trade.get("original_sl")
    original_sl = float(original_sl_raw) if original_sl_raw is not None else sl
    entry = float(trade["entry"])
    tp1  = float(trade.get("tp1") or 0)
    tp2  = float(trade.get("tp2") or 0)
    tp3  = float(trade.get("tp3") or 0)
    hit_tp1 = bool(trade.get("hit_tp1"))
    hit_tp2 = bool(trade.get("hit_tp2"))
    hit_tp3 = bool(trade.get("hit_tp3"))
    high_after = float(trade.get("high_after_open") or entry)
    low_after  = float(trade.get("low_after_open") or entry)

    # Original SL distance — used as R unit for ALL pnl_r computations.
    original_sl_dist = abs(entry - original_sl)

    def _r(exit_price: float) -> float:
        """Compute pnl_r using original_sl distance as 1R unit."""
        if original_sl_dist <= 0:
            return 0.0
        realised = (exit_price - entry) if side == "LONG" else (entry - exit_price)
        return round(realised / original_sl_dist, 3)

    last_check = trade.get("last_check_at") or trade.get("opened_at")
    last_check_dt = pd.Timestamp(last_check)

    # Filter df_5m to bars at or after last_check
    candles = df_5m[df_5m.index >= last_check_dt]
    # NOTE: do NOT early-return here when candles is empty. yfinance sometimes
    # returns no new 5m bar between cycles (data lag, weekend gap, etc.). The
    # stored high_after_open/low_after_open already reflects past peaks, and
    # the LATEST bar's close is the freshest spot price we have. Both must be
    # considered for trailing SL on every cycle, otherwise SL stays stuck at
    # original even when price has clearly moved past TP1/TP2.

    upd = TradeUpdate(
        hit_tp1=hit_tp1, hit_tp2=hit_tp2, hit_tp3=hit_tp3,
        high_after_open=high_after, low_after_open=low_after,
    )
    # Working copy of SL — may be moved to entry (BEP) or TP1 (lock) within this loop.
    cur_sl = sl

    # Augment high_after_open / low_after_open with the LATEST close (in case
    # the stored values are stale and the latest close is more extreme).
    # GUARD: skip GLD/IAU fallback bars (~$432 ETF price) — they pollute
    # high/low tracking permanently. See _is_gold_price + GOLD_PRICE_MIN/MAX.
    if df_5m is not None and len(df_5m) > 0:
        latest_close = float(df_5m.iloc[-1]["close"])
        latest_high  = float(df_5m.iloc[-1]["high"]) if "high" in df_5m.columns else latest_close
        latest_low   = float(df_5m.iloc[-1]["low"])  if "low"  in df_5m.columns else latest_close
        if not (_is_gold_price(latest_close) and _is_gold_price(latest_high) and _is_gold_price(latest_low)):
            log(f"[tracker] WARN df_5m latest bar prices unrealistic (close=${latest_close:.2f} high=${latest_high:.2f} low=${latest_low:.2f}) -- likely GLD fallback; skip update for trade {trade.get('id', '')[:8]}")
        else:
            upd.high_after_open = max(upd.high_after_open or latest_high, latest_high, latest_close)
            upd.low_after_open  = min(upd.low_after_open  or latest_low,  latest_low,  latest_close)
            # Also flag TP hits if latest bar is at or past TP levels (was missed
            # if last_check_at > bar.timestamp due to clock skew)
            if side == "LONG":
                if tp1 > 0 and upd.high_after_open >= tp1: upd.hit_tp1 = True
                if tp2 > 0 and upd.high_after_open >= tp2: upd.hit_tp2 = True
            else:
                if tp1 > 0 and upd.low_after_open  <= tp1: upd.hit_tp1 = True
                if tp2 > 0 and upd.low_after_open  <= tp2: upd.hit_tp2 = True

    # Apply trailing SL based on (possibly augmented) highest excursion.
    if side == "LONG":
        new_sl = _trail_sl_long(entry, original_sl, tp1, tp2, tp3,
                                  upd.high_after_open, cur_sl)
    else:
        new_sl = _trail_sl_short(entry, original_sl, tp1, tp2, tp3,
                                   upd.low_after_open, cur_sl)
    if new_sl != cur_sl:
        cur_sl = new_sl
        upd.sl_new = cur_sl

    closed_in_bar = False

    for ts, row in candles.iterrows():
        h = float(row["high"]); l = float(row["low"])
        # GUARD: skip GLD/IAU fallback bars to prevent low pollution like $432.36
        if not (_is_gold_price(h) and _is_gold_price(l)):
            continue
        upd.high_after_open = max(upd.high_after_open or h, h)
        upd.low_after_open  = min(upd.low_after_open or l, l)

        if side == "LONG":
            # Check SL FIRST against the CURRENT (possibly moved) SL.
            if l <= cur_sl:
                upd.closed = True
                upd.status = "SL"
                upd.exit_price = cur_sl
                if cur_sl <= original_sl:
                    upd.exit_reason = "sl_hit"
                elif abs(cur_sl - entry) < 1e-6:
                    upd.exit_reason = "bep_hit"
                else:
                    upd.exit_reason = "trailing_sl_hit"
                upd.closed_at = ts.isoformat() if hasattr(ts, "isoformat") else now.isoformat()
                upd.pnl_r = _r(cur_sl)
                upd.pnl_pct = round((cur_sl - entry) / entry * 100, 4)
                upd.hit_sl = (cur_sl <= original_sl)   # only flag full SL hit, not BEP/trailing exit
                upd.sl_new = cur_sl if cur_sl != sl else None
                closed_in_bar = True
                break
            # TP3 = full target
            if tp3 > 0 and h >= tp3:
                upd.hit_tp1 = upd.hit_tp2 = upd.hit_tp3 = True
                upd.closed = True
                upd.status = "TP3"
                upd.exit_price = tp3
                upd.exit_reason = "tp_hit"
                upd.closed_at = ts.isoformat() if hasattr(ts, "isoformat") else now.isoformat()
                upd.pnl_r = _r(tp3)
                upd.pnl_pct = round((tp3 - entry) / entry * 100, 4)
                closed_in_bar = True
                break
            # Flag TP hits + apply stepped trailing SL based on new high
            if tp1 > 0 and h >= tp1: upd.hit_tp1 = True
            if tp2 > 0 and h >= tp2: upd.hit_tp2 = True
            new_sl = _trail_sl_long(entry, original_sl, tp1, tp2, tp3,
                                     upd.high_after_open, cur_sl)
            if new_sl != cur_sl:
                cur_sl = new_sl
                upd.sl_new = cur_sl
        else:
            # SHORT — mirrored. cur_sl monotonically decreases.
            if h >= cur_sl:
                upd.closed = True; upd.status = "SL"; upd.exit_price = cur_sl
                if cur_sl >= original_sl:
                    upd.exit_reason = "sl_hit"
                elif abs(cur_sl - entry) < 1e-6:
                    upd.exit_reason = "bep_hit"
                else:
                    upd.exit_reason = "trailing_sl_hit"
                upd.closed_at = ts.isoformat() if hasattr(ts, "isoformat") else now.isoformat()
                upd.pnl_r = _r(cur_sl)
                upd.pnl_pct = round((entry - cur_sl) / entry * 100, 4)
                upd.hit_sl = (cur_sl >= original_sl)
                upd.sl_new = cur_sl if cur_sl != sl else None
                closed_in_bar = True
                break
            if tp3 > 0 and l <= tp3:
                upd.hit_tp1 = upd.hit_tp2 = upd.hit_tp3 = True
                upd.closed = True; upd.status = "TP3"; upd.exit_price = tp3
                upd.exit_reason = "tp_hit"
                upd.closed_at = ts.isoformat() if hasattr(ts, "isoformat") else now.isoformat()
                upd.pnl_r = _r(tp3)
                upd.pnl_pct = round((entry - tp3) / entry * 100, 4)
                closed_in_bar = True
                break
            if tp1 > 0 and l <= tp1: upd.hit_tp1 = True
            if tp2 > 0 and l <= tp2: upd.hit_tp2 = True
            new_sl = _trail_sl_short(entry, original_sl, tp1, tp2, tp3,
                                       upd.low_after_open, cur_sl)
            if new_sl != cur_sl:
                cur_sl = new_sl
                upd.sl_new = cur_sl

    if closed_in_bar:
        return upd

    # CRITICAL FINAL GUARD (added 2026-05-07): if stored extremes already
    # violated cur_sl but candle iteration missed it (e.g. no new 5m bar since
    # last_check_at, OR augmented high/low from latest_bar exceed iterated
    # extremes), close at trailing SL using cur_sl as exit price.
    #
    # ROOT CAUSE: the latest-bar augmentation block (above, at line ~510)
    # updates upd.high_after_open / upd.low_after_open and flags TP hits, but
    # does NOT check against cur_sl. The candle iteration loop checks SL only
    # for bars in `candles` (df_5m since last_check_at) — empty between cycles
    # when daemon polls faster than yfinance new-bar cadence.
    #
    # Without this guard: SL hits silently miss until trade expires, exiting
    # at last_close (often far worse than the SL level). User-reported bug
    # 2026-05-07: Active LONG a0f673a6 with trailing sl=$4703.12 +
    # low_after_open=$4694.20 stayed OPEN; History SHORT 0c7476eb with
    # sl=$4691.90 + high_after_open=$4711.30 expired at -3.01% instead of -1R.
    if side == "LONG" and upd.low_after_open is not None and upd.low_after_open <= cur_sl:
        upd.closed = True
        upd.status = "SL"
        upd.exit_price = cur_sl
        if cur_sl <= original_sl:
            upd.exit_reason = "sl_hit"
        elif abs(cur_sl - entry) < 1e-6:
            upd.exit_reason = "bep_hit"
        else:
            upd.exit_reason = "trailing_sl_hit"
        upd.closed_at = now.isoformat()
        upd.pnl_r = _r(cur_sl)
        upd.pnl_pct = round((cur_sl - entry) / entry * 100, 4)
        upd.hit_sl = (cur_sl <= original_sl)
        upd.sl_new = cur_sl if cur_sl != sl else None
        return upd
    if side == "SHORT" and upd.high_after_open is not None and upd.high_after_open >= cur_sl:
        upd.closed = True
        upd.status = "SL"
        upd.exit_price = cur_sl
        if cur_sl >= original_sl:
            upd.exit_reason = "sl_hit"
        elif abs(cur_sl - entry) < 1e-6:
            upd.exit_reason = "bep_hit"
        else:
            upd.exit_reason = "trailing_sl_hit"
        upd.closed_at = now.isoformat()
        upd.pnl_r = _r(cur_sl)
        upd.pnl_pct = round((entry - cur_sl) / entry * 100, 4)
        upd.hit_sl = (cur_sl >= original_sl)
        upd.sl_new = cur_sl if cur_sl != sl else None
        return upd

    # Not closed by SL/TP — check expiry
    expiry_dt = pd.Timestamp(trade["expiry_at"])
    if now >= expiry_dt:
        last_close = float(df_5m.iloc[-1]["close"])
        upd.closed = True
        upd.status = "EXPIRED"
        upd.exit_price = last_close
        upd.exit_reason = "expired"
        upd.closed_at = now.isoformat()
        upd.pnl_r = _r(last_close)
        upd.pnl_pct = round(
            ((last_close - entry) if side == "LONG" else (entry - last_close)) / entry * 100,
            4,
        )

    return upd


def _check_expiry(trade: dict, now: datetime, df_5m: pd.DataFrame) -> Optional[TradeUpdate]:
    """Only check expiry, no candle iteration (called when no new bars)."""
    expiry_dt = pd.Timestamp(trade["expiry_at"])
    if now < expiry_dt:
        return None
    last_close = float(df_5m.iloc[-1]["close"])
    entry = float(trade["entry"])
    side  = trade["side"]
    # Migration 013: pnl_r normalised to original_sl distance.
    original_sl_raw = trade.get("original_sl")
    original_sl = float(original_sl_raw) if original_sl_raw is not None else float(trade["sl"])
    slDist = abs(entry - original_sl)
    pnl_r = 0.0
    if slDist > 0:
        pnl_r = round(
            ((last_close - entry) if side == "LONG" else (entry - last_close)) / slDist,
            3,
        )
    return TradeUpdate(
        closed=True, status="EXPIRED",
        exit_price=last_close, exit_reason="expired",
        closed_at=now.isoformat(),
        pnl_r=pnl_r,
        pnl_pct=round(((last_close - entry) if side == "LONG" else (entry - last_close)) / entry * 100, 4),
    )


def _update_to_dict(u: TradeUpdate) -> dict:
    """Convert TradeUpdate dataclass to dict, omitting None fields (for PATCH)."""
    out: dict = {"last_check_at": datetime.now(timezone.utc).isoformat()}
    if u.hit_tp1: out["hit_tp1"] = True
    if u.hit_tp2: out["hit_tp2"] = True
    if u.hit_tp3: out["hit_tp3"] = True
    if u.hit_sl:  out["hit_sl"]  = True
    if u.high_after_open is not None: out["high_after_open"] = round(u.high_after_open, 2)
    if u.low_after_open  is not None: out["low_after_open"]  = round(u.low_after_open, 2)
    # Migration 013: persist BEP/lock-TP1 SL movement to active_trades.sl
    if u.sl_new is not None:
        out["sl"] = round(u.sl_new, 2)
        out["sl_moved_at"] = datetime.now(timezone.utc).isoformat()
    if u.closed:
        out["status"]      = u.status
        out["closed_at"]   = u.closed_at
        out["exit_price"]  = round(u.exit_price, 2) if u.exit_price is not None else None
        out["exit_reason"] = u.exit_reason
        out["pnl_r"]       = u.pnl_r
        out["pnl_pct"]     = u.pnl_pct
    return out
