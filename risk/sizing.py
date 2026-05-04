"""Lot/leverage/position sizing untuk XAU/USD.

XAU/USD spec (standard):
- 1 lot (standard) = 100 oz
- Pip = 0.01 (1 cent)
- Pip value (standard lot) = $1
- Mini lot (0.1) = 10 oz, pip value $0.10
- Micro lot (0.01) = 1 oz, pip value $0.01

Contract size on broker dapat berbeda — gua expose param-nya.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from config.settings import RISK_PROFILES


@dataclass
class PositionPlan:
    lot_size: float                  # in lots
    units_oz: float                  # in ounces
    risk_amount_usd: float           # USD lo akan rugi kalau SL kena
    risk_pct: float                  # % of equity
    sl_distance_dollars: float       # dollar distance entry → SL
    notional_value_usd: float        # nilai posisi
    leverage_used: float             # actual leverage
    margin_required_usd: float       # initial margin (estimate)
    pip_value_usd: float             # USD per pip move
    expected_payoff_usd: dict        # {'tp1': $, 'tp2': $, 'tp3': $}
    profile: str
    warnings: list[str]


def compute_position(
    equity_usd: float,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    tp3: float,
    side: Literal["LONG", "SHORT"],
    profile: str = "moderat",
    broker_max_leverage: float = 100.0,
    contract_size_oz: float = 100.0,
    custom_risk_pct: float | None = None,
) -> PositionPlan:
    """Calculate lot size given equity & risk profile.
    Risk-based sizing: posisi diukur supaya kalo SL kena, kerugian = risk_pct × equity."""
    warnings: list[str] = []

    if profile not in RISK_PROFILES:
        warnings.append(f"unknown profile {profile} → fallback moderat")
        profile = "moderat"
    cfg = RISK_PROFILES[profile]
    risk_pct = float(custom_risk_pct) if custom_risk_pct is not None else cfg["risk_per_trade"]

    if equity_usd <= 0:
        warnings.append("equity must be > 0")
        return _empty_plan(profile, warnings)

    if entry <= 0 or sl <= 0:
        warnings.append("invalid entry/sl")
        return _empty_plan(profile, warnings)

    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        warnings.append("entry == sl → cannot size")
        return _empty_plan(profile, warnings)

    # Risk amount
    risk_amount = equity_usd * risk_pct

    # Units of gold (oz) we can hold:
    # P&L per oz = sl_dist (USD per oz).
    # units_oz = risk_amount / sl_dist
    units_oz = risk_amount / sl_dist

    # Convert to lots (broker's contract size)
    lot_size = units_oz / contract_size_oz

    # Round to micro lot precision
    lot_size = round(lot_size, 2)
    units_oz = lot_size * contract_size_oz

    notional = units_oz * entry
    leverage = notional / equity_usd if equity_usd else 0.0

    if leverage > broker_max_leverage:
        warnings.append(f"required leverage {leverage:.1f}x > broker max {broker_max_leverage}x — reduce risk or increase capital")
        # Cap to broker max
        lot_size_cap = (equity_usd * broker_max_leverage) / (entry * contract_size_oz)
        lot_size = round(lot_size_cap, 2)
        units_oz = lot_size * contract_size_oz
        notional = units_oz * entry
        leverage = notional / equity_usd

    margin = notional / max(broker_max_leverage, 1.0)
    pip_value = units_oz * 0.01  # 0.01 USD price move × units = $/pip

    payoff = {
        "tp1": units_oz * abs(tp1 - entry) * (1 if side == "LONG" else 1),
        "tp2": units_oz * abs(tp2 - entry),
        "tp3": units_oz * abs(tp3 - entry),
    }

    if risk_pct > 0.05:
        warnings.append(f"risk {risk_pct*100:.1f}% per trade VERY HIGH — only sustainable with edge >70%")

    return PositionPlan(
        lot_size=lot_size,
        units_oz=units_oz,
        risk_amount_usd=round(risk_amount, 2),
        risk_pct=round(risk_pct, 4),
        sl_distance_dollars=round(sl_dist, 2),
        notional_value_usd=round(notional, 2),
        leverage_used=round(leverage, 2),
        margin_required_usd=round(margin, 2),
        pip_value_usd=round(pip_value, 4),
        expected_payoff_usd={k: round(v, 2) for k, v in payoff.items()},
        profile=profile,
        warnings=warnings,
    )


def kelly_fractional(win_rate: float, avg_win_r: float, fraction: float = 0.25) -> float:
    """Kelly criterion (fractional). Returns suggested risk_pct.
    f* = W - (1-W)/R, where W = win rate, R = avg win / avg loss in R-multiples.
    Use 0.25× Kelly for safety (full Kelly maximizes growth but volatile)."""
    if avg_win_r <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / avg_win_r
    return max(0.0, f * fraction)


def _empty_plan(profile: str, warnings: list[str]) -> PositionPlan:
    return PositionPlan(
        lot_size=0, units_oz=0, risk_amount_usd=0, risk_pct=0,
        sl_distance_dollars=0, notional_value_usd=0,
        leverage_used=0, margin_required_usd=0, pip_value_usd=0,
        expected_payoff_usd={"tp1": 0, "tp2": 0, "tp3": 0},
        profile=profile, warnings=warnings,
    )
