"""Outcome tracker — evaluates rcs_signals against actual price action.

Background job: iterates rows with `outcome IS NULL OR outcome='PENDING'` and
checks if price has touched tp1, tp2, or sl since `generated_at`. Updates:
  - outcome ('TP1_HIT' | 'TP2_HIT' | 'SL_HIT' | 'EXPIRED')
  - outcome_price
  - outcome_at
  - prediction_correct (TRUE if direction outcome matches signal direction)

Why this matters:
  Without outcome data, we can't validate RCS calibration. With it, we get:
    - Real directional accuracy stats per timeframe
    - Training labels for v0.2 ML weight optimization
    - Drift signal when accuracy degrades

Expiry per timeframe (from config.yaml labeling.max_hold_candles):
    M5  : 24 candles  = 2 hours
    M15 : 32 candles  = 8 hours
    H1  : 48 candles  = 2 days

Conservative ordering: SL has priority over TP if both hit in same 5m bar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd


# Expiry per timeframe (candle count × candle duration in minutes)
EXPIRY_MINUTES = {
    "M5":  24 * 5,
    "M15": 32 * 15,
    "H1":  48 * 60,
}


def evaluate_pending_signals(
    store,
    df_5m: pd.DataFrame,
    log=print,
) -> int:
    """Iterate all pending rcs_signals and update outcome.
    Returns: number of signals updated.
    Idempotent — safe to run repeatedly.
    """
    if not store or not getattr(store, "has_db", False):
        return 0
    if df_5m is None or len(df_5m) == 0:
        log("[outcome] no df_5m provided, skipping")
        return 0

    try:
        r = (
            store._client.from_("rcs_signals")
            .select("id, generated_at, timeframe, direction, entry, sl, tp1, tp2")
            .or_("outcome.is.null,outcome.eq.PENDING")
            .neq("direction", "WAIT")            # WAIT signals don't have entry/sl/tp
            .order("generated_at", desc=False)
            .limit(200)
            .execute()
        )
        rows = r.data or []
    except Exception as e:
        msg = str(e).lower()
        if "rcs_signals" in msg or "relation" in msg or "does not exist" in msg:
            log("[outcome] rcs_signals table tidak ada — apply migration 008 first")
        else:
            log(f"[outcome] fetch failed: {e}")
        return 0

    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    modified = 0

    for row in rows:
        try:
            update = _evaluate_one(row, df_5m, now)
            if not update:
                continue
            store._client.from_("rcs_signals").update(update).eq("id", row["id"]).execute()
            modified += 1
            log(f"[outcome] id={row['id']} tf={row['timeframe']} dir={row['direction']} -> {update.get('outcome')} correct={update.get('prediction_correct')}")
        except Exception as e:
            log(f"[outcome] update id={row.get('id')} failed: {e}")

    return modified


def _evaluate_one(row: dict, df_5m: pd.DataFrame, now: datetime) -> Optional[dict]:
    """Decide what update to apply for a single rcs_signal row."""
    direction = row.get("direction")
    if direction not in ("LONG", "SHORT"):
        return None

    entry = float(row.get("entry") or 0)
    sl    = float(row.get("sl")    or 0)
    tp1   = float(row.get("tp1")   or 0)
    tp2   = float(row.get("tp2")   or 0)
    if entry <= 0 or sl <= 0:
        return None  # invalid levels

    # Parse generated_at (ISO string from Supabase)
    gen_at = pd.Timestamp(row["generated_at"])
    if gen_at.tzinfo is None:
        gen_at = gen_at.tz_localize("UTC")

    # Filter df_5m to bars >= generated_at
    candles = df_5m[df_5m.index >= gen_at]
    if len(candles) == 0:
        # No candles after signal generated yet — check if expired anyway
        return _check_expiry_if_needed(row, df_5m, now)

    # Iterate forward, check SL first (worst-case), then TP3 then TP1
    for ts, bar in candles.iterrows():
        h = float(bar["high"])
        l = float(bar["low"])

        if direction == "LONG":
            # SL = below entry, TP = above
            if l <= sl:
                return _close(row, "SL_HIT", sl, ts, correct=False)
            if tp2 > 0 and h >= tp2:
                return _close(row, "TP2_HIT", tp2, ts, correct=True)
            if tp1 > 0 and h >= tp1:
                return _close(row, "TP1_HIT", tp1, ts, correct=True)
        else:  # SHORT
            if h >= sl:
                return _close(row, "SL_HIT", sl, ts, correct=False)
            if tp2 > 0 and l <= tp2:
                return _close(row, "TP2_HIT", tp2, ts, correct=True)
            if tp1 > 0 and l <= tp1:
                return _close(row, "TP1_HIT", tp1, ts, correct=True)

    # Not hit yet — check expiry
    return _check_expiry_if_needed(row, df_5m, now)


def _check_expiry_if_needed(row: dict, df_5m: pd.DataFrame, now: datetime) -> Optional[dict]:
    """Return EXPIRED update if signal exceeded its TF's max_hold window."""
    tf = row.get("timeframe", "M15")
    max_min = EXPIRY_MINUTES.get(tf, 480)
    gen_at = pd.Timestamp(row["generated_at"])
    if gen_at.tzinfo is None:
        gen_at = gen_at.tz_localize("UTC")

    age_min = (now - gen_at.to_pydatetime()).total_seconds() / 60.0
    if age_min < max_min:
        return None  # still pending, not expired

    # Expired. Mark-to-market with last close.
    last_close = float(df_5m.iloc[-1]["close"])
    direction  = row.get("direction")
    entry      = float(row.get("entry") or 0)
    # Direction correctness: did price move in predicted direction at all?
    if direction == "LONG":
        correct = last_close > entry
    elif direction == "SHORT":
        correct = last_close < entry
    else:
        correct = False
    return {
        "outcome":            "EXPIRED",
        "outcome_price":      round(last_close, 3),
        "outcome_at":         now.isoformat(),
        "prediction_correct": correct,
    }


def _close(row: dict, status: str, exit_price: float, ts, correct: bool) -> dict:
    """Build update dict for closed signal."""
    closed_at = ts.isoformat() if hasattr(ts, "isoformat") else datetime.now(timezone.utc).isoformat()
    return {
        "outcome":            status,
        "outcome_price":      round(exit_price, 3),
        "outcome_at":         closed_at,
        "prediction_correct": correct,
    }
