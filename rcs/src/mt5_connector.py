"""MT5 Connector — single source-of-truth for all MetaTrader5 communication.

Other modules MUST import this connector instead of `MetaTrader5` directly.
Reasons:
  - Mock-mode fallback when MT5 lib unavailable (macOS/Linux dev, missing install)
  - Centralised config + symbol resolution + tz conversion
  - Easy to swap brokers (one config edit, not codebase-wide)

Usage:
    from rcs.src.mt5_connector import MT5Connector
    conn = MT5Connector()
    conn.connect()  # uses MT5_LOGIN/MT5_PASSWORD/MT5_SERVER from env
    df = conn.fetch_candles('M5', n_candles=10000)

Mock mode:
    Setiap method return placeholder data atau raise FriendlyError. Test bisa
    pakai konektor ini tanpa real MT5 connection. Production daemon HARUS
    detect mock mode + skip push ke rcs_signals (otherwise corrupt data).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

try:
    import MetaTrader5 as mt5  # type: ignore
    HAS_MT5 = True
except ImportError:
    mt5 = None  # type: ignore
    HAS_MT5 = False


_CONFIG_DEFAULTS = {
    "symbol": "XAUUSD",
    "point_size": 0.01,
    "tick_value_per_lot": 1.0,
    "min_lot": 0.01,
    "max_lot": 100.0,
    "lot_step": 0.01,
    "stops_level_points": 30,
    "server_tz_offset_hours": 2,
    "display_tz": "Asia/Jakarta",
}

_TF_MAP = {
    "M5":  5,        # Will be replaced with mt5.TIMEFRAME_M5 at runtime
    "M15": 15,
    "H1":  16385,    # mt5.TIMEFRAME_H1 numeric value
}


class MT5ConnectionError(RuntimeError):
    """Raised when MT5 lib unavailable or login fails."""
    pass


class MT5Connector:
    """Thin wrapper over MetaTrader5 lib. Mock-mode safe."""

    def __init__(self, config_path: str | Path = "config.yaml"):
        config_path = Path(config_path)
        if not config_path.is_absolute():
            # Resolve relative to rcs/ folder (one level up from src/)
            rcs_root = Path(__file__).resolve().parent.parent
            config_path = rcs_root / config_path
        if not config_path.exists():
            raise FileNotFoundError(f"RCS config.yaml not found at {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f) or {}

        mt5_cfg = self.cfg.get("mt5", {})
        merged = {**_CONFIG_DEFAULTS, **mt5_cfg}
        self.symbol     = os.environ.get("RCS_SYMBOL") or merged["symbol"]
        self.point_size = float(merged["point_size"])
        self.server_tz_offset = int(merged["server_tz_offset_hours"])
        self._connected = False
        self._mock_mode = not HAS_MT5

    @property
    def is_mock(self) -> bool:
        """True kalau MT5 lib ga tersedia. Production daemon harus skip writes."""
        return self._mock_mode

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, login: Optional[int] = None,
                password: Optional[str] = None,
                server: Optional[str] = None) -> dict:
        """Connect + login. Returns symbol_info dict.

        Reads credentials from env (MT5_LOGIN/PASSWORD/SERVER) if not passed.
        Raises MT5ConnectionError on any failure.
        """
        if self._mock_mode:
            self._connected = False
            raise MT5ConnectionError(
                "MetaTrader5 lib tidak ke-install. "
                "Jalanin: pip install MetaTrader5 (Windows only). "
                "Atau set RCS_MOCK_MODE=1 untuk test tanpa MT5."
            )

        login_val    = login    or int(os.environ.get("MT5_LOGIN", "0"))
        password_val = password or os.environ.get("MT5_PASSWORD", "")
        server_val   = server   or os.environ.get("MT5_SERVER", "")

        if not login_val or not password_val or not server_val:
            raise MT5ConnectionError(
                "MT5 credentials missing. Set MT5_LOGIN + MT5_PASSWORD + MT5_SERVER di rcs/.env"
            )

        if not mt5.initialize():
            raise MT5ConnectionError(f"MT5 init failed: {mt5.last_error()}")

        if not mt5.login(login_val, password=password_val, server=server_val):
            raise MT5ConnectionError(f"MT5 login failed (login={login_val}, server={server_val}): {mt5.last_error()}")

        info = mt5.symbol_info(self.symbol)
        if info is None:
            available = [s.name for s in mt5.symbols_get()][:30]
            raise MT5ConnectionError(
                f"Symbol '{self.symbol}' not found at broker. "
                f"Common variants: XAUUSD, XAUUSD., XAUUSDm, GOLD. "
                f"Sample available symbols: {available}"
            )

        if not info.visible:
            mt5.symbol_select(self.symbol, True)

        # Update config in memory if broker reality differs
        actual_point = float(info.point)
        if abs(actual_point - self.point_size) > 1e-9:
            self.point_size = actual_point

        self._connected = True
        return {
            "symbol":             self.symbol,
            "point_size":         actual_point,
            "tick_value":         float(info.trade_tick_value),
            "min_lot":            float(info.volume_min),
            "max_lot":            float(info.volume_max),
            "lot_step":           float(info.volume_step),
            "stops_level_points": int(info.trade_stops_level),
            "spread_typical":     int(info.spread),
            "digits":             int(info.digits),
        }

    def fetch_candles(self, timeframe: str, n_candles: int = 100000) -> pd.DataFrame:
        """Fetch historical candles. Returns DataFrame indexed by UTC timestamp.

        Args:
            timeframe: 'M5', 'M15', or 'H1'
            n_candles: how many bars to retrieve (most recent N)

        Returns columns: open, high, low, close, volume, spread
        """
        if self._mock_mode:
            raise MT5ConnectionError("fetch_candles not available in mock mode")
        if not self._connected:
            raise MT5ConnectionError("Not connected. Call connect() first.")
        if timeframe not in _TF_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Use M5/M15/H1.")

        # Use real mt5.TIMEFRAME_* constants at runtime
        tf_const = getattr(mt5, f"TIMEFRAME_{timeframe}")
        rates = mt5.copy_rates_from_pos(self.symbol, tf_const, 0, n_candles)
        if rates is None or len(rates) == 0:
            raise MT5ConnectionError(f"No candle data returned for {self.symbol} {timeframe}")

        df = pd.DataFrame(rates)
        # MT5 timestamps are server local time. Convert to true UTC by subtracting server tz.
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["time"] = df["time"] - timedelta(hours=self.server_tz_offset)
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume", "real_volume": "real_vol"})

        cols = ["open", "high", "low", "close", "volume", "spread"]
        return df[[c for c in cols if c in df.columns]]

    def get_current_spot(self) -> Optional[float]:
        """Latest tick mid-price. Returns None if not connected or tick unavailable."""
        if self._mock_mode or not self._connected:
            return None
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None
        return (tick.bid + tick.ask) / 2

    def get_symbol_specs(self) -> dict:
        """Return broker specs (for UI + future EA + Kalkulator integration)."""
        if self._mock_mode or not self._connected:
            return {**_CONFIG_DEFAULTS, "symbol": self.symbol, "_mock": True}
        info = mt5.symbol_info(self.symbol)
        return {
            "symbol":      self.symbol,
            "point_size":  float(info.point),
            "tick_value":  float(info.trade_tick_value),
            "min_lot":     float(info.volume_min),
            "max_lot":     float(info.volume_max),
            "lot_step":    float(info.volume_step),
            "stops_level": int(info.trade_stops_level),
            "spread_typical": int(info.spread),
            "digits":      int(info.digits),
        }

    def shutdown(self) -> None:
        if self._connected and not self._mock_mode:
            try:
                mt5.shutdown()
            except Exception:
                pass
        self._connected = False


def smoke_test():
    """Quick verifier — run via: python -m rcs.src.mt5_connector"""
    conn = MT5Connector()
    print(f"Mock mode: {conn.is_mock}")
    print(f"Symbol:    {conn.symbol}")
    print(f"Point:     {conn.point_size}")
    if conn.is_mock:
        print("MetaTrader5 lib not installed — skip live test.")
        print("Install: pip install MetaTrader5 (Windows only)")
        return
    try:
        info = conn.connect()
        print(f"Connected. Specs: {info}")
        spot = conn.get_current_spot()
        print(f"Current spot: {spot}")
        df = conn.fetch_candles("M5", n_candles=5)
        print(f"M5 candles tail:\n{df.tail()}")
    except MT5ConnectionError as e:
        print(f"Connection error: {e}")
    finally:
        conn.shutdown()


if __name__ == "__main__":
    smoke_test()
