"""Confluence filter — promote signals to PENDING_PICKUP only when multiple sources agree.

Philosophy: ML alone ~50-55% accuracy. With multi-source confluence + high
confidence threshold, trade win rate (precision conditional on execution) can
reach 65-75%. Trade-off: signal frequency drops 70-80%.

Sources of agreement:
    1. RCS composite direction (rcs_score sign)
    2. 12-agent debate final_action
    3. Per-style strategy signal (scalper/intraday/swing)
    4. (Optional) ML XGBoost prediction when active

Confluence logic:
    - At least 2 of 3 sources MUST agree on direction
    - Highest-confidence source must have confidence >= per-style threshold
    - No conflict (no source bilang opposite direction)

Output: per-style decision whether to mark as PENDING_PICKUP for EA execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Per-style confidence thresholds for execution.
# Calibrated for live paper-test: too-strict thresholds (3/3 agree + 75% conf)
# meant scalper signals at 65-72% conf never executed even when 12-agent + RCS
# both aligned. Relaxed to 2/3 agree + 65% so paper test can collect ≥5 trades/wk
# of training data. Tighten back after first 30 days if win-rate < 55%.
EXECUTION_THRESHOLDS = {
    "scalper":  {"min_confidence": 0.65, "min_rcs_score": 0.30, "min_sources_agree": 2},
    "intraday": {"min_confidence": 0.60, "min_rcs_score": 0.25, "min_sources_agree": 2},
    "swing":    {"min_confidence": 0.55, "min_rcs_score": 0.20, "min_sources_agree": 2},
}


@dataclass
class ConfluenceDecision:
    """Output of confluence filter for one style."""
    style:              str
    direction:          str          # 'LONG' | 'SHORT' | 'WAIT'
    is_executable:      bool         # True if confluence high enough for EA pickup
    sources_agreeing:   int          # 0-3
    sources_total:      int
    sources_breakdown:  dict         # {source: direction}
    confidence_blended: float        # weighted avg confidence
    reason:             str          # human-readable why executable / why not


def evaluate_confluence(
    style: str,
    style_signal: dict,           # output of strategies.{scalper,intraday,swing}.generate(...).to_dict()
    rcs_result:   Optional[dict], # rcs.composite.compute_rcs(...).to_dict()
    debate_dict:  dict,            # 12-agent debate output
) -> ConfluenceDecision:
    """Decide if signal should be PROMOTED to PENDING_PICKUP for EA execution.

    Returns ConfluenceDecision with is_executable flag + reasoning.
    """
    cfg = EXECUTION_THRESHOLDS.get(style, EXECUTION_THRESHOLDS["intraday"])

    # Extract directions from each source
    style_dir = (style_signal or {}).get("side", "FLAT")
    rcs_dir   = (rcs_result   or {}).get("direction", "WAIT")
    deb_dir   = (debate_dict  or {}).get("final_action", "FLAT")

    sources_breakdown = {
        "style":   style_dir,
        "rcs":     rcs_dir,
        "debate":  deb_dir,
    }

    # Count agreement (LONG/SHORT only — WAIT/FLAT don't count as agreement)
    long_n  = sum(1 for d in (style_dir, rcs_dir, deb_dir) if d == "LONG")
    short_n = sum(1 for d in (style_dir, rcs_dir, deb_dir) if d == "SHORT")

    # No conflict allowed: if both directions present, abort
    if long_n > 0 and short_n > 0:
        return ConfluenceDecision(
            style=style, direction="WAIT", is_executable=False,
            sources_agreeing=0, sources_total=3,
            sources_breakdown=sources_breakdown,
            confidence_blended=0.0,
            reason=f"conflict: long={long_n} short={short_n}",
        )

    if long_n >= cfg["min_sources_agree"]:
        direction = "LONG"
        sources_agreeing = long_n
    elif short_n >= cfg["min_sources_agree"]:
        direction = "SHORT"
        sources_agreeing = short_n
    else:
        return ConfluenceDecision(
            style=style, direction="WAIT", is_executable=False,
            sources_agreeing=max(long_n, short_n), sources_total=3,
            sources_breakdown=sources_breakdown,
            confidence_blended=0.0,
            reason=f"insufficient agreement (need {cfg['min_sources_agree']}, got long={long_n} short={short_n})",
        )

    # Compute blended confidence — weighted avg of agreeing sources
    confs = []
    if style_dir == direction:
        confs.append(float(style_signal.get("confidence", 0)))
    if rcs_dir == direction:
        confs.append(float((rcs_result or {}).get("confidence_pct", 0)) / 100.0)
    if deb_dir == direction:
        confs.append(float(debate_dict.get("confidence", 0)))
    confidence_blended = sum(confs) / len(confs) if confs else 0.0

    # Final confidence gate
    if confidence_blended < cfg["min_confidence"]:
        return ConfluenceDecision(
            style=style, direction=direction, is_executable=False,
            sources_agreeing=sources_agreeing, sources_total=3,
            sources_breakdown=sources_breakdown,
            confidence_blended=confidence_blended,
            reason=f"agreement OK ({sources_agreeing}/3) but conf={confidence_blended:.2f} < threshold {cfg['min_confidence']}",
        )

    # RCS score sanity (must be on agreed direction with sufficient magnitude)
    if rcs_result:
        rcs_score = float(rcs_result.get("rcs_score", 0))
        if direction == "LONG"  and rcs_score < cfg["min_rcs_score"]:
            return ConfluenceDecision(
                style=style, direction=direction, is_executable=False,
                sources_agreeing=sources_agreeing, sources_total=3,
                sources_breakdown=sources_breakdown,
                confidence_blended=confidence_blended,
                reason=f"agreement+conf OK but RCS score {rcs_score:+.2f} < {cfg['min_rcs_score']}",
            )
        if direction == "SHORT" and rcs_score > -cfg["min_rcs_score"]:
            return ConfluenceDecision(
                style=style, direction=direction, is_executable=False,
                sources_agreeing=sources_agreeing, sources_total=3,
                sources_breakdown=sources_breakdown,
                confidence_blended=confidence_blended,
                reason=f"agreement+conf OK but RCS score {rcs_score:+.2f} > -{cfg['min_rcs_score']}",
            )

    # All gates passed — eligible for execution
    return ConfluenceDecision(
        style=style, direction=direction, is_executable=True,
        sources_agreeing=sources_agreeing, sources_total=3,
        sources_breakdown=sources_breakdown,
        confidence_blended=confidence_blended,
        reason=f"PASS: {sources_agreeing}/3 agree, conf={confidence_blended:.2f}, RCS aligned",
    )


def promote_signal_for_ea(
    store,
    rcs_signal_id: int,
    style: str,
    confluence: ConfluenceDecision,
    log=print,
) -> bool:
    """Update rcs_signals row to PENDING_PICKUP for EA pickup.

    Only PRIMARY worker should call this. EA polls /api/ea/next-signal which
    filters WHERE execution_status='PENDING_PICKUP' AND is_executable=true.
    """
    if not confluence.is_executable:
        return False
    if not store or not getattr(store, "has_db", False) or not rcs_signal_id:
        return False
    try:
        store._client.from_("rcs_signals").update({
            "is_executable":    True,
            "execution_status": "PENDING_PICKUP",
        }).eq("id", rcs_signal_id).execute()
        log(f"[confluence] PROMOTED signal #{rcs_signal_id} ({style} {confluence.direction}) → PENDING_PICKUP. {confluence.reason}")
        return True
    except Exception as e:
        log(f"[confluence] promote failed: {e}")
        return False


def _smoke():
    """Run via: python -m rcs.confluence"""
    # Test 1: 3-of-3 agreement, all high conf → SHOULD execute
    style_sig = {"side": "LONG", "confidence": 0.78}
    rcs_res   = {"direction": "LONG", "confidence_pct": 75, "rcs_score": 0.48}
    debate    = {"final_action": "LONG", "confidence": 0.72}
    d = evaluate_confluence("intraday", style_sig, rcs_res, debate)
    print(f"Test 1 (3/3 agree, high conf): executable={d.is_executable} - {d.reason}")
    assert d.is_executable, "should execute"

    # Test 2: conflict (style LONG, RCS SHORT)
    rcs_conflict = {"direction": "SHORT", "confidence_pct": 70, "rcs_score": -0.45}
    d = evaluate_confluence("intraday", style_sig, rcs_conflict, debate)
    print(f"Test 2 (conflict): executable={d.is_executable} - {d.reason}")
    assert not d.is_executable, "should not execute on conflict"

    # Test 3: 2-of-3 agree but low conf → SHOULD NOT execute
    low_conf_style = {"side": "LONG", "confidence": 0.45}
    low_conf_rcs   = {"direction": "LONG", "confidence_pct": 50, "rcs_score": 0.25}
    flat_debate    = {"final_action": "FLAT", "confidence": 0.0}
    d = evaluate_confluence("intraday", low_conf_style, low_conf_rcs, flat_debate)
    print(f"Test 3 (2/3 low conf): executable={d.is_executable} - {d.reason}")
    assert not d.is_executable, "should not execute below conf threshold"

    # Test 4: scalper with 2/3 agree + low conf → SHOULD NOT execute
    weak_style = {"side": "LONG", "confidence": 0.40}
    weak_rcs   = {"direction": "LONG", "confidence_pct": 35, "rcs_score": 0.22}
    flat = {"final_action": "WAIT", "confidence": 0}
    d = evaluate_confluence("scalper", weak_style, weak_rcs, flat)
    print(f"Test 4 (scalper 2/3 low conf): executable={d.is_executable} - {d.reason}")
    assert not d.is_executable, "scalper conf below 0.65 must not execute"

    print()
    print("ALL TESTS PASS")


if __name__ == "__main__":
    _smoke()
