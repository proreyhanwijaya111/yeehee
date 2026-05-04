"""Monte Carlo bootstrap on trade R-multiples.
Why: backtest hasilnya 1 path. MC bootstrap simulasiin 100k path alternatif untuk lihat
distribusi outcome — bukan cuma cherry-picked single run.

Standard institutional method: sample with replacement dari trade R-results,
hitung equity curve untuk tiap path, agregasi stats."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np

from config.settings import BACKTEST
from backtest.engine import BacktestResult


@dataclass
class MCResult:
    n_runs: int
    starting_equity: float
    final_equity_p5: float
    final_equity_p25: float
    final_equity_p50: float
    final_equity_p75: float
    final_equity_p95: float
    max_dd_p5: float          # 5th percentile of max DD (worst case)
    max_dd_p50: float
    max_dd_p95: float
    prob_profit: float
    prob_blowup: float        # prob of >50% drawdown
    prob_50pct_dd: float
    prob_30pct_dd: float
    expected_return_pct: float

    def to_dict(self) -> dict:
        return self.__dict__


def run_monte_carlo(
    bt: BacktestResult,
    n_runs: int = BACKTEST.monte_carlo_runs,
    risk_per_trade: float = 0.01,
    blowup_dd_pct: float = 0.50,
    seed: int | None = 42,
) -> MCResult:
    """Bootstrap resample trade R-multiples and simulate equity curves."""
    if not bt.trades:
        return MCResult(0, bt.starting_equity, *([bt.starting_equity] * 5), 0, 0, 0, 1.0, 0.0, 0.0, 0.0, 0.0)

    rs = np.array([t.pnl_r for t in bt.trades])
    n_trades = len(rs)

    rng = np.random.default_rng(seed)
    # Shape: (n_runs, n_trades)
    samples = rng.choice(rs, size=(n_runs, n_trades), replace=True)

    # Equity curve per run, vectorized
    starting = bt.starting_equity
    # equity[t+1] = equity[t] + equity[t] * risk_pct * R_t = equity[t] * (1 + risk*R)
    # cum product -> compounding
    growth = 1.0 + risk_per_trade * samples
    # Ensure no negative equity (clip at 0)
    cum = np.cumprod(growth, axis=1) * starting
    final = cum[:, -1]

    # Per-run max DD
    peak = np.maximum.accumulate(cum, axis=1)
    dd = (cum - peak) / peak
    max_dd = dd.min(axis=1)  # most negative

    return MCResult(
        n_runs=n_runs,
        starting_equity=starting,
        final_equity_p5=float(np.percentile(final, 5)),
        final_equity_p25=float(np.percentile(final, 25)),
        final_equity_p50=float(np.percentile(final, 50)),
        final_equity_p75=float(np.percentile(final, 75)),
        final_equity_p95=float(np.percentile(final, 95)),
        max_dd_p5=float(np.percentile(max_dd, 5) * 100),
        max_dd_p50=float(np.percentile(max_dd, 50) * 100),
        max_dd_p95=float(np.percentile(max_dd, 95) * 100),
        prob_profit=float(np.mean(final > starting)),
        prob_blowup=float(np.mean(max_dd <= -blowup_dd_pct)),
        prob_50pct_dd=float(np.mean(max_dd <= -0.50)),
        prob_30pct_dd=float(np.mean(max_dd <= -0.30)),
        expected_return_pct=float((np.mean(final) / starting - 1) * 100),
    )


def walk_forward_split(
    df,
    n_splits: int = BACKTEST.walk_forward_splits,
    oos_pct: float = BACKTEST.out_of_sample_pct,
):
    """Returns list of (train_df, test_df) tuples. Anchored walk-forward."""
    n = len(df)
    test_size = int(n * oos_pct / n_splits)
    train_size = n - n_splits * test_size
    splits = []
    for i in range(n_splits):
        train_end = train_size + i * test_size
        test_end = train_end + test_size
        if test_end > n:
            break
        splits.append((df.iloc[:train_end], df.iloc[train_end:test_end]))
    return splits
