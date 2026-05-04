/**
 * POST /api/backtest
 *
 * Monte Carlo simulation of equity outcomes given:
 *   - starting_equity, risk_per_trade, n_runs
 *   - win_rate, avg_win_r, avg_loss_r, n_trades
 *
 * Bootstrap method (port of backtest/monte_carlo.py):
 *   - Sample trade R-multiples from a distribution (Bernoulli outcome × R-magnitude)
 *   - Compound equity per path: equity[t+1] = equity[t] * (1 + risk * R)
 *   - Aggregate percentiles + probabilities across runs
 *
 * Edge runtime — no Node deps, fast.
 */
import { NextResponse } from 'next/server'

export const runtime = 'edge'
export const dynamic = 'force-dynamic'

interface BacktestRequest {
  starting_equity?: number
  risk_per_trade?:  number   // 0..1, e.g. 0.01 for 1%
  n_runs?:          number   // monte carlo iterations
  n_trades?:        number   // trades per simulated path
  win_rate?:        number   // 0..1
  avg_win_r?:       number   // R-multiple for winners (e.g. 1.5)
  avg_loss_r?:      number   // R-multiple for losers (e.g. -1.0, will be made negative)
  blowup_dd_pct?:   number   // DD % considered "blow up" (e.g. 0.5)
}

interface MCResult {
  inputs: Required<BacktestRequest>
  percentiles: {
    final_equity:  { p5: number; p25: number; p50: number; p75: number; p95: number }
    max_drawdown:  { p5: number; p50: number; p95: number }
  }
  probabilities: {
    profit:        number
    drawdown_30:   number
    drawdown_50:   number
    blowup:        number
  }
  expected_return_pct: number
  expectancy_r: number
  n_runs: number
  duration_ms: number
}

export async function POST(req: Request) {
  const t0 = performance.now()
  let body: BacktestRequest
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'invalid JSON' }, { status: 400 })
  }

  // Defaults
  const inputs: Required<BacktestRequest> = {
    starting_equity: clamp(body.starting_equity ?? 10000, 1, 1_000_000_000),
    risk_per_trade:  clamp(body.risk_per_trade  ?? 0.01,  0.0001, 0.10),
    n_runs:          clamp(Math.floor(body.n_runs ?? 5000), 100, 50000),
    n_trades:        clamp(Math.floor(body.n_trades ?? 100), 10, 1000),
    win_rate:        clamp(body.win_rate ?? 0.5,  0.01, 0.99),
    avg_win_r:       clamp(body.avg_win_r ?? 1.5, 0.1, 10),
    avg_loss_r:      Math.min(0, body.avg_loss_r ?? -1) || -1,
    blowup_dd_pct:   clamp(body.blowup_dd_pct ?? 0.5, 0.1, 0.99),
  }

  const finals: number[] = new Array(inputs.n_runs)
  const maxDDs: number[] = new Array(inputs.n_runs)
  let nProfit = 0
  let nBlowup = 0
  let nDD30   = 0
  let nDD50   = 0

  // Expectancy in R-multiples (sanity)
  const expectancy_r = inputs.win_rate * inputs.avg_win_r + (1 - inputs.win_rate) * inputs.avg_loss_r

  for (let run = 0; run < inputs.n_runs; run++) {
    let equity = inputs.starting_equity
    let peak   = equity
    let maxDD  = 0
    for (let t = 0; t < inputs.n_trades; t++) {
      const win = Math.random() < inputs.win_rate
      // Sample R from distribution. Use ±20% noise around avg_win_r/avg_loss_r for variance.
      const noise = (Math.random() - 0.5) * 0.4   // -0.2..+0.2
      const r = win
        ? inputs.avg_win_r * (1 + noise)
        : inputs.avg_loss_r * (1 + noise)
      equity = equity * (1 + inputs.risk_per_trade * r)
      if (equity <= 0) { equity = 0; break }
      if (equity > peak) peak = equity
      const dd = (equity - peak) / peak
      if (dd < maxDD) maxDD = dd
    }
    finals[run] = equity
    maxDDs[run] = maxDD
    if (equity > inputs.starting_equity) nProfit++
    if (maxDD <= -inputs.blowup_dd_pct) nBlowup++
    if (maxDD <= -0.30) nDD30++
    if (maxDD <= -0.50) nDD50++
  }

  finals.sort((a, b) => a - b)
  maxDDs.sort((a, b) => a - b)

  const result: MCResult = {
    inputs,
    percentiles: {
      final_equity: {
        p5:  pct(finals, 0.05),
        p25: pct(finals, 0.25),
        p50: pct(finals, 0.50),
        p75: pct(finals, 0.75),
        p95: pct(finals, 0.95),
      },
      max_drawdown: {
        p5:  pct(maxDDs, 0.05) * 100,   // worst-case (most negative)
        p50: pct(maxDDs, 0.50) * 100,
        p95: pct(maxDDs, 0.95) * 100,
      },
    },
    probabilities: {
      profit:      nProfit / inputs.n_runs,
      drawdown_30: nDD30   / inputs.n_runs,
      drawdown_50: nDD50   / inputs.n_runs,
      blowup:      nBlowup / inputs.n_runs,
    },
    expected_return_pct: ((mean(finals) / inputs.starting_equity) - 1) * 100,
    expectancy_r,
    n_runs: inputs.n_runs,
    duration_ms: Math.round(performance.now() - t0),
  }

  return NextResponse.json(result, {
    headers: { 'Cache-Control': 'no-store' },
  })
}

function clamp(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return lo
  return Math.max(lo, Math.min(hi, v))
}

function mean(arr: number[]): number {
  let s = 0
  for (const v of arr) s += v
  return s / arr.length
}

function pct(sorted: number[], p: number): number {
  const idx = Math.floor(p * (sorted.length - 1))
  return sorted[idx]
}
