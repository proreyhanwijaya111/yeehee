"""Pattern Expert agent — adapted from user's PATTERN EXPERT AGENT/ folder.

Original module is full-fledged with backtest engine + CLI. This adaptation
extracts ONLY the live-detection path needed by `local_agents.pattern_expert_agent`:

  - Pattern detectors (15 candlestick patterns from Bulkowski/Nison)
  - Session classification (Asian/London/Overlap/NY)
  - Bundled per-timeframe statistics (win-rate / avg_R / production_role)
  - Conditional multipliers per spec (at_key_level, trend_aligned, etc.)

Conformance to project:
  - Lowercase OHLC columns (open, high, low, close, volume)
  - DataFrame index = pd.DatetimeIndex (UTC)
  - Returns dict, NOT AgentVerdict (caller wraps it) — keeps this file pure.

For full backtest/CLI use, see PATTERN EXPERT AGENT/pattern_expert.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ─── Stats bundle (loaded once at module import) ─────────────────────────────
# Stats sourced from synthetic 16y daily + 6mo intraday session-aware backtest.
# Rebuild via PATTERN EXPERT AGENT/pattern_expert.py if needed.

_STATS_PATH_D1   = Path(__file__).parent / "pattern_stats_d1.json"
_STATS_PATH_INTRA = Path(__file__).parent / "pattern_stats_intraday.json"


def _load_stats() -> dict:
    """Returns {timeframe: [{name, win_rate, avg_R, role, ...}]}.

    Falls back to empty dict if files missing — agent then runs in
    "detector only" mode without weighted scoring.
    """
    out: dict = {"D1": [], "M30": [], "M15": [], "M5": []}
    try:
        if _STATS_PATH_D1.exists():
            out["D1"] = json.loads(_STATS_PATH_D1.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        if _STATS_PATH_INTRA.exists():
            data = json.loads(_STATS_PATH_INTRA.read_text(encoding="utf-8"))
            for tf in ("M5", "M15", "M30"):
                if tf in data:
                    out[tf] = data[tf]
    except Exception:
        pass
    return out


_STATS = _load_stats()

# Pattern → expected role (whitelist). Anything else is filtered out.
PRODUCTION_ROLES_TRADEABLE = {"primary_long", "primary_short", "primary_scalp",
                               "secondary_long", "secondary_short"}
PRODUCTION_ROLES_FILTER    = {"filter_or_confirmation"}
PRODUCTION_ROLES_AVOID     = {"weak_avoid", "exit_signal_only",
                              "near_breakeven_avoid_unless_high_conviction",
                              "DO_NOT_TRADE_standalone_use_only_as_exit_or_confluence"}


# ─── Indicator helpers (reused from user's module, lean version) ────────────

def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    h_l  = df["high"] - df["low"]
    h_pc = (df["high"] - df["close"].shift(1)).abs()
    l_pc = (df["low"]  - df["close"].shift(1)).abs()
    df["_tr"]      = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    df["_atr14"]   = df["_tr"].rolling(14).mean()
    df["_body"]    = (df["close"] - df["open"]).abs()
    df["_upperW"]  = df["high"] - df[["open", "close"]].max(axis=1)
    df["_lowerW"]  = df[["open", "close"]].min(axis=1) - df["low"]
    df["_range"]   = df["high"] - df["low"]
    df["_bull"]    = df["close"] > df["open"]
    df["_bear"]    = df["close"] < df["open"]
    df["_ema20"]   = df["close"].ewm(span=20,  adjust=False).mean()
    df["_ema50"]   = df["close"].ewm(span=50,  adjust=False).mean()
    df["_ema200"]  = df["close"].ewm(span=200, adjust=False).mean()
    df["_bodyAvg14"]  = df["_body"].rolling(14).mean()
    df["_rangeAvg14"] = df["_range"].rolling(14).mean()
    return df


def _session_of_utc_hour(hour: int) -> str:
    if 8  <= hour < 13:  return "london"
    if 13 <= hour < 16:  return "london_ny_overlap"
    if 16 <= hour < 22:  return "ny"
    return "asia"


# ─── Pattern detectors — vectorised, tested against user's reference ────────
# Each returns 0/+1/-1 series. +1=bullish, -1=bearish, 0=no pattern.

def _hammer(df: pd.DataFrame) -> pd.Series:
    body = df["_body"]
    cond = (
        (df["_lowerW"] >= 2 * body) &
        (df["_upperW"] <= 0.3 * body) &
        (body > 0) &
        (df["close"] > df["_ema20"].shift(1))
    )
    downtrend = df["close"].shift(1) < df["_ema50"].shift(1)
    return pd.Series(np.where(cond & downtrend, 1, 0), index=df.index)


def _shooting_star(df: pd.DataFrame) -> pd.Series:
    body = df["_body"]
    cond = (
        (df["_upperW"] >= 2 * body) &
        (df["_lowerW"] <= 0.3 * body) &
        (body > 0)
    )
    uptrend = df["close"].shift(1) > df["_ema50"].shift(1)
    return pd.Series(np.where(cond & uptrend, -1, 0), index=df.index)


def _bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bear = df["_bear"].shift(1)
    curr_bull = df["_bull"]
    engulf    = (df["open"] <= df["close"].shift(1)) & (df["close"] >= df["open"].shift(1))
    bigger    = df["_body"] > df["_body"].shift(1)
    downtrend = df["close"].shift(2) < df["_ema20"].shift(2)
    cond = prev_bear & curr_bull & engulf & bigger & downtrend
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bull = df["_bull"].shift(1)
    curr_bear = df["_bear"]
    engulf    = (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))
    bigger    = df["_body"] > df["_body"].shift(1)
    uptrend   = df["close"].shift(2) > df["_ema20"].shift(2)
    cond = prev_bull & curr_bear & engulf & bigger & uptrend
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


def _piercing_line(df: pd.DataFrame) -> pd.Series:
    prev_bear = df["_bear"].shift(1)
    long_prev = df["_body"].shift(1) > df["_bodyAvg14"].shift(1)
    open_below = df["open"] < df["low"].shift(1)
    midpoint = (df["open"].shift(1) + df["close"].shift(1)) / 2
    above_mid  = df["close"] > midpoint
    below_open = df["close"] < df["open"].shift(1)
    cond = prev_bear & long_prev & open_below & above_mid & below_open
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    prev_bull = df["_bull"].shift(1)
    long_prev = df["_body"].shift(1) > df["_bodyAvg14"].shift(1)
    open_above = df["open"] > df["high"].shift(1)
    midpoint = (df["open"].shift(1) + df["close"].shift(1)) / 2
    below_mid  = df["close"] < midpoint
    above_open = df["close"] > df["open"].shift(1)
    cond = prev_bull & long_prev & open_above & below_mid & above_open
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


def _morning_star(df: pd.DataFrame) -> pd.Series:
    c1 = df["_bear"].shift(2) & (df["_body"].shift(2) > df["_bodyAvg14"].shift(2))
    c2 = df["_body"].shift(1) < 0.5 * df["_body"].shift(2)
    c3 = df["_bull"] & (df["_body"] > df["_bodyAvg14"])
    midpoint = (df["open"].shift(2) + df["close"].shift(2)) / 2
    c3_mid = df["close"] > midpoint
    cond = c1 & c2 & c3 & c3_mid
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _evening_star(df: pd.DataFrame) -> pd.Series:
    c1 = df["_bull"].shift(2) & (df["_body"].shift(2) > df["_bodyAvg14"].shift(2))
    c2 = df["_body"].shift(1) < 0.5 * df["_body"].shift(2)
    c3 = df["_bear"] & (df["_body"] > df["_bodyAvg14"])
    midpoint = (df["open"].shift(2) + df["close"].shift(2)) / 2
    c3_mid = df["close"] < midpoint
    cond = c1 & c2 & c3 & c3_mid
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


def _bullish_harami(df: pd.DataFrame) -> pd.Series:
    prev_long = df["_bear"].shift(1) & (df["_body"].shift(1) > df["_bodyAvg14"].shift(1))
    contained = (df["open"] > df["close"].shift(1)) & (df["close"] < df["open"].shift(1)) & df["_bull"]
    small     = df["_body"] < 0.5 * df["_body"].shift(1)
    cond = prev_long & contained & small
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _bearish_harami(df: pd.DataFrame) -> pd.Series:
    prev_long = df["_bull"].shift(1) & (df["_body"].shift(1) > df["_bodyAvg14"].shift(1))
    contained = (df["open"] < df["close"].shift(1)) & (df["close"] > df["open"].shift(1)) & df["_bear"]
    small     = df["_body"] < 0.5 * df["_body"].shift(1)
    cond = prev_long & contained & small
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


def _pin_bar_bullish(df: pd.DataFrame) -> pd.Series:
    cond = (
        (df["_lowerW"] >= 0.66 * df["_range"]) &
        (df["_body"] <= 0.33 * df["_range"]) &
        (df["close"] > (df["high"] + df["low"]) / 2) &
        (df["_range"] > 0)
    )
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _pin_bar_bearish(df: pd.DataFrame) -> pd.Series:
    cond = (
        (df["_upperW"] >= 0.66 * df["_range"]) &
        (df["_body"] <= 0.33 * df["_range"]) &
        (df["close"] < (df["high"] + df["low"]) / 2) &
        (df["_range"] > 0)
    )
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


def _inside_bar(df: pd.DataFrame) -> pd.Series:
    cond = (df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    bull3 = df["_bull"] & df["_bull"].shift(1) & df["_bull"].shift(2)
    long3 = (df["_body"] > df["_bodyAvg14"]) & (df["_body"].shift(1) > df["_bodyAvg14"].shift(1)) & \
            (df["_body"].shift(2) > df["_bodyAvg14"].shift(2))
    seq = (df["close"] > df["close"].shift(1)) & (df["close"].shift(1) > df["close"].shift(2))
    cond = bull3 & long3 & seq
    return pd.Series(np.where(cond.fillna(False), 1, 0), index=df.index)


def _three_black_crows(df: pd.DataFrame) -> pd.Series:
    bear3 = df["_bear"] & df["_bear"].shift(1) & df["_bear"].shift(2)
    long3 = (df["_body"] > df["_bodyAvg14"]) & (df["_body"].shift(1) > df["_bodyAvg14"].shift(1)) & \
            (df["_body"].shift(2) > df["_bodyAvg14"].shift(2))
    seq = (df["close"] < df["close"].shift(1)) & (df["close"].shift(1) < df["close"].shift(2))
    cond = bear3 & long3 & seq
    return pd.Series(np.where(cond.fillna(False), -1, 0), index=df.index)


PATTERN_DETECTORS = {
    "hammer":               _hammer,
    "shooting_star":        _shooting_star,
    "bullish_engulfing":    _bullish_engulfing,
    "bearish_engulfing":    _bearish_engulfing,
    "piercing_line":        _piercing_line,
    "dark_cloud_cover":     _dark_cloud_cover,
    "morning_star":         _morning_star,
    "evening_star":         _evening_star,
    "bullish_harami":       _bullish_harami,
    "bearish_harami":       _bearish_harami,
    "pin_bar_bullish":      _pin_bar_bullish,
    "pin_bar_bearish":      _pin_bar_bearish,
    "inside_bar":           _inside_bar,
    "three_white_soldiers": _three_white_soldiers,
    "three_black_crows":    _three_black_crows,
}


# ─── Helpers for confluence scoring ─────────────────────────────────────────

def _is_near_swing_level(df_with_ind: pd.DataFrame, lookback: int = 100,
                          tolerance_atr: float = 1.0) -> tuple[bool, str]:
    """Return (is_near, level_type) for the LAST bar.
    level_type: 'support' | 'resistance' | 'none'."""
    if len(df_with_ind) < lookback + 5:
        return False, "none"
    last_idx = len(df_with_ind) - 1
    cur_close = df_with_ind["close"].iloc[last_idx]
    atr_val = df_with_ind["_atr14"].iloc[last_idx]
    if not np.isfinite(atr_val) or atr_val <= 0:
        return False, "none"

    win = df_with_ind.iloc[max(0, last_idx - lookback): last_idx]
    # Simple swing: highest high / lowest low in trailing 20-bar windows
    swing_high = win["high"].rolling(21, center=True).max()
    swing_low  = win["low"].rolling(21, center=True).min()
    is_swing_h = (win["high"] == swing_high).fillna(False)
    is_swing_l = (win["low"]  == swing_low).fillna(False)

    for h in win["high"][is_swing_h].dropna():
        if abs(cur_close - h) <= tolerance_atr * atr_val:
            return True, "resistance"
    for low_v in win["low"][is_swing_l].dropna():
        if abs(cur_close - low_v) <= tolerance_atr * atr_val:
            return True, "support"
    return False, "none"


def _trend_label(df_with_ind: pd.DataFrame) -> str:
    last = df_with_ind.iloc[-1]
    if pd.notna(last.get("_ema200")):
        if last["close"] > last["_ema200"]: return "up"
        if last["close"] < last["_ema200"]: return "down"
    return "flat"


# ─── Public entry: detect_for_agent() ───────────────────────────────────────

@dataclass
class PatternHit:
    pattern_base: str       # e.g. "bullish_engulfing"
    direction: str          # "LONG" | "SHORT" | "NEUTRAL"
    timeframe: str          # "D1" | "M30" | "M15" | "M5"
    win_rate: float         # historical, [0, 1]
    avg_r: float            # historical expectancy in R units
    role: str               # production_role from spec
    score: float            # final blended score [-1, +1]
    reasoning: list[str]


def _direction_from_signal(sig_value: int, pattern_base: str) -> str:
    """Map signal int + pattern bias → direction."""
    BULL = {"hammer", "bullish_engulfing", "piercing_line", "morning_star",
            "three_white_soldiers", "bullish_harami", "pin_bar_bullish"}
    BEAR = {"shooting_star", "bearish_engulfing", "dark_cloud_cover",
            "evening_star", "three_black_crows", "bearish_harami",
            "pin_bar_bearish"}
    if pattern_base == "inside_bar":
        return "NEUTRAL"
    if pattern_base in BULL:
        return "LONG" if sig_value > 0 else "NEUTRAL"
    if pattern_base in BEAR:
        return "SHORT" if sig_value < 0 else "NEUTRAL"
    return "NEUTRAL"


def _stat_lookup(timeframe: str, pattern_base: str) -> Optional[dict]:
    """Find stat row for (timeframe, pattern_base). Tolerant of name variants."""
    rows = _STATS.get(timeframe, [])
    for r in rows:
        # D1 stats use "name" with no prefix; intraday has pattern_base column
        candidate = (r.get("pattern_base") or r.get("name") or "").lower().replace(" ", "_")
        if candidate == pattern_base:
            return r
    return None


def detect_for_agent(
    df: pd.DataFrame,
    timeframe: str = "M15",
    consider_neutral_inside_bar: bool = False,
) -> list[PatternHit]:
    """Detect patterns on the LAST bar of df. Returns weighted PatternHit list.

    Scoring formula (produces score in [-1, +1]):
        base = win_rate × sign(direction)         (e.g. WR 0.55 LONG = +0.55)
        × (1 + avg_r * 0.5)                       (boost positive expectancy)
        × conditional_multipliers (key_level, trend, session)
        × role_filter                             (avoid rows are zeroed)
    """
    if df is None or len(df) < 30:
        return []

    df_ind = _add_indicators(df.copy())
    last_idx = len(df_ind) - 1

    near_lvl, level_type = _is_near_swing_level(df_ind)
    trend = _trend_label(df_ind)

    # Session classification from last bar timestamp
    ts = df_ind.index[last_idx]
    if isinstance(ts, pd.Timestamp):
        sess = _session_of_utc_hour(ts.tz_convert("UTC").hour if ts.tzinfo else ts.hour)
    else:
        sess = "asia"

    hits: list[PatternHit] = []
    for name, detector in PATTERN_DETECTORS.items():
        try:
            sig = detector(df_ind)
        except Exception:
            continue
        sig_val = int(sig.iloc[last_idx])
        if sig_val == 0:
            continue

        direction = _direction_from_signal(sig_val, name)
        if direction == "NEUTRAL" and not consider_neutral_inside_bar:
            continue

        stat = _stat_lookup(timeframe, name)
        if stat is None:
            # No stats → treat as neutral score
            win_rate = 0.5
            avg_r    = 0.0
            role     = "filter_or_confirmation"
        else:
            win_rate = float(stat.get("win_rate") or stat.get("win_rate_historical") or 0.5)
            avg_r    = float(stat.get("expectancy_R") or stat.get("avg_R") or 0.0)
            role     = stat.get("production_role", "filter_or_confirmation")

        # Skip patterns flagged as avoid
        if role in PRODUCTION_ROLES_AVOID:
            continue

        # Base score
        sign = +1 if direction == "LONG" else (-1 if direction == "SHORT" else 0)
        score = win_rate * sign
        score *= (1.0 + max(avg_r, 0) * 0.5)  # only positive expectancy boosts

        reasoning = [f"{name}@{timeframe} WR={win_rate*100:.0f}% R={avg_r:+.2f} role={role}"]

        # Conditional multipliers per spec_v2
        if near_lvl:
            if (direction == "LONG" and level_type == "support") or \
               (direction == "SHORT" and level_type == "resistance"):
                score *= 1.5
                reasoning.append(f"AT KEY {level_type.upper()} (1.5x)")
        if (direction == "LONG" and trend == "up") or \
           (direction == "SHORT" and trend == "down"):
            score *= 1.2
            reasoning.append(f"trend-aligned ({trend})")
        elif (direction == "LONG" and trend == "down") or \
             (direction == "SHORT" and trend == "up"):
            score *= 0.5
            reasoning.append(f"counter-trend ({trend}) [0.5x]")
        if sess == "asia":
            score *= 0.3
            reasoning.append("Asia session (0.3x)")

        # Clamp
        score = max(-1.0, min(1.0, score))

        hits.append(PatternHit(
            pattern_base=name,
            direction=direction,
            timeframe=timeframe,
            win_rate=win_rate,
            avg_r=avg_r,
            role=role,
            score=score,
            reasoning=reasoning,
        ))

    return hits


def aggregate_pattern_score(hits: list[PatternHit]) -> tuple[float, str, list[str]]:
    """Combine multiple pattern hits into a single (-1..+1) score + direction.
    Returns (score, direction, reasons)."""
    if not hits:
        return 0.0, "NEUTRAL", ["no patterns detected"]

    long_score  = sum(h.score for h in hits if h.score > 0)
    short_score = sum(abs(h.score) for h in hits if h.score < 0)
    net = long_score - short_score
    norm = max(long_score + short_score, 1.0)
    final_score = net / norm  # in [-1, +1]

    if final_score > 0.15:
        direction = "LONG"
    elif final_score < -0.15:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    reasons = [f"{len(hits)} patterns: " + ", ".join(h.pattern_base for h in hits[:3])]
    if hits:
        top = max(hits, key=lambda h: abs(h.score))
        reasons.append(f"top: {top.pattern_base} score={top.score:+.2f} {top.direction}")
    return final_score, direction, reasons


# Optional smoke test
if __name__ == "__main__":
    rng = pd.date_range("2026-01-01", periods=300, freq="15min", tz="UTC")
    np.random.seed(42)
    closes = 4500 + np.cumsum(np.random.randn(300) * 5)
    df = pd.DataFrame({
        "open":  closes + np.random.randn(300),
        "high":  closes + abs(np.random.randn(300) * 3),
        "low":   closes - abs(np.random.randn(300) * 3),
        "close": closes,
        "volume": np.random.randint(100, 1000, 300),
    }, index=rng)
    hits = detect_for_agent(df, timeframe="M15")
    print(f"Detected {len(hits)} patterns on last bar:")
    for h in hits:
        print(f"  {h.pattern_base:20s} {h.direction:7s} score={h.score:+.3f} role={h.role}")
    score, direction, reasons = aggregate_pattern_score(hits)
    print(f"\nAggregate: {direction} score={score:+.3f}")
    for r in reasons: print(f"  - {r}")
