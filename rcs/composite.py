"""RCS — REY Composite Signal (composite indicator).

INDIKATOR PAMUNGKAS yang gabungin SEMUA indikator yang udah ada di yeehee jadi
satu score tunggal. Bukan ML, bukan replacement untuk 12-agent — RCS berdiri di
samping sistem utama sebagai REFERENSI tambahan.

Filosofi:
    Setiap indikator individual punya bias (RSI = momentum, EMA = trend, SMC =
    structure, intermarket = macro). RCS combine semua dengan weighting yang
    sudah teruji secara empirical (configurable per regime).

Output:
    rcs_score: float dalam [-1.0, +1.0]
        > +0.4  : LONG bias kuat
        > +0.2  : LONG bias lemah
        [-0.2, +0.2]: NEUTRAL / wait
        < -0.2  : SHORT bias lemah
        < -0.4  : SHORT bias kuat

Komponen contributors (weighted, sums to 1.0 baseline):
    1. Trend score      (25%)  — EMA stack alignment + ADX strength
    2. Momentum score   (20%)  — RSI + MACD hist
    3. Structure score  (20%)  — SMC sweep, FVG, BOS, swing distance
    4. Intermarket score (15%) — DXY/TIPS/US10Y/VIX/COT (already aggregated)
    5. Volatility score (10%)  — ATR regime (penalty kalau extreme/quiet)
    6. Session score    (10%)  — boost di London/NY, penalty di Asia

Per-regime overrides (optional):
    Trending : tilt 30% to trend score, deboost structure
    Ranging  : tilt 30% to structure score, deboost trend
    Volatile : deboost momentum (whipsaw risk), boost intermarket
    Quiet    : deboost everything (low signal-to-noise)

Phase 2 future:
    Weights bisa di-fit via XGBoost berdasarkan historical outcome dari
    rcs_signals.outcome (TP1_HIT/SL_HIT/EXPIRED). Saat ini = manual heuristic
    yang reasonable.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd


# ─── Component weights ──────────────────────────────────────────────────────────

# Default weights (sum = 1.0)
DEFAULT_WEIGHTS = {
    "trend":       0.25,
    "momentum":    0.20,
    "structure":   0.20,
    "intermarket": 0.15,
    "volatility":  0.10,
    "session":     0.10,
}

# Per-regime weight overrides — applied multiplicatively then renormalized
REGIME_WEIGHT_TILT = {
    "trending_up": {"trend": 1.4, "momentum": 1.2, "structure": 0.7},
    "trending_dn": {"trend": 1.4, "momentum": 1.2, "structure": 0.7},
    "ranging":     {"trend": 0.6, "structure": 1.5, "session": 1.3},
    "volatile":    {"momentum": 0.7, "intermarket": 1.3, "volatility": 1.5},
    "quiet":       {"trend": 0.8, "momentum": 0.8, "structure": 1.2, "session": 1.2},
}


# Direction thresholds
THRESH_LONG_STRONG  =  0.40
THRESH_LONG_WEAK    =  0.20
THRESH_SHORT_WEAK   = -0.20
THRESH_SHORT_STRONG = -0.40


# ─── Score result types ─────────────────────────────────────────────────────────

@dataclass
class ComponentScore:
    """One component's contribution. score in [-1.0, +1.0]."""
    name:    str
    score:   float                 # [-1, +1] direction component
    weight:  float                 # final weight after regime tilt + renormalization
    detail:  str                   # human-readable for top-drivers display


@dataclass
class RCSResult:
    """Final composite output. Mirror columns of rcs_signals table."""
    rcs_score:       float                          # [-1, +1]
    direction:       str                            # 'LONG' | 'SHORT' | 'WAIT'
    confidence_pct:  int                            # [0, 95]
    components:      list[ComponentScore]           # all 6 contributors
    top_drivers:     list[str]                      # top 3 by abs(score * weight)
    regime:          str
    session:         str

    def to_dict(self) -> dict:
        return {
            "rcs_score":      round(self.rcs_score, 4),
            "direction":      self.direction,
            "confidence_pct": self.confidence_pct,
            "components": [
                {"name": c.name, "score": round(c.score, 4),
                 "weight": round(c.weight, 4), "detail": c.detail}
                for c in self.components
            ],
            "top_drivers": self.top_drivers,
            "regime":      self.regime,
            "session":     self.session,
        }


# ─── Component scorers ──────────────────────────────────────────────────────────

