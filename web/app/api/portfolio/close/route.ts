/**
 * POST /api/portfolio/close
 *
 * Body: { trade_id: string, exit_price?: number }
 *
 * Manually close ONE active OPEN trade. User-initiated (e.g. from /portfolio
 * "Tutup manual" button). Auto-managed trades (TP/SL/trailing/expiry) handled
 * by daemon trade_tracker — this is the manual override only.
 *
 * exit_price defaults to latest signal_bundles.xau_price if not provided.
 * pnl_r is computed using original_sl distance (R-unit consistent with
 * auto-closed trades).
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime = 'edge'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_KEY =
  process.env.SUPABASE_SERVICE_ROLE_KEY
  || process.env.SUPABASE_SERVICE_KEY
  || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  || ''

interface TradeRow {
  id: string
  side: 'LONG' | 'SHORT'
  entry: number
  sl: number
  original_sl: number | null
  status: string
}

export async function POST(req: NextRequest) {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({ ok: false, error: 'Supabase env missing' }, { status: 500 })
  }

  let body: { trade_id?: string; exit_price?: number } = {}
  try { body = await req.json() } catch {/* ignore */}

  const tradeId = body.trade_id?.trim()
  if (!tradeId) {
    return NextResponse.json({ ok: false, error: 'trade_id wajib' }, { status: 400 })
  }

  // 1. Fetch the trade
  const headers = {
    'apikey':        SUPABASE_KEY,
    'Authorization': `Bearer ${SUPABASE_KEY}`,
    'Content-Type':  'application/json',
    'Prefer':        'return=representation',
  } as const

  const r1 = await fetch(
    `${SUPABASE_URL}/rest/v1/active_trades?id=eq.${encodeURIComponent(tradeId)}&select=id,side,entry,sl,original_sl,status&limit=1`,
    { headers, cache: 'no-store' },
  )
  if (!r1.ok) {
    return NextResponse.json({ ok: false, error: `fetch trade failed: HTTP ${r1.status}` }, { status: 500 })
  }
  const rows: TradeRow[] = await r1.json().catch(() => [])
  if (rows.length === 0) {
    return NextResponse.json({ ok: false, error: 'Trade tidak ditemukan' }, { status: 404 })
  }
  const trade = rows[0]
  if (trade.status !== 'OPEN') {
    return NextResponse.json({ ok: false, error: `Trade sudah ${trade.status}` }, { status: 409 })
  }

  // 2. Resolve exit price (param > latest spot)
  let exitPrice = typeof body.exit_price === 'number' ? body.exit_price : null
  if (exitPrice === null) {
    try {
      const r2 = await fetch(
        `${SUPABASE_URL}/rest/v1/signal_bundles?select=xau_price&order=created_at.desc&limit=1`,
        { headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` }, cache: 'no-store' },
      )
      if (r2.ok) {
        const arr = await r2.json()
        const v = arr?.[0]?.xau_price
        if (typeof v === 'number') exitPrice = v
      }
    } catch {/* ignore */}
  }
  if (exitPrice === null) {
    return NextResponse.json({ ok: false, error: 'Exit price tidak tersedia. Coba lagi atau kirim exit_price di body.' }, { status: 503 })
  }

  // 3. Compute pnl_r using original_sl distance
  const entry  = Number(trade.entry)
  const origSL = trade.original_sl !== null ? Number(trade.original_sl) : Number(trade.sl)
  const slDist = Math.abs(entry - origSL)
  const realised = trade.side === 'LONG' ? (exitPrice - entry) : (entry - exitPrice)
  const pnl_r   = slDist > 0 ? Math.round((realised / slDist) * 1000) / 1000 : 0
  const pnl_pct = Math.round((realised / entry) * 1e4) / 100

  // 4. Patch the trade
  const patch = {
    status:      'MANUAL',
    exit_reason: 'manual_close',
    closed_at:   new Date().toISOString(),
    exit_price:  Math.round(exitPrice * 100) / 100,
    pnl_r,
    pnl_pct,
  }

  const r3 = await fetch(
    `${SUPABASE_URL}/rest/v1/active_trades?id=eq.${encodeURIComponent(tradeId)}`,
    { method: 'PATCH', headers, body: JSON.stringify(patch), cache: 'no-store' },
  )
  if (!r3.ok) {
    const text = await r3.text()
    return NextResponse.json({ ok: false, error: `patch failed: HTTP ${r3.status}: ${text.slice(0, 200)}` }, { status: 500 })
  }

  return NextResponse.json({
    ok: true,
    trade_id: tradeId,
    exit_price: patch.exit_price,
    pnl_r,
    pnl_pct,
  })
}
