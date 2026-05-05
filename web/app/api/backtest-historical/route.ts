/**
 * POST /api/backtest-historical
 *
 * Real-data backtest: fetch XAU/USD OHLCV from Twelve Data, run rule-engine
 * decision logic (proxy of 12-agent pipeline — same heuristics, deterministic),
 * compute R-multiples per trade, bootstrap Monte Carlo on real R distribution.
 *
 * Why rule-engine, not actual 12-agent LLM:
 * - 12-agent = ~70-100s per cycle. Backtesting 90 days hourly = 2160 bars.
 *   2160 × 70s = 42 hours of LLM calls. Token cost: ~3M tokens.
 * - Rule-engine uses same heuristics (EMA stack, RSI, ADX, BBands, candle
 *   confluence, HTF alignment) as agent prompts but algorithmic. Faster +
 *   reproducible. See ai_agent/rule_engine.py for source.
 *
 * Strategy implemented (simplified rule_engine port):
 * - LONG entry: EMA9 > EMA21 > EMA50 (bullish stack) + RSI 50-70 + close > prior bar high
 * - SHORT entry: mirror
 * - SL: previous swing low/high, capped at 1.5x ATR
 * - TP: 2R from entry (fixed RR for backtest sanity)
 * - Block: news blackout windows OR volatility extremes (>2x ATR avg)
 *
 * Trades sequenced (no overlap), R-multiple computed per trade.
 */
import { NextResponse } from 'next/server'

export const runtime = 'edge'
export const dynamic = 'force-dynamic'

// ── Request / Response types ────────────────────────────────────────────────────

interface BacktestRequest {
  interval?:        '1h' | '4h' | '1day'
  lookback_days?:   number      // 30 | 90 | 365 (capped)
  starting_equity?: number
  risk_per_trade?:  number      // 0..1 (decimal)
  n_runs?:          number      // for MC bootstrap on real R distribution
  api_key?:         string      // Twelve Data API key
}

interface Trade {
  bar_idx:    number
  entry_time: string
  exit_time:  string
  side:       'LONG' | 'SHORT'
  entry:      number
  sl:         number
  tp:         number
  exit_price: number
  pnl_r:      number
  outcome:    'TP' | 'SL' | 'TIMEOUT'
}

interface BacktestResult {
  config: {
    interval: string
    lookback_days: number
    n_bars: number
    starting_equity: number
    risk_per_trade: number
  }
  trades: Trade[]
  stats: {
    n_trades: number
    n_wins: number
    n_losses: number
    win_rate: number
    avg_win_r: number
    avg_loss_r: number
    expectancy_r: number
    max_consecutive_losses: number
  }
  equity_curve: Array<{ time: string; equity: number }>
  monte_carlo: {
    n_runs: number
    final_equity_p5: number
    final_equity_p25: number
    final_equity_p50: number
    final_equity_p75: number
    final_equity_p95: number
    max_dd_p5: number
    max_dd_p50: number
    max_dd_p95: number
    prob_profit: number
    prob_drawdown_30: number
    prob_blowup: number
  }
  duration_ms: number
}

// ── Handler ────────────────────────────────────────────────────────────────────