def _score_trend(df_4h: pd.DataFrame | None) -> ComponentScore:
    """EMA stack alignment + ADX strength → trend conviction.
    +1.0 = strong bullish trend, -1.0 = strong bearish, 0 = no clear trend.
    """
    if df_4h is None or len(df_4h) < 50:
        return ComponentScore("trend", 0.0, 0.0, "no HTF data")
    last = df_4h.iloc[-1]
    e9, e21, e50, e200 = last.get("ema9"), last.get("ema21"), last.get("ema50"), last.get("ema200")
    adx = last.get("adx")

    if any(x is None or pd.isna(x) for x in (e9, e21, e50, e200)):
        return ComponentScore("trend", 0.0, 0.0, "EMA missing")

    # Stack alignment: count how many "stair-step" relationships are in same direction
    bullish_legs = sum([e9 > e21, e21 > e50, e50 > e200])
    bearish_legs = sum([e9 < e21, e21 < e50, e50 < e200])

    if bullish_legs == 3:
        base_score = 1.0
        label = "EMA stack fully bullish"
    elif bullish_legs == 2:
        base_score = 0.5
        label = "EMA stack mostly bullish"
    elif bearish_legs == 3:
        base_score = -1.0
        label = "EMA stack fully bearish"
    elif bearish_legs == 2:
        base_score = -0.5
        label = "EMA stack mostly bearish"
    else:
        base_score = 0.0
        label = "EMA stack mixed"

    # ADX modulator: stronger ADX = more conviction
    if pd.notna(adx):
        if adx >= 30:
            mod = 1.0
            adx_label = f"ADX={adx:.0f} strong"
        elif adx >= 20:
            mod = 0.7
            adx_label = f"ADX={adx:.0f} dev"
        else:
            mod = 0.3   # weak ADX = haircut conviction
            adx_label = f"ADX={adx:.0f} weak"
    else:
        mod = 0.5
        adx_label = "ADX n/a"

    score = base_score * mod
    return ComponentScore("trend", score, 0.0, f"{label}, {adx_label}")


def _score_momentum(df_15m: pd.DataFrame | None) -> ComponentScore:
    """RSI position + MACD histogram → momentum direction + strength."""
    if df_15m is None or len(df_15m) < 30:
        return ComponentScore("momentum", 0.0, 0.0, "no LTF data")
    last = df_15m.iloc[-1]
    rsi  = last.get("rsi14")
    hist = last.get("hist")

    score = 0.0
    parts = []
    if pd.notna(rsi):
        # RSI: 50 = neutral, >50 = bullish, <50 = bearish; extreme = mean-revert risk
        if rsi >= 70:
            score += -0.3   # overbought, mean-revert risk
            parts.append(f"RSI={rsi:.0f} overbought")
        elif rsi >= 55:
            score += 0.4
            parts.append(f"RSI={rsi:.0f} bullish")
        elif rsi <= 30:
            score += 0.3   # oversold, mean-revert opportunity (bullish)
            parts.append(f"RSI={rsi:.0f} oversold")
        elif rsi <= 45:
            score += -0.4
            parts.append(f"RSI={rsi:.0f} bearish")
        else:
            parts.append(f"RSI={rsi:.0f} neutral")

    if pd.notna(hist):
        # MACD hist: positive = bullish momentum
        if abs(hist) > 0.5:  # significant
            score += 0.4 if hist > 0 else -0.4
            parts.append(f"MACD hist={hist:+.2f}")
        elif abs(hist) > 0.1:
            score += 0.2 if hist > 0 else -0.2
            parts.append(f"MACD hist={hist:+.2f} weak")

    score = float(np.clip(score, -1.0, 1.0))
    return ComponentScore("momentum", score, 0.0, ", ".join(parts) or "neutral")


def _score_structure(df_15m: pd.DataFrame | None) -> ComponentScore:
    """SMC sweep + FVG + BOS + swing distance → structure conviction."""
    if df_15m is None or len(df_15m) < 30:
        return ComponentScore("structure", 0.0, 0.0, "no SMC data")

    last = df_15m.iloc[-1]
    recent5 = df_15m.tail(5)

    score = 0.0
    parts = []
    # SMC events (bullish recently within 5 bars)
    if "bull_sweep" in df_15m.columns and recent5["bull_sweep"].any():
        score += 0.35
        parts.append("bull sweep")
    if "bear_sweep" in df_15m.columns and recent5["bear_sweep"].any():
        score -= 0.35
        parts.append("bear sweep")
    if "fvg_bull" in df_15m.columns and recent5["fvg_bull"].any():
        score += 0.25
        parts.append("FVG bull")
    if "fvg_bear" in df_15m.columns and recent5["fvg_bear"].any():
        score -= 0.25
        parts.append("FVG bear")
    if last.get("bos_up"):
        score += 0.20
        parts.append("BOS up")
    if last.get("bos_dn"):
        score -= 0.20
        parts.append("BOS dn")

    score = float(np.clip(score, -1.0, 1.0))
    return ComponentScore("structure", score, 0.0, ", ".join(parts) or "no SMC events")


