"""
================================================================================
XAU PATTERN TRADING AGENT
================================================================================
A production-grade candlestick pattern detection & backtesting agent for Gold.

Author: Built from real, peer-reviewed candlestick research
References:
  - Bulkowski, T. "Encyclopedia of Candlestick Charts" (Wiley, 2008)
  - Nison, S. "Japanese Candlestick Charting Techniques" (Penguin, 2001)
  - Marshall, B.R., Young, M.R., Rose, L.C. (2006) "Candlestick technical 
    trading strategies: Can they create value for investors?" 
    Journal of Banking & Finance, 30(8), 2303-2323.
  - Caginalp, G., Laurent, H. (1998) "The Predictive Power of Price Patterns"
    Applied Mathematical Finance, 5(3), 181-205.

USAGE:
    # As CLI:
    python xau_pattern_agent.py scan data.csv
    python xau_pattern_agent.py backtest data.csv --pattern bullish_engulfing
    python xau_pattern_agent.py analyze data.csv
    python xau_pattern_agent.py signal data.csv  # latest signal

    # As library:
    from xau_pattern_agent import PatternAgent
    agent = PatternAgent.from_csv("data.csv")
    signals = agent.scan()
    results = agent.backtest_all_patterns()
    
DATA FORMAT (CSV):
    Date,Open,High,Low,Close,Volume  (Volume optional)
    2010-01-04,1097.85,1133.6,1075.0,1118.4,...
"""
from __future__ import annotations
import sys
import argparse
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional
from pathlib import Path

import numpy as np
import pandas as pd

# ============================================================================
# 1. UTILITIES
# ============================================================================

def true_range(df: pd.DataFrame) -> pd.Series:
    """Compute True Range for ATR."""
    h_l = df['High'] - df['Low']
    h_pc = (df['High'] - df['Close'].shift(1)).abs()
    l_pc = (df['Low'] - df['Close'].shift(1)).abs()
    return pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).rolling(period).mean()

def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add helper columns used by patterns and the agent."""
    df = df.copy()
    df['Body']      = (df['Close'] - df['Open']).abs()
    df['UpperWick'] = df['High'] - df[['Open','Close']].max(axis=1)
    df['LowerWick'] = df[['Open','Close']].min(axis=1) - df['Low']
    df['Range']     = df['High'] - df['Low']
    df['Bullish']   = df['Close'] > df['Open']
    df['Bearish']   = df['Close'] < df['Open']
    df['ATR14']     = atr(df, 14)
    df['EMA20']     = ema(df['Close'], 20)
    df['EMA50']     = ema(df['Close'], 50)
    df['EMA200']    = ema(df['Close'], 200)
    df['BodyAvg14'] = df['Body'].rolling(14).mean()
    df['RangeAvg14']= df['Range'].rolling(14).mean()
    df['Trend']     = np.where(df['Close'] > df['EMA200'], 'up',
                       np.where(df['Close'] < df['EMA200'], 'down', 'flat'))
    return df

def find_swing_levels(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Identify recent swing highs and lows (pivots).  A swing high at bar i is a
    bar whose high is the highest within +/-`lookback` bars.  Used for
    support/resistance confluence with patterns.
    """
    df = df.copy()
    df['SwingHigh'] = (df['High'] == df['High'].rolling(2*lookback+1, center=True).max()).astype(int)
    df['SwingLow']  = (df['Low']  == df['Low'].rolling(2*lookback+1,  center=True).min()).astype(int)
    return df

def near_key_level(df: pd.DataFrame, idx: int, lookback: int = 100, 
                   tolerance_atr: float = 1.0) -> tuple[bool, str]:
    """
    Check if current bar is within `tolerance_atr` ATRs of a recent swing high
    or low. Returns (is_near, level_type).
    """
    if idx < lookback or idx >= len(df):
        return False, 'none'
    window = df.iloc[max(0, idx-lookback):idx]
    cur_close = df['Close'].iloc[idx]
    atr_val = df['ATR14'].iloc[idx]
    if not np.isfinite(atr_val) or atr_val <= 0:
        return False, 'none'
    
    swing_highs = window[window['SwingHigh'] == 1]['High'] if 'SwingHigh' in window.columns else pd.Series()
    swing_lows  = window[window['SwingLow']  == 1]['Low']  if 'SwingLow'  in window.columns else pd.Series()
    
    for h in swing_highs:
        if abs(cur_close - h) <= tolerance_atr * atr_val:
            return True, 'resistance'
    for l in swing_lows:
        if abs(cur_close - l) <= tolerance_atr * atr_val:
            return True, 'support'
    return False, 'none'

# Session helpers (UTC times). XAU/USD shows distinct behavior across sessions:
#  Asian:   00:00-08:00 UTC  (typically range-bound, low vol)
#  London:  08:00-16:00 UTC  (highest gold liquidity, breakouts common)
#  NY:      13:00-22:00 UTC  (most volatile, news-driven moves)
def session_of(ts: pd.Timestamp) -> str:
    """Return session label for a UTC timestamp."""
    h = ts.hour
    if 8 <= h < 13:  return 'london'
    if 13 <= h < 16: return 'london_ny_overlap'   # highest vol
    if 16 <= h < 22: return 'ny'
    return 'asia'

