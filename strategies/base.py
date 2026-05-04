"""Common types & base class for strategies."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class Style(str, Enum):
    SCALPER = "scalper"
    INTRADAY = "intraday"
    SWING = "swing"


@dataclass
class Signal:
    style: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    confidence: float           # 0..1
    confluence_count: int       # how many factors agreed
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    regime: str = ""
    session: str = ""
    timestamp: str = ""
    rr_to_tp1: float = 0.0
    rr_to_tp2: float = 0.0

    def is_actionable(self) -> bool:
        return self.side in (Side.LONG.value, Side.SHORT.value) and self.confidence > 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyContext:
    """All inputs a strategy might use."""
    df_primary: object              # pd.DataFrame timeframe utama (with technical+smc indicators)
    df_htf: object = None           # higher timeframe untuk filter
    intermarket: dict = field(default_factory=dict)
    cot: dict = field(default_factory=dict)
    in_news_blackout: bool = False
    news_event: Optional[object] = None
    session: str = ""
    regime: str = ""


def calc_rr(entry: float, sl: float, tp: float, side: str) -> float:
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    if side == Side.LONG.value:
        return (tp - entry) / risk
    return (entry - tp) / risk