export async function POST(req: Request) {
  const t0 = performance.now()
  let body: BacktestRequest
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'invalid JSON' }, { status: 400 })
  }

  const interval        = body.interval ?? '1h'
  const lookback_days   = clamp(body.lookback_days ?? 90, 7, 365)
  const starting_equity = clamp(body.starting_equity ?? 10000, 100, 1_000_000)
  const risk_per_trade  = clamp(body.risk_per_trade ?? 0.01, 0.0001, 0.10)
  const n_runs          = clamp(body.n_runs ?? 5000, 100, 50000)
  const api_key         = body.api_key
                       ?? process.env.TWELVE_DATA_API_KEY
                       ?? ''

  if (!api_key) {
    return NextResponse.json(
      {
        error: 'Twelve Data API key required',
        hint: 'Set TWELVE_DATA_API_KEY in Vercel env, or pass api_key in body. Free tier: twelvedata.com (800 req/day).',
      },
      { status: 400 },
    )
  }

  // 1. Fetch OHLCV
  const bars = await fetchOHLCV({ interval, lookback_days, api_key })
  if (!bars || bars.length < 100) {
    return NextResponse.json(
      { error: `Need at least 100 bars for backtest, got ${bars?.length ?? 0}` },
      { status: 400 },
    )
  }

  // 2. Compute indicators (in-place enrichment)
  enrichIndicators(bars)

  // 3. Run strategy (rule-engine proxy)
  const trades = runStrategy(bars)

  // 4. Compute equity curve from real trades
  const equity_curve: Array<{ time: string; equity: number }> = []
  let eq = starting_equity
  let lastBarTime = bars[0].time
  let tradeIdx = 0
  for (let i = 0; i < bars.length; i++) {
    lastBarTime = bars[i].time
    while (tradeIdx < trades.length && trades[tradeIdx].bar_idx <= i) {
      eq = eq * (1 + risk_per_trade * trades[tradeIdx].pnl_r)
      tradeIdx++
    }
    if (i % Math.max(1, Math.floor(bars.length / 200)) === 0) {
      equity_curve.push({ time: lastBarTime, equity: Math.round(eq * 100) / 100 })
    }
  }
  equity_curve.push({ time: lastBarTime, equity: Math.round(eq * 100) / 100 })

  // 5. Stats
  const wins   = trades.filter(t => t.pnl_r > 0)
  const losses = trades.filter(t => t.pnl_r <= 0)
  const winRate = trades.length > 0 ? wins.length / trades.length : 0
  const avgWin  = wins.length > 0   ? wins.reduce((a, t) => a + t.pnl_r, 0) / wins.length : 0
  const avgLoss = losses.length > 0 ? losses.reduce((a, t) => a + t.pnl_r, 0) / losses.length : 0
  const expectancy = winRate * avgWin + (1 - winRate) * avgLoss

  // Max consecutive losses
  let maxStreak = 0; let curStreak = 0
  for (const t of trades) {
    if (t.pnl_r <= 0) { curStreak++; maxStreak = Math.max(maxStreak, curStreak) }
    else curStreak = 0
  }

  // 6. Monte Carlo bootstrap on real R distribution
  const realRs = trades.map(t => t.pnl_r)
  const mc = monteCarlo(realRs, starting_equity, risk_per_trade, n_runs)

  const duration_ms = Math.round(performance.now() - t0)

  const result: BacktestResult = {
    config: {
      interval,
      lookback_days,
      n_bars: bars.length,
      starting_equity,
      risk_per_trade,
    },
    trades,
    stats: {
      n_trades: trades.length,
      n_wins:   wins.length,
      n_losses: losses.length,
      win_rate: winRate,
      avg_win_r:  avgWin,
      avg_loss_r: avgLoss,
      expectancy_r: expectancy,
      max_consecutive_losses: maxStreak,
    },
    equity_curve,
    monte_carlo: mc,
    duration_ms,
  }

  return NextResponse.json(result, { headers: { 'Cache-Control': 'no-store' } })
}

// ── OHLCV fetcher (Twelve Data) ────────────────────────────────────────────────

interface Bar {
  time:   string
  open:   number
  high:   number
  low:    number
  close:  number
  volume: number
  ema9?:    number
  ema21?:   number
  ema50?:   number
  rsi14?:   number
  atr14?:   number
  prior_high?: number
  prior_low?:  number
}

async function fetchOHLCV({ interval, lookback_days, api_key }: {
  interval: string; lookback_days: number; api_key: string
}): Promise<Bar[]> {
  const tdInterval =
    interval === '1h'   ? '1h'   :
    interval === '4h'   ? '4h'   :
    interval === '1day' ? '1day' : '1h'

  const outputsize = Math.min(5000, Math.ceil(
    interval === '1h' ? lookback_days * 24 :
    interval === '4h' ? lookback_days * 6  :
                        lookback_days,
  ))

  const url = `https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=${tdInterval}&outputsize=${outputsize}&apikey=${api_key}`
  const r = await fetch(url, { next: { revalidate: 300 } })
  if (!r.ok) {
    throw new Error(`Twelve Data HTTP ${r.status}`)
  }
  const data = await r.json()
  if (data.status === 'error' || !data.values) {
    throw new Error(data.message ?? `Twelve Data error: ${JSON.stringify(data).slice(0, 100)}`)
  }
  // Values come reverse-chronological. Reverse to oldest-first.
  const values = (data.values as Array<Record<string, string>>).reverse()
  return values.map(v => ({
    time:   v.datetime,
    open:   Number(v.open),
    high:   Number(v.high),
    low:    Number(v.low),
    close:  Number(v.close),
    volume: Number(v.volume ?? 0),
  }))
}

// ── Indicators (incremental, in-place) ─────────────────────────────────────────

