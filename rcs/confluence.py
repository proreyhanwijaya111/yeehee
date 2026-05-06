"""EA execution gate — simplified per Opsi A (2026-05).

Earlier version required ≥2/3 sources agree (style + RCS + 12-agent debate)
plus per-style min_confidence + min_rcs_score. This combined ~9 layers in
total upstream produced a compounded ~13% pass rate — virtually nothing
reached PENDING_PICKUP.

User feedback: signals jarang muncul, EA gak jalan, kalo execute manual aja
hasilnya lebih bagus (8/9 win semalem dengan 12-agent only). Decision: kembali
ke V1-style gating where ONE filter rules: style strategy itself.

Current gate (Opsi A):
    1. style_signal.side ∈ {LONG, SHORT}
    2. style_signal.confidence ≥ ea_min_confidence_pct (from app_settings)

That's it. RCS becomes display-only reference. 12-agent debate result is
shown in UI as overall market view but doesn't block per-style execution.

If win rate < 50% after 30 days paper test, ADD filters back based on data
(not on prior beliefs about what should help).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Floor when app_settings.ea_min_confidence_pct unavailable.
# 0.55 chosen to balance frequency vs quality on $500 demo paper test.
DEFAULT_MIN_CONFIDENCE = 0.55


@dataclass
class EaDecision:
    """Whether a per-style signal should be promoted to EA pickup queue."""
    style:        str
    side:         str           # 'LONG' | 'SHORT' | 'WAIT'
    is_executable: bool
    confidence:   float
    reason:       str           # short human-readable reason


def evaluate_for_ea(
    style: str,
    style_signal: dict,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> EaDecision:
    """Decide if a per-style signal qualifies for EA auto-execution.

    Pure rule: directional signal (LONG/SHORT) with confidence above threshold.
    Returns reason string for log/audit, never raises.
    """
    sig = style_signal or {}
    side = sig.get("side", "FLAT")
    conf = float(sig.get("confidence", 0) or 0)

    if side not in ("LONG", "SHORT"):
        return EaDecision(style=style, side="WAIT", is_executable=False,
                          confidence=conf, reason=f"side={side}")
    if conf < min_confidence:
        return EaDecision(style=style, side=side, is_executable=False,
                          confidence=conf,
                          reason=f"conf={conf:.2f} < min {min_confidence:.2f}")
    return EaDecision(style=style, side=side, is_executable=True,
                      confidence=conf, reason=f"PASS conf={conf:.2f}")


def promote_signal_for_ea(
    store,
    rcs_signal_id: int,
    decision: EaDecision,
    log=print,
) -> bool:
    """Mark rcs_signals row PENDING_PICKUP for EA polling.

    EA picks up via /api/ea/next-signal which atomically claims rows where
    execution_status='PENDING_PICKUP' AND is_executable=true.
    """
    if not decision.is_executable:
        return False
    if not store or not getattr(store, "has_db", False) or not rcs_signal_id:
        return False
    try:
        store._client.from_("rcs_signals").update({
            "is_executable":    True,
            "execution_status": "PENDING_PICKUP",
        }).eq("id", rcs_signal_id).execute()
        log(f"[ea] PROMOTE #{rcs_signal_id} {decision.style} {decision.side} conf={decision.confidence:.2f}")
        return True
    except Exception as e:
        log(f"[ea] promote failed: {e}")
        return False


# ─── Backward-compat shim ────────────────────────────────────────────────────
# Older callers / migrations may still import evaluate_confluence. Keep a thin
# wrapper that delegates to the new gate. Sources agreement columns dropped.

@dataclass
class ConfluenceDecision:
    style: str
    direction: str
    is_executable: bool
    sources_agreeing: int = 0
    sources_total: int = 1
    sources_breakdown: Optional[dict] = None
    confidence_blended: float = 0.0
    reason: str = ""


def evaluate_confluence(style, style_signal, rcs_result=None, debate_dict=None,
                        min_confidence: float = DEFAULT_MIN_CONFIDENCE):
    """Deprecated — kept for backward import compat. Use evaluate_for_ea."""
    d = evaluate_for_ea(style, style_signal, min_confidence=min_confidence)
    return ConfluenceDecision(
        style=d.style,
        direction=d.side,
        is_executable=d.is_executable,
        sources_agreeing=1 if d.is_executable else 0,
        sources_total=1,
        sources_breakdown={"style": d.side},
        confidence_blended=d.confidence,
        reason=d.reason,
    )


def _smoke():
    """python -m rcs.confluence"""
    # PASS: LONG with conf above threshold
    d = evaluate_for_ea("scalper", {"side": "LONG", "confidence": 0.70})
    print(f"PASS test: {d}")
    assert d.is_executable

    # FAIL: FLAT
    d = evaluate_for_ea("scalper", {"side": "FLAT", "confidence": 0.0})
    print(f"FLAT test: {d}")
    assert not d.is_executable

    # FAIL: confidence below
    d = evaluate_for_ea("intraday", {"side": "SHORT", "confidence": 0.40},
                        min_confidence=0.55)
    print(f"LOW conf test: {d}")
    assert not d.is_executable

    # PASS: edge of threshold
    d = evaluate_for_ea("swing", {"side": "LONG", "confidence": 0.55},
                        min_confidence=0.55)
    print(f"EDGE test: {d}")
    assert d.is_executable

    print("\nALL TESTS PASS")


if __name__ == "__main__":
    _smoke()
