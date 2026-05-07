"""Centralized config. Semua tunable params di sini, no magic numbers di kode lain."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ===== Tickers (yfinance, free) =====
TICKERS = {
    "xau": "GC=F",          # Gold futures (paling likuid + free)
    "dxy": "DX-Y.NYB",       # Dollar Index
    "us10y": "^TNX",         # US 10Y yield
    "us2y": "^IRX",          # US 13W (proxy short-end)
    "tip": "TIP",            # TIPS ETF (real yield proxy)
    "vix": "^VIX",
    "spx": "^GSPC",
    "silver": "SI=F",        # Untuk gold/silver ratio
    "oil": "CL=F",
}

# ===== Trading sessions (UTC) =====
SESSIONS_UTC = {
    "asia":   (0, 8),    # 00:00–08:00 UTC
    "london": (7, 16),   # 07:00–16:00 UTC
    "ny":     (12, 21),  # 12:00–21:00 UTC
    "overlap_lon_ny": (12, 16),
}

# London Fix times (UTC)
LONDON_FIX_AM = "10:30"
LONDON_FIX_PM = "15:00"

# ===== High-impact news (no-trade window) =====
HIGH_IMPACT_BLACKOUT_MIN = 30  # Block 30 min sebelum & sesudah event red

# ===== Risk profiles =====
RISK_PROFILES = {
    "konservatif":  {"risk_per_trade": 0.005, "max_daily_loss": 0.02, "max_concurrent": 1, "kelly_frac": 0.15},
    "moderat":      {"risk_per_trade": 0.010, "max_daily_loss": 0.04, "max_concurrent": 2, "kelly_frac": 0.25},
    "agresif":      {"risk_per_trade": 0.020, "max_daily_loss": 0.06, "max_concurrent": 3, "kelly_frac": 0.40},
    "bebas":        {"risk_per_trade": 0.050, "max_daily_loss": 0.20, "max_concurrent": 5, "kelly_frac": 1.00},
}

# ===== Signal confluence threshold =====
@dataclass(frozen=True)
class SignalThresholds:
    min_confluence: int = 5         # min jumlah faktor agree
    min_confidence: float = 0.65    # 0..1
    strong_confidence: float = 0.80
    require_mtf_align: bool = True
    require_intermarket: bool = True
    veto_on_news_blackout: bool = True

THRESHOLDS = SignalThresholds()

# ===== AI agent =====
@dataclass(frozen=True)
class AIConfig:
    model: str = "claude-opus-4-7"
    max_tokens: int = 2048
    temperature: float = 0.2
    debate_rounds: int = 1
    require_n_of_4_agree: int = 3   # 3-of-4 agent agreement

AI = AIConfig()

# ===== Strategy params =====
@dataclass(frozen=True)
class ScalperConfig:
    timeframe: str = "5m"
    htf_filter: str = "1h"
    atr_period: int = 14
    # 2026-05-07 RR-3:1 spec: TP1 = 3 × SL distance. Scalper SL=1.2×ATR, so
    # TP1=3.6×ATR. EA's BEP-at-1R lock breakeven once first ATR-distance covered.
    sl_atr_mult: float = 1.2
    tp1_atr_mult: float = 3.6
    tp2_atr_mult: float = 4.8   # buffered above TP1 for partial-close future use
    tp3_atr_mult: float = 6.0

@dataclass(frozen=True)
class IntradayConfig:
    timeframe: str = "15m"
    htf_filter: str = "4h"
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp1_atr_mult: float = 4.5   # = 3 × sl_atr_mult (RR 3:1)
    tp2_atr_mult: float = 6.0
    tp3_atr_mult: float = 7.5

@dataclass(frozen=True)
class SwingConfig:
    timeframe: str = "4h"
    htf_filter: str = "1d"
    atr_period: int = 14
    sl_atr_mult: float = 2.0
    tp1_atr_mult: float = 6.0   # = 3 × sl_atr_mult (RR 3:1)
    tp2_atr_mult: float = 8.0
    tp3_atr_mult: float = 10.0

SCALPER = ScalperConfig()
INTRADAY = IntradayConfig()
SWING = SwingConfig()

# ===== Backtest =====
@dataclass(frozen=True)
class BacktestConfig:
    spread_pips: float = 2.0           # XAU spread typical 20-30 cents = 2-3 pips
    slippage_pips: float = 0.5
    commission_per_lot: float = 7.0    # USD per lot per round trip
    monte_carlo_runs: int = 100_000
    walk_forward_splits: int = 5
    out_of_sample_pct: float = 0.20

BACKTEST = BacktestConfig()

# ===== Paths =====
DATA_CACHE = ROOT / "data_cache"
BACKTEST_RESULTS = ROOT / "backtest_results"
DATA_CACHE.mkdir(exist_ok=True)
BACKTEST_RESULTS.mkdir(exist_ok=True)

# ===== Env =====
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip()
TIMEZONE = os.getenv("TIMEZONE", "Asia/Jakarta")
DEFAULT_RISK_PROFILE = os.getenv("DEFAULT_RISK_PROFILE", "moderat")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

HAS_AI_KEY = bool(ANTHROPIC_API_KEY)
HAS_TELEGRAM = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