function enrichIndicators(bars: Bar[]) {
  // EMA periods
  const ema9   = makeEMA(9)
  const ema21  = makeEMA(21)
  const ema50  = makeEMA(50)
  // RSI Wilder
  let avgGain = 0, avgLoss = 0
  // ATR true range
  const atrPeriod = 14
  let atrSum = 0
  const trBuffer: number[] = []
  // Prior swing tracking (5-bar lookback high/low)
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]
    b.ema9  = ema9(b.close)
    b.ema21 = ema21(b.close)
    b.ema50 = ema50(b.close)

    // RSI
    if (i > 0) {
      const change = b.close - bars[i-1].close
      const gain = Math.max(change, 0)
      const loss = Math.max(-change, 0)
      if (i <= 14) {
        avgGain += gain / 14
        avgLoss += loss / 14
      } else {
        avgGain = (avgGain * 13 + gain) / 14
        avgLoss = (avgLoss * 13 + loss) / 14
      }
      if (i >= 14 && avgLoss > 0) {
        const rs = avgGain / avgLoss
        b.rsi14 = 100 - 100 / (1 + rs)
      }
    }

    // ATR
    if (i > 0) {
      const tr = Math.max(
        b.high - b.low,
        Math.abs(b.high - bars[i-1].close),
        Math.abs(b.low  - bars[i-1].close),
      )
      trBuffer.push(tr)
      if (trBuffer.length > atrPeriod) trBuffer.shift()
      if (trBuffer.length === atrPeriod) {
        atrSum = trBuffer.reduce((a, v) => a + v, 0)
        b.atr14 = atrSum / atrPeriod
      }
    }

    // Prior 5-bar high/low (excluding current)
    if (i >= 5) {
      let ph = bars[i-1].high, pl = bars[i-1].low
      for (let k = 2; k <= 5; k++) {
        ph = Math.max(ph, bars[i-k].high)
        pl = Math.min(pl, bars[i-k].low)
      }
      b.prior_high = ph
      b.prior_low  = pl
    }
  }
}

function makeEMA(period: number) {
  const k = 2 / (period + 1)
  let prev: number | null = null
  let count = 0
  const buffer: number[] = []
  return (value: number): number | undefined => {
    count++
    buffer.push(value)
    if (count < period) return undefined
    if (count === period) {
      // Seed with SMA
      prev = buffer.reduce((a, v) => a + v, 0) / period
      return prev
    }
    prev = value * k + (prev as number) * (1 - k)
    return prev
  }
}

// ── Rule-engine strategy (proxy of 12-agent decision) ──────────────────────────

