"""Smoke test: validates modules can import + basic functions work.
Run AFTER `pip install -r requirements.txt`:
    python smoke_test.py
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = 0
FAIL = 0


def check(label: str, fn):
    global PASS, FAIL
    try:
        result = fn()
        print(f"  [OK]  {label}: {result}")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {label}: {e.__class__.__name__}: {e}")
        traceback.print_exc()
        FAIL += 1


def main():
    print("=" * 60)
    print("yeehee smoke test")
    print("=" * 60)

    print("\n[1] Imports")
    check("config.settings", lambda: __import__("config.settings", fromlist=["TICKERS"]).TICKERS["xau"])
    check("data.price_fetcher", lambda: __import__("data.price_fetcher", fromlist=["fetch_xau"]).fetch_xau.__name__)
    check("data.calendar_fetcher", lambda: __import__("data.calendar_fetcher", fromlist=["fetch_calendar"]).fetch_calendar.__name__)
    check("data.cot_fetcher", lambda: __import__("data.cot_fetcher", fromlist=["fetch_cot_gold"]).fetch_cot_gold.__name__)
    check("features.technical", lambda: __import__("features.technical", fromlist=["add_all"]).add_all.__name__)
    check("features.smc", lambda: __import__("features.smc", fromlist=["add_all_smc"]).add_all_smc.__name__)
    check("features.regime", lambda: __import__("features.regime", fromlist=["detect_regime"]).detect_regime.__name__)
    check("features.session", lambda: __import__("features.session", fromlist=["session_at"]).session_at.__name__)
    check("features.intermarket", lambda: __import__("features.intermarket", fromlist=["intermarket_score"]).intermarket_score.__name__)
    check("strategies.scalper", lambda: __import__("strategies.scalper", fromlist=["generate"]).generate.__name__)
    check("strategies.intraday", lambda: __import__("strategies.intraday", fromlist=["generate"]).generate.__name__)
    check("strategies.swing", lambda: __import__("strategies.swing", fromlist=["generate"]).generate.__name__)
    check("ai_agent.rule_engine", lambda: __import__("ai_agent.rule_engine", fromlist=["debate"]).debate.__name__)
    check("ai_agent.pm_agent", lambda: __import__("ai_agent.pm_agent", fromlist=["claude_available"]).claude_available())
    check("risk.sizing", lambda: __import__("risk.sizing", fromlist=["compute_position"]).compute_position.__name__)
    check("backtest.engine", lambda: __import__("backtest.engine", fromlist=["run_backtest"]).run_backtest.__name__)
    check("backtest.monte_carlo", lambda: __import__("backtest.monte_carlo", fromlist=["run_monte_carlo"]).run_monte_carlo.__name__)
    check("signal_engine", lambda: __import__("signal_engine", fromlist=["generate_signals"]).generate_signals.__name__)

    print("\n[2] Data layer (network)")
    from data.price_fetcher import fetch_xau
    df = None
    def _fetch():
        nonlocal df
        df = fetch_xau("1h", period="60d")
        return f"{len(df)} bars, last close {df['close'].iloc[-1]:.2f}"
    check("fetch_xau 1h 60d", _fetch)

    print("\n[3] Feature engine")
    if df is not None and len(df) > 50:
        from features.technical import add_all
        from features.smc import add_all_smc
        from features.regime import detect_regime
        df_full = add_all(df)
        check("add_all (technicals)", lambda: f"cols added: rsi14={pd.notna(df_full['rsi14'].iloc[-1])}, adx={pd.notna(df_full['adx'].iloc[-1])}")
        df_full = add_all_smc(df_full)
        check("add_all_smc", lambda: f"FVG bull last 50: {int(df_full['fvg_bull'].tail(50).sum())}")
        df_full = detect_regime(df_full)
        check("detect_regime", lambda: f"current regime: {df_full['regime'].iloc[-1]}")

    print("\n[4] Risk sizing")
    from risk.sizing import compute_position
    plan = compute_position(equity_usd=10000, entry=2000, sl=1990, tp1=2010, tp2=2020, tp3=2035, side="LONG", profile="moderat")
    check("compute_position moderat", lambda: f"lot={plan.lot_size}, risk=${plan.risk_amount_usd}")

    print("\n[5] Backtest mini")
    if df is not None:
        from features.technical import add_all
        df_bt = add_all(df.tail(500))
        from backtest.engine import run_backtest, default_swing_signal
        bt = run_backtest(df_bt, default_swing_signal, starting_equity=10000.0, risk_per_trade=0.01)
        check("run_backtest mini", lambda: f"{bt.n_trades} trades, win_rate={bt.win_rate:.2%}")
        if bt.n_trades > 0:
            from backtest.monte_carlo import run_monte_carlo
            mc = run_monte_carlo(bt, n_runs=10_000, risk_per_trade=0.01)
            check("monte_carlo 10k runs", lambda: f"prob_profit={mc.prob_profit:.2%}, median final ${mc.final_equity_p50:.0f}")

    print("\n[6] Full signal engine")
    try:
        from signal_engine import generate_signals
        bundle = generate_signals(use_pm_narrative=False)
        check("generate_signals", lambda: f"price=${bundle.xau_price}, regime={bundle.regime}, debate={bundle.debate['final_action']}")
    except Exception as e:
        print(f"  [FAIL] generate_signals: {e}")
        FAIL_local = True

    print("\n" + "=" * 60)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import pandas as pd
    sys.exit(main())
