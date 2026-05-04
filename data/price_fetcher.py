"""Price fetcher (yfinance, free). Cache hasil di disk biar nggak hammer API."""
from __future__ import annotations
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config.settings import DATA_CACHE, TICKERS

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

PERIOD_DEFAULT = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "4h": "730d",
    "1d": "max",
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


def fetch_xau(interval: str = "1h", period: Optional[str] = None) -> pd.DataFrame:
    return fetch_ohlcv(TICKERS["xau"], interval, period)


def fetch_intermarket_bundle(interval: str = "1h", period: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """Bundle XAU + DXY + US10Y + VIX + SPX untuk feature engineering."""
    out = {}
    for key in ("xau", "dxy", "us10y", "vix", "spx", "silver"):
        try:
            out[key] = fetch_ohlcv(TICKERS[key], interval, period)
        except Exception as e:
            out[key] = pd.DataFrame()
            print(f"[warn] fetch {key} failed: {e}")
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