def _score_intermarket(intermarket: dict | None) -> ComponentScore:
    """Use existing intermarket_score (already weighted DXY/TIPS/US10Y/VIX/SPX).

    The intermarket module returns score in [-1, +1] where:
      +1 = bullish gold (DXY weak, real yields down, vol up)
      -1 = bearish gold
    """
    if not intermarket:
        return ComponentScore("intermarket", 0.0, 0.0, "no intermarket data")
    score = float(intermarket.get("score") or 0.0)
    components = (intermarket.get("components") or {})
    drivers = []
    for name in ("tip", "dxy", "us10y", "vix"):
        c = components.get(name)
        if c and c.get("note"):
            drivers.append(c["note"][:40])
    return ComponentScore("intermarket", score, 0.0, "; ".join(drivers[:3]) or "neutral")


def _score_volatility(df_4h: pd.DataFrame | None) -> ComponentScore:
    """ATR regime: extreme = penalty (whipsaw), quiet = penalty (low edge),
    normal/high = positive (good for directional trading).

    NOTE: this is a DIRECTIONAL-NEUTRAL component. We just penalize bad regimes.
    Returns 0 score for direction (multiplied later by other directional components).

    Implementation: Returns positive score if regime favorable, negative if
    unfavorable. To keep RCS sign coherent, we adopt convention: score = 0 here,
    but use weight to MODULATE other components. Simpler: small positive boost
    in good regimes, penalty in bad.
    """
    if df_4h is None or len(df_4h) < 50 or "atr14" not in df_4h.columns:
        return ComponentScore("volatility", 0.0, 0.0, "no ATR data")

    atr_now    = float(df_4h["atr14"].iloc[-1])
    atr_avg20  = float(df_4h["atr14"].tail(20).mean())
    if atr_avg20 <= 0:
        return ComponentScore("volatility", 0.0, 0.0, "ATR zero baseline")
    ratio = atr_now / atr_avg20

    # Score: positive if normal-high vol (favorable), negative if extreme/quiet
    if ratio > 2.0:
        score = -0.5     # extreme vol = whipsaw
        label = f"ATR={ratio:.2f}x EXTREME (whipsaw risk)"
    elif ratio > 1.5:
        score = +0.3     # high vol = good for trend
        label = f"ATR={ratio:.2f}x high (trend favorable)"
    elif ratio >= 0.7:
        score = +0.5     # normal vol = ideal
        label = f"ATR={ratio:.2f}x normal (ideal)"
    elif ratio >= 0.4:
        score = -0.2     # low vol = drift
        label = f"ATR={ratio:.2f}x low"
    else:
        score = -0.5     # very quiet
        label = f"ATR={ratio:.2f}x QUIET (no edge)"

    return ComponentScore("volatility", score, 0.0, label)


def _score_session(session: str | None) -> ComponentScore:
    """Session boost: London/NY = good for directional, Asia = penalty."""
    if not session:
        return ComponentScore("session", 0.0, 0.0, "session unknown")

    s = (session or "").lower()
    if "lon_ny" in s or "overlap" in s:
        return ComponentScore("session", 0.7, 0.0, f"{session} (peak liquidity)")
    if s in ("london", "ny"):
        return ComponentScore("session", 0.5, 0.0, f"{session} (active)")
    if s == "asia":
        return ComponentScore("session", -0.3, 0.0, "asia (low vol, ranging bias)")
    return ComponentScore("session", 0.0, 0.0, f"{session}")


# ─── Main composite function ────────────────────────────────────────────────────

def _apply_regime_tilt(weights: dict, regime: str | None) -> dict:
    """Apply per-regime weight tilt + renormalize to sum=1."""
    if not regime or regime not in REGIME_WEIGHT_TILT:
        # Renormalize default weights anyway in case caller mutates them
        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()} if total > 0 else weights

    tilt = REGIME_WEIGHT_TILT[regime]
    tilted = {k: v * tilt.get(k, 1.0) for k, v in weights.items()}
    total = sum(tilted.values())
    if total <= 0:
        return weights
    return {k: v / total for k, v in tilted.items()}