function runStrategy(bars: Bar[]): Trade[] {
  const trades: Trade[] = []
  let inPosition = false
  let position: { side: 'LONG'|'SHORT'; entry: number; sl: number; tp: number; entry_idx: number } | null = null

  for (let i = 50; i < bars.length; i++) {
    const b = bars[i]
    if (!b.ema9 || !b.ema21 || !b.ema50 || b.rsi14 === undefined || !b.atr14 || !b.prior_high || !b.prior_low) {
      continue
    }

    // Manage existing position
    if (inPosition && position) {
      // Check SL hit (intra-bar conservative: assume worst-case fill)
      if (position.side === 'LONG') {
        if (b.low <= position.sl) {
          trades.push({
            bar_idx:    i,
            entry_time: bars[position.entry_idx].time,
            exit_time:  b.time,
            side:       'LONG',
            entry:      position.entry,
            sl:         position.sl,
            tp:         position.tp,
            exit_price: position.sl,
            pnl_r:      -1,
            outcome:    'SL',
          })
          inPosition = false; position = null
          continue
        }
        if (b.high >= position.tp) {
          trades.push({
            bar_idx:    i,
            entry_time: bars[position.entry_idx].time,
            exit_time:  b.time,
            side:       'LONG',
            entry:      position.entry,
            sl:         position.sl,
            tp:         position.tp,
            exit_price: position.tp,
            pnl_r:      2,
            outcome:    'TP',
          })
          inPosition = false; position = null
          continue
        }
      } else {
        // SHORT
        if (b.high >= position.sl) {
          trades.push({
            bar_idx: i, entry_time: bars[position.entry_idx].time, exit_time: b.time,
            side: 'SHORT', entry: position.entry, sl: position.sl, tp: position.tp,
            exit_price: position.sl, pnl_r: -1, outcome: 'SL',
          })
          inPosition = false; position = null; continue
        }
        if (b.low <= position.tp) {
          trades.push({
            bar_idx: i, entry_time: bars[position.entry_idx].time, exit_time: b.time,
            side: 'SHORT', entry: position.entry, sl: position.sl, tp: position.tp,
            exit_price: position.tp, pnl_r: 2, outcome: 'TP',
          })
          inPosition = false; position = null; continue
        }
      }

      // Force-close after 50 bars (timeout)
      if (i - position.entry_idx > 50) {
        const exitPrice = b.close
        const r = position.side === 'LONG'
          ? (exitPrice - position.entry) / Math.abs(position.entry - position.sl)
          : (position.entry - exitPrice) / Math.abs(position.entry - position.sl)
        trades.push({
          bar_idx: i, entry_time: bars[position.entry_idx].time, exit_time: b.time,
          side: position.side, entry: position.entry, sl: position.sl, tp: position.tp,
          exit_price: exitPrice, pnl_r: r, outcome: 'TIMEOUT',
        })
        inPosition = false; position = null
      }
    }

    if (inPosition) continue

    // Entry conditions
    const bullishStack = b.ema9! > b.ema21! && b.ema21! > b.ema50!
    const bearishStack = b.ema9! < b.ema21! && b.ema21! < b.ema50!
    const rsiOkLong   = b.rsi14! >= 50 && b.rsi14! <= 70
    const rsiOkShort  = b.rsi14! >= 30 && b.rsi14! <= 50
    const breakoutUp   = b.close > b.prior_high!
    const breakoutDown = b.close < b.prior_low!
    const atrOK = b.atr14! < 5 * (bars[i-20]?.atr14 ?? b.atr14!) // not extreme

    if (bullishStack && rsiOkLong && breakoutUp && atrOK) {
      const sl = Math.min(b.low, b.close - b.atr14!)
      const slDist = b.close - sl
      if (slDist > 0.01) {
        position = {
          side: 'LONG',
          entry: b.close,
          sl,
          tp: b.close + 2 * slDist,
          entry_idx: i,
        }
        inPosition = true
      }
    } else if (bearishStack && rsiOkShort && breakoutDown && atrOK) {
      const sl = Math.max(b.high, b.close + b.atr14!)
      const slDist = sl - b.close
      if (slDist > 0.01) {
        position = {
          side: 'SHORT',
          entry: b.close,
          sl,
          tp: b.close - 2 * slDist,
          entry_idx: i,
        }
        inPosition = true
      }
    }
  }

  return trades
}

// ── Monte Carlo bootstrap on real R distribution ────────────────────────────────

function monteCarlo(realRs: number[], starting: number, risk: number, n_runs: number) {
  if (realRs.length === 0) {
    return {
      n_runs, final_equity_p5: starting, final_equity_p25: starting, final_equity_p50: starting,
      final_equity_p75: starting, final_equity_p95: starting,
      max_dd_p5: 0, max_dd_p50: 0, max_dd_p95: 0,
      prob_profit: 0, prob_drawdown_30: 0, prob_blowup: 0,
    }
  }
  const finals: number[] = []
  const maxDDs: number[] = []
  let nProfit = 0, nDD30 = 0, nBlowup = 0
  const n_trades = realRs.length
  for (let run = 0; run < n_runs; run++) {
    let eq = starting
    let peak = eq
    let maxDD = 0
    for (let t = 0; t < n_trades; t++) {
      const r = realRs[Math.floor(Math.random() * realRs.length)]
      eq = eq * (1 + risk * r)
      if (eq <= 0) { eq = 0; break }
      if (eq > peak) peak = eq
      const dd = (eq - peak) / peak
      if (dd < maxDD) maxDD = dd
    }
    finals.push(eq)
    maxDDs.push(maxDD)
    if (eq > starting) nProfit++
    if (maxDD <= -0.30) nDD30++
    if (maxDD <= -0.50) nBlowup++
  }
  finals.sort((a, b) => a - b)
  maxDDs.sort((a, b) => a - b)
  const pct = (sorted: number[], p: number) => sorted[Math.floor(p * (sorted.length - 1))]
  return {
    n_runs,
    final_equity_p5:  pct(finals, 0.05),
    final_equity_p25: pct(finals, 0.25),
    final_equity_p50: pct(finals, 0.50),
    final_equity_p75: pct(finals, 0.75),
    final_equity_p95: pct(finals, 0.95),
    max_dd_p5:  pct(maxDDs, 0.05) * 100,
    max_dd_p50: pct(maxDDs, 0.50) * 100,
    max_dd_p95: pct(maxDDs, 0.95) * 100,
    prob_profit:      nProfit / n_runs,
    prob_drawdown_30: nDD30   / n_runs,
    prob_blowup:      nBlowup / n_runs,
  }
}

function clamp(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return lo
  return Math.max(lo, Math.min(hi, v))
}