# ============================================================================
# 2. CANDLESTICK PATTERN DETECTORS
# ----------------------------------------------------------------------------
# Each detector returns a Series of 0/+1/-1: 0=no pattern, +1=bullish, -1=bearish
# Pattern definitions follow Bulkowski (2008) and Nison (2001) conventions.
# ============================================================================

def _is_doji(df: pd.DataFrame, body_threshold: float = 0.1) -> pd.Series:
    """Body smaller than `body_threshold` of the range."""
    return df['Body'] < body_threshold * df['Range'].replace(0, np.nan)

def hammer(df: pd.DataFrame) -> pd.Series:
    """
    Hammer (bullish): small body at top, lower wick >= 2x body, little/no upper
    wick, must occur in DOWNTREND. Hanging man = same shape but in uptrend.
    """
    body = df['Body']
    cond = (
        (df['LowerWick'] >= 2 * body) &
        (df['UpperWick'] <= 0.3 * body) &
        (body > 0) &
        (df['Close'] > df['EMA20'].shift(1))  # confirmation: close above prior EMA20
    )
    # Hammer: in downtrend (price below EMA50 last 5 bars or sliding)
    downtrend = df['Close'].shift(1) < df['EMA50'].shift(1)
    return np.where(cond & downtrend, 1, 0)

def shooting_star(df: pd.DataFrame) -> pd.Series:
    """
    Shooting Star (bearish): small body at bottom, upper wick >= 2x body,
    little/no lower wick, occurs in UPTREND.
    """
    body = df['Body']
    cond = (
        (df['UpperWick'] >= 2 * body) &
        (df['LowerWick'] <= 0.3 * body) &
        (body > 0)
    )
    uptrend = df['Close'].shift(1) > df['EMA50'].shift(1)
    return np.where(cond & uptrend, -1, 0)

def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """
    Bullish engulfing: prev bar bearish, current bullish, current body engulfs
    prev body (open below prev close, close above prev open). Should occur in
    a downtrend / pullback.
    """
    prev_bear = df['Bearish'].shift(1)
    curr_bull = df['Bullish']
    engulf = (df['Open'] <= df['Close'].shift(1)) & (df['Close'] >= df['Open'].shift(1))
    body_dominance = df['Body'] > df['Body'].shift(1)
    downtrend = df['Close'].shift(2) < df['EMA20'].shift(2)
    cond = prev_bear & curr_bull & engulf & body_dominance & downtrend
    return np.where(cond.fillna(False), 1, 0)

