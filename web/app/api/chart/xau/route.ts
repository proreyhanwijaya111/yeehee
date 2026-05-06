/**
 * GET /api/chart/xau?from=ISO&to=ISO&interval=5m
 *
 * Proxy ke Yahoo Finance v8 chart endpoint untuk dapat OHLC bars XAU/USD.
 * Dipake portfolio page buat draw line chart per trade — entry/SL/TP/exit
 * markers + actual price action between opened_at..closed_at.
 *
 * Yahoo punya tinggi limit + free, gak butuh API key.
 *
 * Symbol fallback chain (kalau primary 404 / no data):
 *   1. XAUUSD=X (spot FX format) — tracks real spot, sometimes 404 di Vercel edge
 *   2. GC=F     (gold futures) — always available, slight basis vs spot
 *   3. GLD      (gold ETF) — last resort, daily close only
 *
 * Cache 60 detik — chart per trade gak perlu real-time candle.
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

// Map our friendly intervals → Yahoo intervals (yahoo allows: 1m,2m,5m,15m,30m,60m,90m,1h,1d)
const ALLOWED_INTERVALS = new Set(['1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d'])

// Symbol fallback chain — try in order until one returns valid bars
const SYMBOL_FALLBACKS = ['XAUUSD=X', 'GC=F', 'GLD']

interface YahooChart {
  chart: {
    result?: Array<{
      timestamp?: number[]
      indicators: {
        quote?: Array<{
          open?:   (number | null)[]
          high?:   (number | null)[]
          low?:    (number | null)[]
          close?:  (number | null)[]
        }>
      }
    }>
    error?: { code: string; description: string } | null
  }
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const fromIso = searchParams.get('from')
  const toIso   = searchParams.get('to')
  const interval = (searchParams.get('interval') || '5m').toLowerCase()
  const symbolOverride = searchParams.get('symbol')

  if (!fromIso || !toIso) {
    return NextResponse.json({ ok: false, error: 'from and to ISO timestamps required' }, { status: 400 })
  }
  if (!ALLOWED_INTERVALS.has(interval)) {
    return NextResponse.json({ ok: false, error: `interval must be one of ${[...ALLOWED_INTERVALS].join(',')}` }, { status: 400 })
  }

  const fromMs = new Date(fromIso).getTime()
  const toMs   = new Date(toIso).getTime()
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs) || toMs <= fromMs) {
    return NextResponse.json({ ok: false, error: 'invalid timestamps' }, { status: 400 })
  }

  // Pad +/-30 min so the trade entry/exit aren't on the very edge of the chart
  const padMs = 30 * 60 * 1000
  const period1 = Math.floor((fromMs - padMs) / 1000)
  const period2 = Math.ceil((toMs + padMs) / 1000)

  const symbolList = symbolOverride ? [symbolOverride] : SYMBOL_FALLBACKS
  const errors: string[] = []

  for (const sym of symbolList) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?period1=${period1}&period2=${period2}&interval=${interval}`
    try {
      const r = await fetch(url, {
        headers: {
          // Yahoo blocks default fetch UA + needs realistic browser headers
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Accept':          'application/json',
          'Accept-Language': 'en-US,en;q=0.9',
        },
        next: { revalidate: 60 },
      })
      if (!r.ok) {
        errors.push(`${sym}: HTTP ${r.status}`)
        continue
      }
      const data = (await r.json()) as YahooChart
      if (data.chart.error) {
        errors.push(`${sym}: ${data.chart.error.description}`)
        continue
      }
      const result = data.chart.result?.[0]
      if (!result || !result.timestamp || !result.indicators.quote?.[0]) {
        errors.push(`${sym}: no data`)
        continue
      }
      const ts   = result.timestamp
      const q    = result.indicators.quote[0]
      const bars = ts.map((t, i) => ({
        t: t * 1000,                                       // ms
        o: q.open?.[i]  ?? null,
        h: q.high?.[i]  ?? null,
        l: q.low?.[i]   ?? null,
        c: q.close?.[i] ?? null,
      })).filter(b => b.c !== null)

      if (bars.length === 0) {
        errors.push(`${sym}: empty bars`)
        continue
      }

      return NextResponse.json({ ok: true, symbol: sym, interval, bars }, {
        headers: { 'Cache-Control': 'public, max-age=60, s-maxage=60' },
      })
    } catch (e) {
      errors.push(`${sym}: ${String(e).slice(0, 60)}`)
    }
  }

  return NextResponse.json({
    ok: false,
    error: `all symbols failed: ${errors.join(' | ')}`,
    bars: [],
  }, { status: 502 })
}
