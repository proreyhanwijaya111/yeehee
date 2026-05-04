"""Vectorized-ish bar-by-bar backtest. Simple but realistic:
- Spread + slippage applied on entry/exit
- ATR-based SL/TP
- One position at a time
- Tracks equity curve, trade log
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np
import pandas as pd

from config.settings import BACKTEST


@dataclass
class Trade:
    side: str
    entry_idx: int
    entry_time: object
    entry_price: float
    sl: float
    tp: float
    exit_idx: int = 0
    exit_time: object = None
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_r: float = 0.0      # in R-multiples
    pnl_dollars: float = 0.0


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    starting_equity: float = 10000.0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl_r > 0]

    @property
    def losses(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl_r <= 0]

    @property
    def win_rate(self) -> float:
        return len(self.wins) / self.n_trades if self.n_trades else 0.0

    @property
    def avg_win_r(self) -> float:
        return float(np.mean([t.pnl_r for t in self.wins])) if self.wins else 0.0

    @property
    def avg_loss_r(self) -> float:
        return float(np.mean([t.pnl_r for t in self.losses])) if self.losses else 0.0

    @property
    def expectancy_r(self) -> float:
        return self.win_rate * self.avg_win_r + (1 - self.win_rate) * self.avg_loss_r

    @property
    def total_return_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        return (self.equity_curve[-1] / self.starting_equity - 1) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        eq = np.array(self.equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        return float(dd.min() * 100)

    @property
    def sharpe(self) -> float:
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0.0
        rets = np.diff(self.equity_curve) / self.equity_curve[:-1]
        if rets.std() == 0:
            return 0.0
        return float(rets.mean() / rets.std() * np.sqrt(252))

    def stats(self) -> dict:
        return {
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_win_r": round(self.avg_win_r, 3),
            "avg_loss_r": round(self.avg_loss_r, 3),
            "expectancy_r": round(self.expectancy_r, 3),
            "total_return_pct": round(self.total_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe": round(self.sharpe, 2),
            "starting_equity": self.starting_equity,
            "ending_equity": round(self.equity_curve[-1] if self.equity_curve else 0, 2),
        }


def _apply_costs(price: float, side: str, exit: bool = False) -> float:
    """Apply spread + slippage. Spread = 2 pips, slippage = 0.5 pip. Pip = 0.01 for XAU."""
    pip = 0.01
    cost = (BACKTEST.spread_pips + BACKTEST.slippage_pips) * pip
    if side == "LONG":
        return price + cost if not exit else price - cost
    return price - cost if not exit else price + cost


def run_backtest(
    df: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, int], dict],
    starting_equity: float = 10000.0,
    risk_per_trade: float = 0.01,
    contract_oz: float = 100.0,
) -> BacktestResult:
    """signal_fn(df, idx) → {'side': 'LONG'|'SHORT'|'FLAT', 'sl': float, 'tp': float}
    Walk bar-by-bar. Open at next bar after signal. Exit on SL or TP hit (using high/low)."""

    result = BacktestResult(starting_equity=starting_equity)
    equity = starting_equity
    result.equity_curve.append(equity)

    in_pos: Optional[Trade] = None

    for i in range(len(df) - 1):
        bar = df.iloc[i]
        nxt = df.iloc[i + 1]

        # Manage open position first
        if in_pos is not None:
            hit_sl = (in_pos.side == "LONG" and bar["low"] <= in_pos.sl) or \
                     (in_pos.side == "SHORT" and bar["high"] >= in_pos.sl)
            hit_tp = (in_pos.side == "LONG" and bar["high"] >= in_pos.tp) or \
                     (in_pos.side == "SHORT" and bar["low"] <= in_pos.tp)

            if hit_sl and hit_tp:
                # Conservative: assume SL hit first
                in_pos.exit_price = _apply_costs(in_pos.sl, in_pos.side, exit=True)
                in_pos.exit_reason = "SL (both touched, conservative)"
            elif hit_sl:
                in_pos.exit_price = _apply_costs(in_pos.sl, in_pos.side, exit=True)
                in_pos.exit_reason = "SL"
            elif hit_tp:
                in_pos.exit_price = _apply_costs(in_pos.tp, in_pos.side, exit=True)
                in_pos.exit_reason = "TP"
            else:
                continue

            in_pos.exit_idx = i
            in_pos.exit_time = df.index[i]
            risk_dist = abs(in_pos.entry_price - in_pos.sl)
            move = (in_pos.exit_price - in_pos.entry_price) if in_pos.side == "LONG" else (in_pos.entry_price - in_pos.exit_price)
            in_pos.pnl_r = move / risk_dist if risk_dist else 0.0
            risk_dollars = equity * risk_per_trade
            in_pos.pnl_dollars = in_pos.pnl_r * risk_dollars
            equity += in_pos.pnl_dollars
            result.trades.append(in_pos)
            result.equity_curve.append(equity)
            in_pos = None

        # New signal?
        if in_pos is None:
            sig = signal_fn(df, i)
            side = sig.get("side", "FLAT")
            if side in ("LONG", "SHORT"):
                entry_px = _apply_costs(float(nxt["open"]), side)
                sl = float(sig["sl"])
                tp = float(sig["tp"])
                if side == "LONG" and not (sl < entry_px < tp):
                    continue
                if side == "SHORT" and not (tp < entry_px < sl):
                    continue
                in_pos = Trade(
                    side=side,
                    entry_idx=i + 1,
                    entry_time=df.index[i + 1],
                    entry_price=entry_px,
                    sl=sl,
                    tp=tp,
                )

    return result


# === Simple "default" signal function for E2E testing ===
def default_swing_signal(df: pd.DataFrame, i: int) -> dict:
    """Use for sanity backtest: EMA21/50 cross + ADX>20."""
    if i < 50:
        return {"side": "FLAT"}
    bar = df.iloc[i]
    prev = df.iloc[i - 1]
    e21, e50 = bar.get("ema21"), bar.get("ema50")
    pe21, pe50 = prev.get("ema21"), prev.get("ema50")
    adx_v = bar.get("adx", 0)
    atr_v = bar.get("atr14", 0)
    close = bar["close"]
    if any(pd.isna(x) for x in [e21, e50, pe21, pe50, atr_v]) or atr_v == 0:
        return {"side": "FLAT"}
    if adx_v < 20:
        return {"side": "FLAT"}
    if e21 > e50 and pe21 <= pe50:
        return {"side": "LONG", "sl": close - 2 * atr_v, "tp": close + 4 * atr_v}
    if e21 < e50 and pe21 >= pe50:
        return {"side": "SHORT", "sl": close + 2 * atr_v, "tp": close - 4 * atr_v}
    return {"side": "FLAT"}
