"""Live recalibrator for futures_premium_gap.txt.

WHY THIS EXISTS (2026-05-06 session):
- Twelve Data quota burned daily -> daemon Tier 1 spot fetch returns yfinance fallback
  (= GC=F futures, has +$5..$20 premium over broker spot).
- Yahoo HTTPS XAUUSD=X 404s -> daemon Tier 2 also dead.
- Daemon falls through to Tier 3: GC=F minus _load_premium_gap() static value.
- Without a working spot source feeding the runner's gap-saver, that static stays at
  the env default `XAU_FUTURES_PREMIUM_USD=7.0` while the real gap moves $5..$20.

PRAGMATIC FIX (this script):
- Pulls fresh GC=F (yfinance, works) + XAU spot (stooq.com CSV, free, no key, no quota).
- Computes gap = GC=F - XAU.
- Writes data_cache/futures_premium_gap.txt every 60s.
- Daemon's _load_premium_gap() (runner.py) reads this file every cycle and uses it
  in: spot_for_entry = df_close - gap. ZERO daemon code change.

USAGE (run in a separate PowerShell tab, leave open):
    cd C:\\Users\\Administrator\\yeehee-daemon
    .venv\\Scripts\\activate
    python scripts/recalibrate_gap.py

OR background once:
    python scripts/recalibrate_gap.py >> data_cache/recalibrate_gap.log 2>&1 &

STOP: Ctrl+C, or `del data_cache\\futures_premium_gap.txt` to revert to env default.

WHEN TO RETIRE THIS SCRIPT:
- Twelve Data quota reset (next UTC midnight) AND we upgrade to paid plan, OR
- proper Tier 2 stooq fetcher added to data/price_fetcher.py + runner.py wires it in,
  OR
- MT5 EA mirror (Tier 0) running -> broker-grade $0 gap, no estimation needed.
"""
from __future__ import annotations
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Resolve repo root (script lives in scripts/ subfolder)
ROOT = Path(__file__).resolve().parent.parent
GAP_FILE = ROOT / "data_cache" / "futures_premium_gap.txt"

# Sanity: must match runner.py:_load_premium_gap range check (1.0 < v < 30.0)
GAP_MIN = 1.0
GAP_MAX = 25.0  # tighter than runner sanity, gold basis rarely > $25

POLL_SECONDS = 60

try:
    import requests
    import yfinance as yf
except ImportError as e:
    print(f"[recalibrate-gap] FATAL: {e}. Activate .venv first.", file=sys.stderr)
    sys.exit(1)


def fetch_gc_close() -> float | None:
    """Latest GC=F 5m close via yfinance (proven to work on PC kantor)."""
    try:
        df = yf.download("GC=F", period="1d", interval="5m",
                         progress=False, threads=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        v = float(df["Close"].iloc[-1])
        return v if v > 1000 else None  # sanity: gold price not GLD ETF
    except Exception as e:
        print(f"[recalibrate-gap] yfinance err: {e!r}")
        return None


def fetch_stooq_xau() -> float | None:
    """XAU/USD spot from stooq.com CSV. No API key, no quota."""
    try:
        r = requests.get(
            "https://stooq.com/q/l/?s=xauusd&i=d&f=sd2t2ohlcv&h&e=csv",
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code != 200:
            return None
        lines = r.text.strip().split("\n")
        if len(lines) < 2:
            return None
        parts = lines[1].split(",")
        if len(parts) < 7:
            return None
        v = float(parts[6])  # close column
        return v if v > 1000 else None
    except Exception as e:
        print(f"[recalibrate-gap] stooq err: {e!r}")
        return None


def write_gap(gap: float) -> bool:
    try:
        GAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        GAP_FILE.write_text(f"{gap:.2f}\n", encoding="utf-8")
        return True
    except Exception as e:
        print(f"[recalibrate-gap] write err: {e!r}")
        return False


def main() -> None:
    print(f"[recalibrate-gap] starting --writing {GAP_FILE} every {POLL_SECONDS}s")
    print(f"[recalibrate-gap] gap range allowed: ${GAP_MIN:.2f} .. ${GAP_MAX:.2f}")
    last_gap: float | None = None

    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        gc = fetch_gc_close()
        xau = fetch_stooq_xau()

        if gc is None or xau is None:
            print(f"[recalibrate-gap] {ts} skip --gc={gc} xau={xau}")
        else:
            raw_gap = gc - xau
            # Clip to sane range (sometimes basis goes negative briefly during fast rallies;
            # daemon sanity rejects gap <= 1.0, so we floor to GAP_MIN+0.01)
            if raw_gap < GAP_MIN:
                gap = GAP_MIN + 0.01
                clip = "clip-low"
            elif raw_gap > GAP_MAX:
                gap = GAP_MAX
                clip = "clip-high"
            else:
                gap = raw_gap
                clip = "ok"

            if write_gap(gap):
                delta = "" if last_gap is None else f" (delta {gap-last_gap:+.2f})"
                print(f"[recalibrate-gap] {ts} GC=F=${gc:.2f} XAU=${xau:.2f} "
                      f"raw_gap=${raw_gap:.2f} -> wrote ${gap:.2f} [{clip}]{delta}",
                      flush=True)
                last_gap = gap

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[recalibrate-gap] stopped by user")