def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Mirror of bullish engulfing."""
    prev_bull = df['Bullish'].shift(1)
    curr_bear = df['Bearish']
    engulf = (df['Open'] >= df['Close'].shift(1)) & (df['Close'] <= df['Open'].shift(1))
    body_dominance = df['Body'] > df['Body'].shift(1)
    uptrend = df['Close'].shift(2) > df['EMA20'].shift(2)
    cond = prev_bull & curr_bear & engulf & body_dominance & uptrend
    return np.where(cond.fillna(False), -1, 0)

def piercing_line(df: pd.DataFrame) -> pd.Series:
    """
    Bullish Piercing: prev bar bearish (long body), current opens below prev
    low and closes above midpoint of prev body but below prev open.
    Highest documented win-rate pattern in Quantified Strategies study.
    """
    prev_bear = df['Bearish'].shift(1)
    long_prev = df['Body'].shift(1) > df['BodyAvg14'].shift(1)
    open_below_prev_low = df['Open'] < df['Low'].shift(1)
    midpoint = (df['Open'].shift(1) + df['Close'].shift(1)) / 2
    close_above_mid = df['Close'] > midpoint
    close_below_prev_open = df['Close'] < df['Open'].shift(1)
    cond = prev_bear & long_prev & open_below_prev_low & close_above_mid & close_below_prev_open
    return np.where(cond.fillna(False), 1, 0)

def dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    """Bearish mirror of piercing line."""
    prev_bull = df['Bullish'].shift(1)
    long_prev = df['Body'].shift(1) > df['BodyAvg14'].shift(1)
    open_above_prev_high = df['Open'] > df['High'].shift(1)
    midpoint = (df['Open'].shift(1) + df['Close'].shift(1)) / 2
    close_below_mid = df['Close'] < midpoint
    close_above_prev_open = df['Close'] > df['Open'].shift(1)
    cond = prev_bull & long_prev & open_above_prev_high & close_below_mid & close_above_prev_open
    return np.where(cond.fillna(False), -1, 0)

def morning_star(df: pd.DataFrame) -> pd.Series:
    """
    Morning Star (bullish): 3 candles - long bearish, small body (gap down),
    long bullish closing above midpoint of first candle.
    """
    c1_bear = df['Bearish'].shift(2) & (df['Body'].shift(2) > df['BodyAvg14'].shift(2))
    c2_small = df['Body'].shift(1) < 0.5 * df['Body'].shift(2)
    c3_bull = df['Bullish'] & (df['Body'] > df['BodyAvg14'])
    midpoint = (df['Open'].shift(2) + df['Close'].shift(2)) / 2
    c3_above_mid = df['Close'] > midpoint
    cond = c1_bear & c2_small & c3_bull & c3_above_mid
    return np.where(cond.fillna(False), 1, 0)

def evening_star(df: pd.DataFrame) -> pd.Series:
    """Bearish mirror of morning star."""
    c1_bull = df['Bullish'].shift(2) & (df['Body'].shift(2) > df['BodyAvg14'].shift(2))
    c2_small = df['Body'].shift(1) < 0.5 * df['Body'].shift(2)
    c3_bear = df['Bearish'] & (df['Body'] > df['BodyAvg14'])
    midpoint = (df['Open'].shift(2) + df['Close'].shift(2)) / 2
    c3_below_mid = df['Close'] < midpoint
    cond = c1_bull & c2_small & c3_bear & c3_below_mid
    return np.where(cond.fillna(False), -1, 0)

def three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    """3 consecutive long bullish candles, each opens within prior body and 
    closes near its high."""
    bull3 = df['Bullish'] & df['Bullish'].shift(1) & df['Bullish'].shift(2)
    long3 = (df['Body'] > df['BodyAvg14']) & (df['Body'].shift(1) > df['BodyAvg14'].shift(1)) & (df['Body'].shift(2) > df['BodyAvg14'].shift(2))
    seq = (df['Close'] > df['Close'].shift(1)) & (df['Close'].shift(1) > df['Close'].shift(2))
    open_within = (df['Open'] > df['Open'].shift(1)) & (df['Open'] < df['Close'].shift(1)) & \
                  (df['Open'].shift(1) > df['Open'].shift(2)) & (df['Open'].shift(1) < df['Close'].shift(2))
    cond = bull3 & long3 & seq & open_within
    return np.where(cond.fillna(False), 1, 0)

def three_black_crows(df: pd.DataFrame) -> pd.Series:
    """3 consecutive long bearish candles."""
    bear3 = df['Bearish'] & df['Bearish'].shift(1) & df['Bearish'].shift(2)
    long3 = (df['Body'] > df['BodyAvg14']) & (df['Body'].shift(1) > df['BodyAvg14'].shift(1)) & (df['Body'].shift(2) > df['BodyAvg14'].shift(2))
    seq = (df['Close'] < df['Close'].shift(1)) & (df['Close'].shift(1) < df['Close'].shift(2))
    open_within = (df['Open'] < df['Open'].shift(1)) & (df['Open'] > df['Close'].shift(1)) & \
                  (df['Open'].shift(1) < df['Open'].shift(2)) & (df['Open'].shift(1) > df['Close'].shift(2))
    cond = bear3 & long3 & seq & open_within
    return np.where(cond.fillna(False), -1, 0)

def bullish_harami(df: pd.DataFrame) -> pd.Series:
    """Prev bearish long body contains current small bullish body."""
    prev_bear_long = df['Bearish'].shift(1) & (df['Body'].shift(1) > df['BodyAvg14'].shift(1))
    contained = (df['Open'] > df['Close'].shift(1)) & (df['Close'] < df['Open'].shift(1)) & df['Bullish']
    small_body = df['Body'] < 0.5 * df['Body'].shift(1)
    cond = prev_bear_long & contained & small_body
    return np.where(cond.fillna(False), 1, 0)

def bearish_harami(df: pd.DataFrame) -> pd.Series:
    prev_bull_long = df['Bullish'].shift(1) & (df['Body'].shift(1) > df['BodyAvg14'].shift(1))
    contained = (df['Open'] < df['Close'].shift(1)) & (df['Close'] > df['Open'].shift(1)) & df['Bearish']
    small_body = df['Body'] < 0.5 * df['Body'].shift(1)
    cond = prev_bull_long & contained & small_body
    return np.where(cond.fillna(False), -1, 0)

def inside_bar(df: pd.DataFrame) -> pd.Series:
    """
    Inside bar: current high < prev high AND current low > prev low.
    Not directional by itself - reports +1 if breakout will be tested up,
    -1 if down. We label as 'neutral inside bar' = +/- 1 based on close direction
    of subsequent bar at runtime. For detection, return +1 on detection.
    """
    cond = (df['High'] < df['High'].shift(1)) & (df['Low'] > df['Low'].shift(1))
    return np.where(cond.fillna(False), 1, 0)

def pin_bar_bullish(df: pd.DataFrame) -> pd.Series:
    """
    Pin bar (bullish rejection): lower wick > 2/3 of total range, close in upper
    half. Common at S/R levels.
    """
    cond = (
        (df['LowerWick'] >= 0.66 * df['Range']) &
        (df['Body'] <= 0.33 * df['Range']) &
        (df['Close'] > (df['High'] + df['Low']) / 2) &
        (df['Range'] > 0)
    )
    return np.where(cond.fillna(False), 1, 0)

def pin_bar_bearish(df: pd.DataFrame) -> pd.Series:
    cond = (
        (df['UpperWick'] >= 0.66 * df['Range']) &
        (df['Body'] <= 0.33 * df['Range']) &
        (df['Close'] < (df['High'] + df['Low']) / 2) &
        (df['Range'] > 0)
    )
    return np.where(cond.fillna(False), -1, 0)


# Master registry
PATTERNS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    'hammer':              hammer,
    'shooting_star':       shooting_star,
    'bullish_engulfing':   bullish_engulfing,
    'bearish_engulfing':   bearish_engulfing,
    'piercing_line':       piercing_line,
    'dark_cloud_cover':    dark_cloud_cover,
    'morning_star':        morning_star,
    'evening_star':        evening_star,
    'three_white_soldiers':three_white_soldiers,
    'three_black_crows':   three_black_crows,
    'bullish_harami':      bullish_harami,
    'bearish_harami':      bearish_harami,
    'inside_bar':          inside_bar,
    'pin_bar_bullish':     pin_bar_bullish,
    'pin_bar_bearish':     pin_bar_bearish,
}

PATTERN_BIAS = {  # which patterns are bullish vs bearish
    'hammer': +1, 'bullish_engulfing': +1, 'piercing_line': +1,
    'morning_star': +1, 'three_white_soldiers': +1, 'bullish_harami': +1,
    'pin_bar_bullish': +1,
    'shooting_star': -1, 'bearish_engulfing': -1, 'dark_cloud_cover': -1,
    'evening_star': -1, 'three_black_crows': -1, 'bearish_harami': -1,
    'pin_bar_bearish': -1,
    'inside_bar': 0,  # directional after breakout
}

def detect_all_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Add a column per pattern. Each column: 0/+1/-1 signal."""
    out = df.copy()
    for name, fn in PATTERNS.items():
        out[f'pat_{name}'] = fn(df)
    return out

