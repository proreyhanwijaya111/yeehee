"""Trading session context. XAU punya behavior session-specific yg konsisten:
- Asia (00-08 UTC): range-bound, low vol. Strategi mean-revert.
- London open (07-08 UTC): volatility spike, trend day setup.
- London-NY overlap (12-16 UTC): highest volatility, best for momentum.
- Post-NY (21+): drift, low vol.
"""
from __future__ import annotations
from datetime import datetime, time, timezone
from typing import Optional
import pandas as pd

from config.settings import SESSIONS_UTC, LONDON_FIX_AM, LONDON_FIX_PM


def session_at(dt: datetime) -> str:
    h = dt.astimezone(timezone.utc).hour
    if SESSIONS_UTC["overlap_lon_ny"][0] <= h < SESSIONS_UTC["overlap_lon_ny"][1]:
        return "lon_ny_overlap"
    if SESSIONS_UTC["asia"][0] <= h < SESSIONS_UTC["asia"][1]:
        return "asia"
    if SESSIONS_UTC["london"][0] <= h < SESSIONS_UTC["london"][1]:
        return "london"
    if SESSIONS_UTC["ny"][0] <= h < SESSIONS_UTC["ny"][1]:
        return "ny"
    return "off_hours"


def is_near_london_fix(dt: datetime, window_min: int = 15) -> tuple[bool, Optional[str]]:
    utc = dt.astimezone(timezone.utc)
    for label, t_str in [("AM_fix", LONDON_FIX_AM), ("PM_fix", LONDON_FIX_PM)]:
        hh, mm = map(int, t_str.split(":"))
        fix = utc.replace(hour=hh, minute=mm, second=0, microsecond=0)
        diff = abs((utc - fix).total_seconds()) / 60
        if diff <= window_min:
            return True, label
    return False, None


def annotate_session(df: pd.DataFrame) -> pd.DataFrame:
    """Add session column + session-specific stats."""
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    elif out.index.tz is None:
        out.index = out.index.tz_localize("UTC")

    hours = out.index.hour
    sessions = []
    for h in hours:
        if SESSIONS_UTC["overlap_lon_ny"][0] <= h < SESSIONS_UTC["overlap_lon_ny"][1]:
            sessions.append("lon_ny_overlap")
        elif SESSIONS_UTC["asia"][0] <= h < SESSIONS_UTC["asia"][1]:
            sessions.append("asia")
        elif SESSIONS_UTC["london"][0] <= h < SESSIONS_UTC["london"][1]:
            sessions.append("london")
        elif SESSIONS_UTC["ny"][0] <= h < SESSIONS_UTC["ny"][1]:
            sessions.append("ny")
        else:
            sessions.append("off_hours")
    out["session"] = sessions
    return out


def session_bias(df: pd.DataFrame, session: str = "asia") -> dict:
    """For Asia session: detect Asia range high/low — used as London breakout levels."""
    df = annotate_session(df)
    today = df.index[-1].normalize()
    today_df = df[df.index >= today]
    asia = today_df[today_df["session"] == "asia"]
    if asia.empty:
        return {"session": session, "available": False}
    return {
        "session": session,
        "available": True,
        "high": float(asia["high"].max()),
        "low": float(asia["low"].min()),
        "range": float(asia["high"].max() - asia["low"].min()),
    }