def compute_rcs(
    df_4h:        pd.DataFrame | None,
    df_15m:       pd.DataFrame | None,
    intermarket:  dict | None,
    session:      str | None,
    regime:       str | None,
    custom_weights: dict | None = None,
) -> RCSResult:
    """Compute RCS composite score.

    Args:
        df_4h: HTF dataframe with EMA9/21/50/200, ADX, ATR14
        df_15m: LTF dataframe with RSI14, MACD hist, SMC marks
        intermarket: dict from features.intermarket.intermarket_score()
        session: 'asia' | 'london' | 'ny' | 'lon_ny_overlap' | 'off_hours'
        regime: 'trending_up' | 'trending_dn' | 'ranging' | 'volatile' | 'quiet'
        custom_weights: override DEFAULT_WEIGHTS

    Returns:
        RCSResult with score, direction, confidence, components, top drivers.
    """
    base_weights = custom_weights or DEFAULT_WEIGHTS
    weights = _apply_regime_tilt(base_weights, regime)

    # Score each component (returns score [-1, +1] but weight=0; we'll set weight)
    components_raw = [
        _score_trend(df_4h),
        _score_momentum(df_15m),
        _score_structure(df_15m),
        _score_intermarket(intermarket),
        _score_volatility(df_4h),
        _score_session(session),
    ]

    # Assign weights from the regime-tilted weights dict
    components = []
    weighted_sum = 0.0
    for c in components_raw:
        w = float(weights.get(c.name, 0.0))
        components.append(ComponentScore(c.name, c.score, w, c.detail))
        weighted_sum += c.score * w

    # rcs_score is the weighted sum, bounded to [-1, +1]
    rcs_score = float(np.clip(weighted_sum, -1.0, 1.0))

    # Direction
    if rcs_score >= THRESH_LONG_STRONG:
        direction = "LONG"
    elif rcs_score <= THRESH_SHORT_STRONG:
        direction = "SHORT"
    elif rcs_score >= THRESH_LONG_WEAK or rcs_score <= THRESH_SHORT_WEAK:
        # Weak side: still indicate direction but mark as low confidence
        direction = "LONG" if rcs_score > 0 else "SHORT"
    else:
        direction = "WAIT"

    # Confidence: |score| × 100, capped 95
    confidence_pct = int(min(95, abs(rcs_score) * 100))

    # Top drivers: components with largest abs(score * weight)
    sorted_comps = sorted(components, key=lambda c: abs(c.score * c.weight), reverse=True)
    top_drivers = [
        f"{c.name}: {c.detail} (s={c.score:+.2f} w={c.weight:.2f})"
        for c in sorted_comps[:3] if abs(c.score * c.weight) > 0.01
    ]

    return RCSResult(
        rcs_score=rcs_score,
        direction=direction,
        confidence_pct=confidence_pct,
        components=components,
        top_drivers=top_drivers,
        regime=regime or "unknown",
        session=session or "unknown",
    )


# ─── Smoke test ─────────────────────────────────────────────────────────────────

def _smoke():
    """Run via: python -m rcs.composite"""
    # Fake data
    idx = pd.date_range("2026-05-05", periods=60, freq="4h")
    df_4h = pd.DataFrame({
        "close": np.linspace(4500, 4600, 60),
        "ema9":  np.linspace(4495, 4595, 60),
        "ema21": np.linspace(4490, 4590, 60),
        "ema50": np.linspace(4485, 4585, 60),
        "ema200": np.linspace(4470, 4570, 60),
        "adx":  28.0, "atr14": 8.5,
    }, index=idx)
    df_15m = pd.DataFrame({
        "rsi14": 60.0, "hist": 1.5,
        "bull_sweep": False, "bear_sweep": False,
        "fvg_bull": False, "fvg_bear": False,
        "bos_up": False, "bos_dn": False,
    }, index=pd.date_range("2026-05-05", periods=30, freq="15min"))
    intermarket = {
        "score": 0.35,
        "components": {
            "tip": {"value": 0.003, "score": 0.5, "note": "TIPS 5-bar +0.30%"},
            "dxy": {"value": -0.001, "score": 0.4, "note": "DXY 5-bar -0.10%"},
        },
    }

    result = compute_rcs(
        df_4h=df_4h, df_15m=df_15m,
        intermarket=intermarket, session="london", regime="trending_up",
    )
    import json
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    _smoke()