# ============================================================================
# 3. BACKTEST ENGINE
# ============================================================================

@dataclass
class Trade:
    pattern: str
    entry_date: pd.Timestamp
    direction: int           # +1 long, -1 short
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str         # 'tp', 'sl', 'time'
    bars_held: int
    pnl_R: float             # P&L in units of risk (R-multiples)
    pnl_pct: float

@dataclass
class BacktestResult:
    pattern: str
    trades: list = field(default_factory=list)
    
    @property
    def n(self): return len(self.trades)
    
    @property
    def wins(self): return sum(1 for t in self.trades if t.pnl_R > 0)
    
    @property
    def losses(self): return sum(1 for t in self.trades if t.pnl_R <= 0)
    
    @property
    def win_rate(self): return self.wins / self.n if self.n else 0.0
    
    @property
    def gross_profit(self): return sum(t.pnl_R for t in self.trades if t.pnl_R > 0)
    
    @property
    def gross_loss(self): return abs(sum(t.pnl_R for t in self.trades if t.pnl_R <= 0))
    
    @property
    def profit_factor(self):
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float('inf')
    
    @property
    def expectancy_R(self):
        return sum(t.pnl_R for t in self.trades) / self.n if self.n else 0.0
    
    @property
    def avg_win_R(self):
        wins = [t.pnl_R for t in self.trades if t.pnl_R > 0]
        return np.mean(wins) if wins else 0.0
    
    @property
    def avg_loss_R(self):
        losses = [t.pnl_R for t in self.trades if t.pnl_R <= 0]
        return np.mean(losses) if losses else 0.0
    
    @property
    def max_drawdown_R(self):
        cum = np.cumsum([t.pnl_R for t in self.trades])
        if len(cum) == 0: return 0.0
        peak = np.maximum.accumulate(cum)
        return float(np.max(peak - cum))
    
    @property
    def sharpe(self):
        if self.n < 2: return 0.0
        rs = [t.pnl_R for t in self.trades]
        return float(np.mean(rs) / np.std(rs) * math.sqrt(252)) if np.std(rs) > 0 else 0.0
    
    def summary(self) -> dict:
        return dict(
            pattern=self.pattern, n_trades=self.n, win_rate=round(self.win_rate, 4),
            profit_factor=round(self.profit_factor, 3) if self.profit_factor != float('inf') else None,
            expectancy_R=round(self.expectancy_R, 4),
            avg_win_R=round(self.avg_win_R, 3), avg_loss_R=round(self.avg_loss_R, 3),
            max_drawdown_R=round(self.max_drawdown_R, 2),
            sharpe=round(self.sharpe, 3),
            gross_R=round(sum(t.pnl_R for t in self.trades), 2),
        )

