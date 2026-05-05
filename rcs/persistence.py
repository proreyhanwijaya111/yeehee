"""Push/read RCS signal to/from Supabase rcs_signals table.

Uses existing SettingsStore from ai_agent.orchestrator for consistency with
the main daemon's Supabase connection. Graceful fallback if migration 008
not yet applied (table missing) — daemon won't crash, just logs warning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from rcs.composite import RCSResult


def push_rcs_signal(
    store,
    result: RCSResult,
    timeframe: str,
    spot_price: float,
    atr_14: float,
    broker_symbol: str = "XAUUSD",
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp1: Optional[float] = None,
    tp2: Optional[float] = None,
    model_version: str = "rcs_composite_v0.1",
    log=print,
) -> Optional[int]:
    """Insert RCSResult to rcs_signals table. Returns id or None on failure."""
    if not store or not getattr(store, "has_db", False):
        return None

    # Compute distance in points (for EA consumption later — Phase 3)
    point_size = 0.01  # XAU/USD standard
    sl_points  = int(round(abs(spot_price - sl) / point_size)) if sl else None
    tp1_points = int(round(abs(spot_price - tp1) / point_size)) if tp1 else None
    tp2_points = int(round(abs(spot_price - tp2) / point_size)) if tp2 else None

    # 3-class probabilities approximate from rcs_score:
    # Map score ∈ [-1, +1] → (p_short, p_neutral, p_long) softmax-ish
    s = result.rcs_score
    # Simple linear allocation; sum=1
    if s > 0:
        prob_long    = round(0.33 + s * 0.5, 4)        # up to 0.83
        prob_short   = round(0.33 - s * 0.25, 4)
        prob_neutral = round(1.0 - prob_long - prob_short, 4)
    else:
        prob_short   = round(0.33 + abs(s) * 0.5, 4)
        prob_long    = round(0.33 - abs(s) * 0.25, 4)
        prob_neutral = round(1.0 - prob_long - prob_short, 4)
    # Bound to [0, 1]
    prob_long    = max(0.0, min(1.0, prob_long))
    prob_short   = max(0.0, min(1.0, prob_short))
    prob_neutral = max(0.0, min(1.0, prob_neutral))

    # feature_snapshot: just per-component score + weight (compact JSON)
    feature_snapshot = {
        c.name: {"score": round(c.score, 4), "weight": round(c.weight, 4),
                 "detail": c.detail[:80]}
        for c in result.components
    }
    shap_top_5 = [{"name": c.name, "contribution": round(c.score * c.weight, 4),
                   "detail": c.detail[:100]}
                  for c in sorted(result.components,
                                  key=lambda c: abs(c.score * c.weight),
                                  reverse=True)[:5]]

    payload = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "timeframe":      timeframe,
        "broker_symbol":  broker_symbol,
        "spot_price":     round(float(spot_price), 3),
        "atr_14":         round(float(atr_14), 3),
        "prob_long":      prob_long,
        "prob_short":     prob_short,
        "prob_neutral":   prob_neutral,
        "rcs_score":      round(result.rcs_score, 4),
        "direction":      result.direction,
        "entry":          round(entry, 3) if entry else None,
        "sl":             round(sl, 3)    if sl    else None,
        "tp1":            round(tp1, 3)   if tp1   else None,
        "tp2":            round(tp2, 3)   if tp2   else None,
        "sl_points":      sl_points,
        "tp1_points":     tp1_points,
        "tp2_points":     tp2_points,
        "confidence_pct": result.confidence_pct,
        "feature_snapshot": feature_snapshot,
        "shap_top_5":     shap_top_5,
        "model_version":  model_version,
        "is_executable":  False,
        "execution_status": "NOT_FOR_EXECUTION",
    }

    try:
        r = store._client.from_("rcs_signals").insert(payload).execute()
        new_id = (r.data or [{}])[0].get("id")
        log(f"[rcs] pushed signal id={new_id} tf={timeframe} dir={result.direction} score={result.rcs_score:+.3f} conf={result.confidence_pct}%")
        return new_id
    except Exception as e:
        msg = str(e).lower()
        if "rcs_signals" in msg or "relation" in msg or "does not exist" in msg:
            log(f"[rcs] table rcs_signals tidak ada — apply migration 008. Skipping push.")
        else:
            log(f"[rcs] push failed: {e}")
        return None


def get_latest_rcs(store, timeframe: Optional[str] = None) -> Optional[dict]:
    """Read most recent rcs_signal. Used by 12-agent system as reference input."""
    if not store or not getattr(store, "has_db", False):
        return None
    try:
        q = store._client.from_("rcs_signals").select("*").order("generated_at", desc=True).limit(1)
        if timeframe:
            q = q.eq("timeframe", timeframe)
        r = q.execute()
        rows = r.data or []
        return rows[0] if rows else None
    except Exception:
        return None
