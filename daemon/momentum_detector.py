"""Event-driven momentum trigger (Opsi B).

Background watcher that polls real-time XAU price + lightweight M5 features,
and decides whether market conditions warrant an immediate full-pipeline
re-evaluation (instead of waiting for the next 5-min scheduled cycle).

Trigger conditions for XAU/USD:
    1. Price spike: >0.3% move within 1 min (~$13 at $4500 spot)
    2. ATR explosion: last M5 bar range > 1.5x ATR(14)
    3. EMA stack flip: EMA9 cross EMA21 on M5
    4. Volume spike: last bar volume > 3x rolling avg (where volume available)
    5. News blackout exit: just exited a high-impact event window

State (kept in MomentumWatcher instance, not persisted across daemon restart):
- last_price          : float (price seen on previous poll)
- last_full_eval_at   : float (epoch seconds of last full-pipeline run)
- last_trigger_at     : float (epoch seconds of last trigger fire — for debounce)
- last_in_blackout    : bool  (to detect transition out of blackout)
- ema9_above_21_prev  : bool | None (for cross detection)

Cost guard:
- Min interval between triggers (debounce) = 60s. Prevents 5x fires/minute on volatile day.
- Trigger ALWAYS pushes the 5-min schedule timer forward — so we don't double-eval.
- Fallback to quiet polling if Twelve Data quota exhausted (yfinance close as proxy).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd


# ─── Config ────────────────────────────────────────────────────────────────────

# Minimum seconds between trigger fires (avoid spam on hectic news days)
TRIGGER_DEBOUNCE_S = 60

# % move within 1 poll cycle to qualify as price spike
PRICE_SPIKE_PCT = 0.003   # 0.3% — about $13 at $4500 gold

# ATR explosion: last bar range / ATR(14)
ATR_EXPLOSION_RATIO = 1.5

# Volume spike: last bar / rolling 20-bar avg
VOLUME_SPIKE_RATIO = 3.0


@dataclass
class TriggerEvent:
    """A momentum trigger fired."""
    reason: str           # short tag e.g. 'price_spike', 'ema_cross', 'blackout_exit'
    detail: str           # human-readable detail
    fired_at: float       # epoch seconds
    price_now: float
    price_prev: Optional[float]


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _detect_price_spike(price_now: float, price_prev: Optional[float]) -> Optional[str]:
    """Return reason str if price moved > PRICE_SPIKE_PCT vs prev poll; else None."""
    if price_prev is None or price_prev <= 0:
        return None
    pct = abs(price_now - price_prev) / price_prev
    if pct >= PRICE_SPIKE_PCT:
        direction = "up" if price_now > price_prev else "down"
        return f"price_spike_{direction}_{pct*100:.2f}pct"
    return None


def _detect_atr_explosion(df_5m: pd.DataFrame) -> Optional[str]:
    """Last M5 bar range > 1.5x ATR(14)."""
    if df_5m is None or len(df_5m) < 20 or "atr14" not in df_5m.columns:
        return None
    last = df_5m.iloc[-1]
    bar_range = float(last["high"]) - float(last["low"])
    atr = float(last["atr14"]) if pd.notna(last["atr14"]) else None
    if atr is None or atr <= 0:
        return None
    ratio = bar_range / atr
    if ratio >= ATR_EXPLOSION_RATIO:
        return f"atr_explosion_{ratio:.2f}x"
    return None


def _detect_ema_cross(df_5m: pd.DataFrame, ema9_above_21_prev: Optional[bool]) -> tuple[Optional[str], Optional[bool]]:
    """Detect EMA9 crossing EMA21 on M5. Returns (reason_or_none, current_state)."""
    if df_5m is None or len(df_5m) < 30:
        return None, ema9_above_21_prev
    last = df_5m.iloc[-1]
    e9 = last.get("ema9")
    e21 = last.get("ema21")
    if e9 is None or e21 is None or pd.isna(e9) or pd.isna(e21):
        return None, ema9_above_21_prev
    e9_above = bool(e9 > e21)
    if ema9_above_21_prev is None:
        return None, e9_above   # first observation, no cross yet
    if e9_above != ema9_above_21_prev:
        direction = "bullish_cross" if e9_above else "bearish_cross"
        return f"ema9_21_{direction}", e9_above
    return None, e9_above


def _detect_volume_spike(df_5m: pd.DataFrame) -> Optional[str]:
    """Last bar volume > 3x rolling 20-bar avg. Skip if no volume data."""
    if df_5m is None or len(df_5m) < 25 or "volume" not in df_5m.columns:
        return None
    last_v = float(df_5m["volume"].iloc[-1])
    avg_v = float(df_5m["volume"].tail(20).mean())
    if avg_v <= 0 or last_v <= 0:
        return None
    ratio = last_v / avg_v
    if ratio >= VOLUME_SPIKE_RATIO:
        return f"volume_spike_{ratio:.1f}x"
    return None


def _detect_blackout_exit(in_blackout_now: bool, last_in_blackout: Optional[bool]) -> Optional[str]:
    """Detect transition: was in blackout last poll, now clear → fire trigger."""
    if last_in_blackout is True and in_blackout_now is False:
        return "blackout_exit"
    return None


# ─── Watcher class (stateful, used inside daemon thread) ───────────────────────

class MomentumWatcher:
    """Stateful watcher. Call evaluate(...) on each poll cycle.

    Returns TriggerEvent or None. Caller is responsible for actually running
    the full re-eval pipeline when a trigger fires.

    Debouncing built-in: even if multiple conditions fire, only one trigger
    per TRIGGER_DEBOUNCE_S window.
    """

    def __init__(self, log: Callable[[str], None] = print):
        self.log = log
        self.last_price: Optional[float] = None
        self.last_full_eval_at: float = 0.0
        self.last_trigger_at: float = 0.0
        self.last_in_blackout: Optional[bool] = None
        self.ema9_above_21_prev: Optional[bool] = None
        self.poll_count: int = 0

    def mark_full_eval(self, t: Optional[float] = None) -> None:
        """Caller invokes this after successfully running the full pipeline.
        Resets the schedule timer so triggers + scheduled don't double-fire."""
        self.last_full_eval_at = t if t is not None else time.time()

    def evaluate(
        self,
        price_now: float,
        df_5m: Optional[pd.DataFrame],
        in_blackout_now: bool,
    ) -> Optional[TriggerEvent]:
        """Run all detectors. Return the FIRST matching trigger, or None.

        Order matters: price_spike checked first (cheapest, most actionable),
        then ATR/EMA (require df_5m), then volume, then blackout_exit.
        """
        self.poll_count += 1
        now = time.time()

        # Update EMA cross state regardless of debounce (so we don't miss next cross)
        ema_reason, ema9_above = _detect_ema_cross(df_5m, self.ema9_above_21_prev)
        self.ema9_above_21_prev = ema9_above

        # Debounce: skip detection if we fired recently
        if now - self.last_trigger_at < TRIGGER_DEBOUNCE_S:
            self.last_price = price_now
            self.last_in_blackout = in_blackout_now
            return None

        triggers: list[tuple[str, str]] = []  # [(reason_tag, detail)]

        # 1. Price spike (cheapest check)
        spike = _detect_price_spike(price_now, self.last_price)
        if spike:
            triggers.append((spike, f"price {self.last_price:.2f} -> {price_now:.2f}"))

        # 2. ATR explosion
        atr_exp = _detect_atr_explosion(df_5m) if df_5m is not None else None
        if atr_exp:
            triggers.append((atr_exp, "M5 bar range >> ATR(14)"))

        # 3. EMA cross
        if ema_reason:
            triggers.append((ema_reason, "EMA9 crossed EMA21 on M5"))

        # 4. Volume spike
        vol_spike = _detect_volume_spike(df_5m) if df_5m is not None else None
        if vol_spike:
            triggers.append((vol_spike, "M5 volume >> 20-bar avg"))

        # 5. Blackout exit (least frequent, most important post-event)
        bl_exit = _detect_blackout_exit(in_blackout_now, self.last_in_blackout)
        if bl_exit:
            triggers.append((bl_exit, "high-impact news event window cleared"))

        # Update state for next poll
        prev_price = self.last_price
        self.last_price = price_now
        self.last_in_blackout = in_blackout_now

        if not triggers:
            return None

        # Take the highest-priority trigger
        # Order in `triggers` list reflects priority above
        reason, detail = triggers[0]
        evt = TriggerEvent(
            reason=reason,
            detail=detail,
            fired_at=now,
            price_now=price_now,
            price_prev=prev_price,
        )
        self.last_trigger_at = now
        self.log(
            f"[momentum] TRIGGER reason={evt.reason} detail='{evt.detail}' "
            f"price={evt.price_now:.2f} (poll #{self.poll_count})"
        )
        return evt