def backtest_pattern(
    df: pd.DataFrame,
    pattern_col: str,
    direction: int,
    risk_atr_mult: float = 1.5,
    reward_atr_mult: float = 3.0,    # R:R = 2.0
    max_bars: int = 10,
    pattern_name: str | None = None,
    spread_usd: float = 0.0,         # round-trip spread cost in price units (NEW)
    allowed_sessions: list[str] | None = None,  # filter entries by session (NEW)
    skip_news_hours: list[int] | None = None,   # UTC hours to skip (NEW), e.g. [12,13,14] for NFP
) -> BacktestResult:
    """
    Backtest one pattern.
    Entry: NEXT bar open after pattern bar.
    Stop loss: entry -/+ risk_atr_mult * ATR (below for long, above for short).
    Take profit: entry +/- reward_atr_mult * ATR.
    Time stop: exit at close after `max_bars` if neither hit.
    Risk per trade is normalized; PnL reported in R-multiples.
    
    NEW for scalping:
      spread_usd        : subtract from gross PnL to model broker spread cost
      allowed_sessions  : ['london','london_ny_overlap','ny','asia'] - only enter in these
      skip_news_hours   : list of UTC hours to skip (NFP=12-14 UTC first Fri/month etc.)
    """
    res = BacktestResult(pattern=pattern_name or pattern_col)
    sigs = df[pattern_col]
    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    opens = df['Open'].values
    atrs = df['ATR14'].values
    dates = df.index
    
    n = len(df)
    for i in range(50, n - max_bars - 1):  # need indicator warmup + future bars
        if sigs.iloc[i] == direction or (sigs.iloc[i] != 0 and direction == 0):
            entry_idx = i + 1
            entry_ts = dates[entry_idx]
            
            # SESSION FILTER
            if allowed_sessions is not None:
                sess = session_of(entry_ts)
                if sess not in allowed_sessions:
                    continue
            # NEWS HOUR FILTER  
            if skip_news_hours is not None and entry_ts.hour in skip_news_hours:
                continue
            
            entry = opens[entry_idx]
            atr_val = atrs[i]
            if not np.isfinite(atr_val) or atr_val <= 0:
                continue
            
            risk = risk_atr_mult * atr_val
            if direction == 1:
                sl = entry - risk
                tp = entry + reward_atr_mult * atr_val
            else:  # -1 short
                sl = entry + risk
                tp = entry - reward_atr_mult * atr_val
            
            exit_price = None
            exit_reason = None
            exit_idx = entry_idx
            for j in range(entry_idx, min(entry_idx + max_bars, n)):
                if direction == 1:
                    if lows[j] <= sl:
                        exit_price, exit_reason, exit_idx = sl, 'sl', j
                        break
                    if highs[j] >= tp:
                        exit_price, exit_reason, exit_idx = tp, 'tp', j
                        break
                else:
                    if highs[j] >= sl:
                        exit_price, exit_reason, exit_idx = sl, 'sl', j
                        break
                    if lows[j] <= tp:
                        exit_price, exit_reason, exit_idx = tp, 'tp', j
                        break
            
            if exit_price is None:
                exit_idx = min(entry_idx + max_bars - 1, n - 1)
                exit_price = closes[exit_idx]
                exit_reason = 'time'
            
            pnl_pts = (exit_price - entry) * direction - spread_usd  # SUBTRACT spread
            pnl_R = pnl_pts / risk
            pnl_pct = pnl_pts / entry * 100
            
            res.trades.append(Trade(
                pattern=res.pattern,
                entry_date=dates[entry_idx],
                direction=direction,
                entry_price=float(entry),
                exit_date=dates[exit_idx],
                exit_price=float(exit_price),
                exit_reason=exit_reason,
                bars_held=exit_idx - entry_idx,
                pnl_R=float(pnl_R),
                pnl_pct=float(pnl_pct),
            ))
    return res

# ============================================================================
# 4. SIGNAL GENERATOR (LIVE / LATEST BAR)
# ============================================================================

@dataclass
class Signal:
    date: pd.Timestamp
    pattern: str
    direction: str       # 'long' / 'short' / 'flat'
    entry: float
    stop: float
    target: float
    atr: float
    rr: float
    confidence: float    # 0..1, composite score
    notes: list = field(default_factory=list)

