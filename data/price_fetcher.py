"""Price fetcher (yfinance, free). Cache hasil di disk biar nggak hammer API."""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config.settings import DATA_CACHE, TICKERS

# Fallback tickers per asset — kalau primary gagal (GC=F sering ke-block / delisted-state), coba alternatif.
# Order matters: paling akurat dulu.
FALLBACK_TICKERS = {
    "xau":    ["GC=F", "XAUUSD=X", "GLD", "IAU"],     # gold futures -> spot fx -> ETF -> alt ETF
    "dxy":    ["DX-Y.NYB", "DX=F", "UUP"],            # ICE DXY -> futures -> bullish dollar ETF
    "us10y":  ["^TNX", "^IRX", "TLT"],                # 10Y yield -> 13W -> long bond ETF
    "vix":    ["^VIX"],
    "spx":    ["^GSPC", "SPY"],
    "silver": ["SI=F", "XAGUSD=X", "SLV"],
}

CACHE_TTL = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 1800,
    "4h": 3600,
    "1d": 21600,
}

INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "1h",     # yfinance no 4h, resample dari 1h
    "1d": "1d",
}

# Yahoo Finance hard limits per interval (semakin kecil interval, semakin pendek max period)
# Bekas "730d" untuk 1h sering hit rate-limit / empty response. Pakai 60d aja - lebih reliable.
PERIOD_DEFAULT = {
    "1m": "5d",
    "5m": "30d",
    "15m": "30d",
    "30m": "30d",
    "1h": "60d",      # was 730d (too greedy, sering empty)
    "4h": "180d",     # was 730d
    "1d": "5y",       # was max (max kadang trigger weird state)
}


def _cache_path(symbol: str, interval: str) -> Path:
    safe = symbol.replace("=", "_").replace("^", "").replace("-", "_")
    return DATA_CACHE / f"{safe}__{interval}.parquet"


def _is_cache_fresh(path: Path, interval: str) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL.get(interval, 1800)


def fetch_ohlcv(
    symbol: str,
    interval: str = "1h",
    period: Optional[str] = None,
    use_cache: bool = True,
    auto_adjust: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV; cache di parquet. interval='4h' di-resample dari 1h."""
    cache = _cache_path(symbol, interval)
    if use_cache and _is_cache_fresh(cache, interval):
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass

    yf_interval = INTERVAL_MAP.get(interval, interval)
    period = period or PERIOD_DEFAULT.get(interval, "60d")

    df = yf.download(
        symbol,
        period=period,
        interval=yf_interval,
        progress=False,
        auto_adjust=auto_adjust,
        threads=False,
    )

    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty for {symbol} {interval}")

    # Flatten MultiIndex kolom kalau yfinance balikinnya begitu
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    df.columns = [c.lower() for c in df.columns]
    df.index.name = "time"

    # Resample 4h dari 1h
    if interval == "4h":
        df = df.resample("4h", label="right", closed="right").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna()

    df = df.dropna(subset=["close"])

    try:
        df.to_parquet(cache)
    except Exception:
        pass

    return df


def _fetch_with_fallback(asset_key: str, interval: str, period: Optional[str] = None) -> pd.DataFrame:
    """Try primary ticker, fall back to alternatives if Yahoo returns empty / rate-limits."""
    candidates = FALLBACK_TICKERS.get(asset_key, [])
    if not candidates:
        # Unknown key, try config TICKERS direct
        sym = TICKERS.get(asset_key)
        if sym:
            return fetch_ohlcv(sym, interval, period)
        raise RuntimeError(f"no ticker config for {asset_key}")

    last_error: Exception | None = None
    for i, sym in enumerate(candidates):
        try:
            df = fetch_ohlcv(sym, interval, period, use_cache=(i == 0))
            if df is not None and not df.empty:
                if i > 0:
                    print(f"[fallback] {asset_key} pakai {sym} (primary {candidates[0]} gagal)")
                return df
        except Exception as e:
            last_error = e
            # don't print on first failure (often transient), only if all fail
    raise RuntimeError(f"all tickers failed for {asset_key} ({candidates}): {last_error}")


def fetch_xau(interval: str = "1h", period: Optional[str] = None) -> pd.DataFrame:
    return _fetch_with_fallback("xau", interval, period)


def fetch_intermarket_bundle(interval: str = "1h", period: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """Bundle XAU + DXY + US10Y + VIX + SPX. Each ticker has its own fallback chain."""
    out = {}
    for key in ("xau", "dxy", "us10y", "vix", "spx", "silver"):
        try:
            out[key] = _fetch_with_fallback(key, interval, period)
        except Exception as e:
            out[key] = pd.DataFrame()
            print(f"[warn] fetch {key} failed (all fallbacks exhausted): {e}")
    return out


def latest_price(symbol: str = TICKERS["xau"]) -> Optional[float]:
    try:
        df = fetch_ohlcv(symbol, "5m", period="1d", use_cache=False)
        return float(df["close"].iloc[-1])
    except Exception:
        return None


if __name__ == "__main__":
    # Smoke test
    import sys
    df = fetch_xau("1h", "30d")
    print(f"[ok] XAU 1h: {len(df)} rows, last close = {df['close'].iloc[-1]:.2f}")
    print(df.tail(3))
