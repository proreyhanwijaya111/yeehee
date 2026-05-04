"""Pure-numpy/pandas indicators. Tidak depend pandas-ta agar transparan + zero install pain."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_e = ema(close, fast)
    slow_e = ema(close, slow)
    line = fast_e - slow_e
    sig = ema(line, signal)
    hist = line - sig
    return pd.DataFrame({"macd": line, "signal": sig, "hist": hist})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n) * n  # de-smooth
    atr_n = atr(df, n)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_n.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_n.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_n = dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return pd.DataFrame({"adx": adx_n, "plus_di": plus_di, "minus_di": minus_di})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    upper = mid + k * sd
    lower = mid - k * sd
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower)
    return pd.DataFrame({"bb_mid": mid, "bb_up": upper, "bb_low": lower, "bb_width": width, "bb_pctb": pct_b})


def stoch(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    h, l, c = df["high"], df["low"], df["close"]
    ll = l.rolling(k, min_periods=k).min()
    hh = h.rolling(k, min_periods=k).max()
    raw_k = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    sk = raw_k.rolling(smooth, min_periods=smooth).mean()
    sd = sk.rolling(d, min_periods=d).mean()
    return pd.DataFrame({"stoch_k": sk, "stoch_d": sd})


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP — assumes index is datetime; reset per UTC day."""
    if "volume" not in df.columns or df["volume"].sum() == 0:
        return pd.Series(index=df.index, dtype=float)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = tp * df["volume"]
    grouper = df.index.floor("D") if hasattr(df.index, "floor") else None
    if grouper is None:
        return pv.cumsum() / df["volume"].cumsum()
    return pv.groupby(grouper).cumsum() / df["volume"].groupby(grouper).cumsum()


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan semua indikator standar ke df. Returns new df."""
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi14"] = rsi(out["close"], 14)
    macd_df = macd(out["close"])
    out = out.join(macd_df)
    out["atr14"] = atr(out, 14)
    adx_df = adx(out, 14)
    out = out.join(adx_df)
    bb = bollinger(out["close"])
    out = out.join(bb)
    st = stoch(out)
    out = out.join(st)
    try:
        out["vwap"] = vwap(out)
    except Exception:
        pass
    return out


def trend_state(df: pd.DataFrame) -> pd.Series:
    """+1 strong up, +0.5 weak up, 0 neutral, -0.5 weak dn, -1 strong dn."""
    e9, e21, e50, e200 = df["ema9"], df["ema21"], df["ema50"], df["ema200"]
    state = pd.Series(0.0, index=df.index)
    state += np.where(e9 > e21, 0.25, -0.25)
    state += np.where(e21 > e50, 0.25, -0.25)
    state += np.where(e50 > e200, 0.5, -0.5)
    return state.clip(-1, 1)