def latest_signal(df: pd.DataFrame, risk_atr_mult: float = 1.5,
                  reward_atr_mult: float = 3.0) -> list[Signal]:
    """Look at the most recent bar(s) and return any active patterns."""
    df = add_indicators(df)
    df = find_swing_levels(df, lookback=20)
    df = detect_all_patterns(df)
    last = df.iloc[-1]
    out: list[Signal] = []
    
    # Check S/R confluence on the last bar
    is_near_level, level_type = near_key_level(df, len(df)-1, lookback=100, tolerance_atr=1.0)
    
    for name, _ in PATTERNS.items():
        sig = df[f'pat_{name}'].iloc[-1]
        bias = PATTERN_BIAS[name]
        if sig == 0: continue
        
        direction = 'long' if (sig == 1 if bias == 0 else bias == 1) else 'short'
        entry = last['Close']
        atr_val = last['ATR14']
        if not np.isfinite(atr_val) or atr_val <= 0: continue
        
        if direction == 'long':
            stop = entry - risk_atr_mult * atr_val
            target = entry + reward_atr_mult * atr_val
        else:
            stop = entry + risk_atr_mult * atr_val
            target = entry - reward_atr_mult * atr_val
        
        # Confidence scoring
        notes = []
        score = 0.5  # base
        # Trend alignment bonus
        if direction == 'long' and last['Close'] > last['EMA200']:
            score += 0.15; notes.append("aligned with uptrend (EMA200)")
        if direction == 'short' and last['Close'] < last['EMA200']:
            score += 0.15; notes.append("aligned with downtrend (EMA200)")
        if direction == 'long' and last['Close'] < last['EMA200']:
            score -= 0.10; notes.append("counter-trend (caution)")
        if direction == 'short' and last['Close'] > last['EMA200']:
            score -= 0.10; notes.append("counter-trend (caution)")
        # Body strength
        if last['Body'] > last['BodyAvg14']:
            score += 0.10; notes.append("strong body (above avg)")
        # Recent volatility expansion  
        if last['Range'] > 1.5 * last['RangeAvg14']:
            score += 0.05; notes.append("range expansion")
        # S/R confluence (HIGH-IMPACT bonus per Marshall et al. research)
        if is_near_level:
            if direction == 'long' and level_type == 'support':
                score += 0.20; notes.append(f"AT KEY SUPPORT (high-probability)")
            elif direction == 'short' and level_type == 'resistance':
                score += 0.20; notes.append(f"AT KEY RESISTANCE (high-probability)")
        score = max(0.0, min(1.0, score))
        
        out.append(Signal(
            date=df.index[-1], pattern=name, direction=direction,
            entry=float(entry), stop=float(stop), target=float(target),
            atr=float(atr_val), rr=reward_atr_mult/risk_atr_mult,
            confidence=round(score, 3), notes=notes
        ))
    return out

# ============================================================================
# 5b. POSITION SIZING
# ============================================================================

def position_size(account_balance: float, risk_pct: float, entry: float,
                  stop: float, contract_size: float = 100.0) -> dict:
    """
    Compute position size for XAU.
      account_balance : in account currency (USD)
      risk_pct        : 0.01 = 1% of equity per trade
      entry, stop     : prices in USD/oz
      contract_size   : 100 = standard XAU lot (100 oz),
                        10  = mini lot,
                        1   = micro lot.
    Returns dict with risk_usd, lots, units_oz.
    """
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return {'error': 'stop must differ from entry'}
    risk_usd = account_balance * risk_pct
    units_oz = risk_usd / risk_per_unit
    lots = units_oz / contract_size
    return dict(
        risk_usd=round(risk_usd, 2),
        risk_per_oz_usd=round(risk_per_unit, 2),
        units_oz=round(units_oz, 2),
        lots=round(lots, 4),
        notional_usd=round(units_oz * entry, 2),
    )

# ============================================================================
# 5. AGENT FACADE
# ============================================================================

@dataclass
class PatternAgent:
    df: pd.DataFrame
    name: str = "XAU"
    
    @classmethod
    def from_csv(cls, path: str, name: str = "XAU") -> 'PatternAgent':
        raw = pd.read_csv(path)
        # Auto-detect date column
        date_col = next((c for c in raw.columns if c.lower() in ('date','datetime','time','timestamp')), raw.columns[0])
        raw[date_col] = pd.to_datetime(raw[date_col])
        raw = raw.set_index(date_col).sort_index()
        # Standardize column names
        raw.columns = [c.capitalize() for c in raw.columns]
        for col in ['Open', 'High', 'Low', 'Close']:
            assert col in raw.columns, f"Missing column: {col}"
        if 'Volume' not in raw.columns:
            raw['Volume'] = 0
        return cls(df=raw, name=name)
    
    @classmethod
    def from_yfinance(cls, ticker: str = "GC=F", start: str = "2010-01-01",
                      end: str | None = None, interval: str = "1d",
                      name: str | None = None) -> 'PatternAgent':
        """
        Load OHLC data from Yahoo Finance.  Requires `pip install yfinance`.
        Common XAU tickers:
          - 'GC=F'   COMEX Gold futures (most reliable proxy)
          - 'GLD'    SPDR Gold ETF
          - 'XAUUSD=X' (less reliable, often gappy)
        """
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("Install yfinance: pip install yfinance")
        df = yf.download(ticker, start=start, end=end, interval=interval,
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        return cls(df=df, name=name or ticker)
    
    @classmethod
    def from_mt5(cls, symbol: str = "XAUUSD", timeframe: int = None,
                 n_bars: int = 5000, name: str | None = None) -> 'PatternAgent':
        """
        Load OHLC data from MetaTrader 5.  Requires `pip install MetaTrader5`
        and a running MT5 terminal logged into a broker.
        timeframe: use mt5.TIMEFRAME_D1, mt5.TIMEFRAME_H4, etc.
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            raise ImportError("Install MetaTrader5: pip install MetaTrader5")
        if not mt5.initialize():
            raise RuntimeError("Failed to initialize MT5 - is the terminal running?")
        if timeframe is None:
            timeframe = mt5.TIMEFRAME_D1
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
        mt5.shutdown()
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No data for {symbol}")
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.rename(columns={'time': 'Date', 'open': 'Open', 'high': 'High',
                                'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'})
        df = df.set_index('Date')[['Open','High','Low','Close','Volume']]
        return cls(df=df, name=name or symbol)
    
    @classmethod
    def from_dataframe(cls, df: pd.DataFrame, name: str = "XAU") -> 'PatternAgent':
        """Build agent from any properly-formatted DataFrame."""
        df = df.copy()
        if 'Date' in df.columns:
            df = df.set_index('Date')
        for col in ['Open','High','Low','Close']:
            assert col in df.columns, f"Missing column: {col}"
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return cls(df=df, name=name)
    
    def scan(self) -> pd.DataFrame:
        """Return rows where any pattern triggered (with pattern names)."""
        df = add_indicators(self.df)
        df = detect_all_patterns(df)
        pat_cols = [c for c in df.columns if c.startswith('pat_')]
        df['active_patterns'] = df[pat_cols].apply(
            lambda r: ', '.join([c.replace('pat_','') + ('+' if v==1 else '-')
                                 for c,v in r.items() if v != 0]),
            axis=1
        )
        return df[df['active_patterns'] != ''][['Open','High','Low','Close','active_patterns']]
    
    def latest_signal(self) -> list[Signal]:
        return latest_signal(self.df)
    
    def backtest_pattern(self, pattern: str, **kwargs) -> BacktestResult:
        df = add_indicators(self.df)
        df = detect_all_patterns(df)
        bias = PATTERN_BIAS[pattern]
        direction = bias if bias != 0 else 1
        return backtest_pattern(df, f'pat_{pattern}', direction, pattern_name=pattern, **kwargs)
    
    def backtest_all_patterns(self, **kwargs) -> pd.DataFrame:
        rows = []
        for name in PATTERNS.keys():
            try:
                r = self.backtest_pattern(name, **kwargs)
                rows.append(r.summary())
            except Exception as e:
                rows.append({'pattern': name, 'error': str(e)})
        df = pd.DataFrame(rows)
        if 'expectancy_R' in df.columns:
            df = df.sort_values('expectancy_R', ascending=False)
        return df
    
    def market_state(self) -> dict:
        df = add_indicators(self.df)
        last = df.iloc[-1]
        return dict(
            date=str(self.df.index[-1].date()),
            close=float(last['Close']),
            atr14=float(last['ATR14']) if np.isfinite(last['ATR14']) else None,
            ema20=float(last['EMA20']),
            ema50=float(last['EMA50']) if np.isfinite(last['EMA50']) else None,
            ema200=float(last['EMA200']) if np.isfinite(last['EMA200']) else None,
            trend=str(last['Trend']),
            body=float(last['Body']),
            range=float(last['Range']),
        )
    
    def resample(self, rule: str) -> 'PatternAgent':
        """Resample to a different timeframe.  rule: '1W', '1M', '4H', etc."""
        df = self.df.resample(rule).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min',
            'Close': 'last', 'Volume': 'sum'
        }).dropna()
        return PatternAgent(df=df, name=f"{self.name}_{rule}")
    
    def multi_timeframe_signals(self, timeframes: list[str] = ['1D', '1W', '1ME']) -> dict:
        """Get latest signals across multiple timeframes (e.g. D/W/M alignment)."""
        out = {}
        for tf in timeframes:
            try:
                a = self if tf == '1D' else self.resample(tf)
                if len(a.df) < 50:  # too few bars after resample
                    out[tf] = {'error': f'insufficient bars ({len(a.df)})'}
                    continue
                sigs = a.latest_signal()
                state = a.market_state()
                out[tf] = dict(
                    bars=len(a.df), state=state,
                    signals=[asdict(s) for s in sigs],
                    last_date=str(a.df.index[-1].date())
                )
            except Exception as e:
                out[tf] = {'error': str(e)}
        return out

# ============================================================================
# 6. CLI
# ============================================================================

def _print_signals(signals: list[Signal]):
    if not signals:
        print("No active patterns on the most recent bar.")
        return
    for s in signals:
        print(f"\n  [{s.pattern.upper()}]  ({s.direction.upper()})")
        print(f"    Date     : {s.date.date()}")
        print(f"    Entry    : {s.entry:.2f}")
        print(f"    Stop     : {s.stop:.2f}  (ATR={s.atr:.2f})")
        print(f"    Target   : {s.target:.2f}  (R:R={s.rr:.1f})")
        print(f"    Confidence: {s.confidence*100:.0f}%")
        if s.notes:
            for n in s.notes:
                print(f"      - {n}")

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='XAU Pattern Trading Agent — candlestick-pattern based gold trading agent.',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest='cmd', required=True)
    
    p_scan = sub.add_parser('scan', help='Scan all bars and list pattern occurrences')
    p_scan.add_argument('csv')
    p_scan.add_argument('--last', type=int, default=20)
    
    p_signal = sub.add_parser('signal', help='Get trade signal for the latest bar')
    p_signal.add_argument('csv')
    
    p_bt = sub.add_parser('backtest', help='Backtest patterns')
    p_bt.add_argument('csv')
    p_bt.add_argument('--pattern', default=None)
    p_bt.add_argument('--risk-atr', type=float, default=1.5)
    p_bt.add_argument('--reward-atr', type=float, default=3.0)
    p_bt.add_argument('--max-bars', type=int, default=10)
    p_bt.add_argument('--json', action='store_true')
    
    p_an = sub.add_parser('analyze', help='Full pattern frequency + market state report')
    p_an.add_argument('csv')
    p_an.add_argument('--json', action='store_true')
    
    p_mtf = sub.add_parser('mtf', help='Multi-timeframe signal alignment (D/W/M)')
    p_mtf.add_argument('csv')
    p_mtf.add_argument('--timeframes', nargs='+', default=['1D','1W','1ME'])
    
    p_size = sub.add_parser('size', help='Position sizing helper for an XAU trade')
    p_size.add_argument('--balance', type=float, required=True, help='account equity in USD')
    p_size.add_argument('--risk-pct', type=float, default=0.01, help='risk per trade (0.01 = 1%%)')
    p_size.add_argument('--entry', type=float, required=True)
    p_size.add_argument('--stop', type=float, required=True)
    p_size.add_argument('--contract', type=float, default=100.0,
                        help='contract size in oz: 100=standard, 10=mini, 1=micro')
    
    args = parser.parse_args(argv)
    
    # 'size' is the only command that doesn't need a CSV
    if args.cmd == 'size':
        result = position_size(args.balance, args.risk_pct, args.entry,
                               args.stop, args.contract)
        print("\n=== POSITION SIZE CALCULATOR (XAU) ===")
        for k, v in result.items():
            print(f"  {k:20s}: {v}")
        return
    
    agent = PatternAgent.from_csv(args.csv)
    print(f"\nXAU PATTERN AGENT — Loaded {len(agent.df)} bars from {args.csv}")
    print(f"Date range: {agent.df.index[0].date()} → {agent.df.index[-1].date()}\n")
    
    if args.cmd == 'scan':
        df = agent.scan()
        print(f"Found {len(df)} bars with active patterns.")
        print(f"\nMost recent {args.last}:")
        print(df.tail(args.last).to_string())
        
    elif args.cmd == 'signal':
        sigs = agent.latest_signal()
        st = agent.market_state()
        print(f"Market state: trend={st['trend']}, close={st['close']:.2f}, ATR14={st['atr14']:.2f}")
        print(f"\n=== ACTIVE SIGNALS ===")
        _print_signals(sigs)
        
    elif args.cmd == 'backtest':
        kwargs = dict(risk_atr_mult=args.risk_atr, reward_atr_mult=args.reward_atr,
                      max_bars=args.max_bars)
        if args.pattern:
            res = agent.backtest_pattern(args.pattern, **kwargs)
            if args.json:
                print(json.dumps(res.summary(), indent=2))
            else:
                s = res.summary()
                print(f"=== Backtest: {args.pattern} ===")
                for k,v in s.items(): print(f"  {k:18s}: {v}")
        else:
            df = agent.backtest_all_patterns(**kwargs)
            if args.json:
                print(df.to_json(orient='records', indent=2))
            else:
                print("=== Backtest: ALL patterns ===")
                print(df.to_string(index=False))
    
    elif args.cmd == 'analyze':
        # Frequency
        df_ind = add_indicators(agent.df)
        df_pat = detect_all_patterns(df_ind)
        freq = {}
        for name in PATTERNS:
            col = df_pat[f'pat_{name}']
            freq[name] = int((col != 0).sum())
        # Backtest
        bt = agent.backtest_all_patterns()
        st = agent.market_state()
        report = dict(
            data=dict(bars=len(agent.df), 
                      start=str(agent.df.index[0].date()),
                      end=str(agent.df.index[-1].date())),
            market_state=st,
            pattern_frequency=freq,
            backtest_top10=bt.head(10).to_dict('records'),
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print("=== MARKET STATE ===")
            for k,v in st.items(): print(f"  {k:10s}: {v}")
            print("\n=== PATTERN FREQUENCY (occurrences) ===")
            for k,v in sorted(freq.items(), key=lambda x: -x[1]):
                if v > 0: print(f"  {k:25s}: {v}")
            print("\n=== BACKTEST RANKING (by expectancy_R) ===")
            print(bt.to_string(index=False))
    
    elif args.cmd == 'mtf':
        result = agent.multi_timeframe_signals(args.timeframes)
        print("=== MULTI-TIMEFRAME SIGNAL ALIGNMENT ===")
        for tf, info in result.items():
            print(f"\n--- Timeframe: {tf} ---")
            if 'error' in info:
                print(f"  {info['error']}")
                continue
            st = info['state']
            print(f"  Last bar: {info['last_date']}  bars: {info['bars']}")
            print(f"  Trend: {st['trend']}  Close: {st['close']:.2f}  ATR14: {st['atr14']:.2f}" if st['atr14'] else f"  Trend: {st['trend']}")
            sigs = info['signals']
            if not sigs:
                print(f"  No active patterns.")
            else:
                for s in sigs:
                    print(f"  >> {s['pattern']} ({s['direction']})  conf={s['confidence']*100:.0f}%  entry={s['entry']:.2f}  SL={s['stop']:.2f}  TP={s['target']:.2f}")

if __name__ == '__main__':
    main()
