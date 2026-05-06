/**
 * POST /api/portfolio/reset
 *
 * Resets paper-trade history. Two modes:
 *   { scope: 'open' }   — close all OPEN trades as MANUAL (no pnl impact)
 *   { scope: 'all' }    — delete EVERYTHING (open + closed). Clean slate.
 *
 * Used from /portfolio when user wants to start fresh from new code base
 * (e.g. after BEP fix or after switching to Opsi A simplified gate).
 *
 * Service-role key required so we can delete past rows. Anon key won't work.
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime = 'edge'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SERVICE_KEY  = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY || ''
const USER_ID      = 'default'

export async function POST(req: NextRequest) {
  if (!SUPABASE_URL || !SERVICE_KEY) {
    return NextResponse.json(
      { ok: false, error: 'SUPABASE_SERVICE_ROLE_KEY missing in Vercel env' },
      { status: 500 },
    )
  }

  let body: { scope?: 'open' | 'all' } = {}
  try {
    body = await req.json()
  } catch {
    body = { scope: 'open' }
  }
  const scope = body.scope === 'all' ? 'all' : 'open'

  const headers = {
    'apikey':         SERVICE_KEY,
    'Authorization':  `Bearer ${SERVICE_KEY}`,
    'Content-Type':   'application/json',
    'Prefer':         'return=representation',
  } as const

  try {
    if (scope === 'all') {
      // Hard delete every row for this user.
      const r = await fetch(
        `${SUPABASE_URL}/rest/v1/active_trades?user_id=eq.${USER_ID}`,
        { method: 'DELETE', headers, cache: 'no-store' },
      )
      if (!r.ok) {
        const text = await r.text()
        return NextResponse.json({ ok: false, error: `delete all failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
      }
      const rows = await r.json().catch(() => [])
      return NextResponse.json({ ok: true, scope, deleted: Array.isArray(rows) ? rows.length : 0 })
    }

    // scope = 'open' — soft close: mark MANUAL with current xau spot from latest signal bundle
    // (best-effort; if fetching latest fails, exit_price remains null — pnl_r=0).
    let lastPrice: number | null = null
    try {
      const sigR = await fetch(
        `${SUPABASE_URL}/rest/v1/signal_bundles?select=xau_price&order=timestamp.desc&limit=1`,
        { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` }, cache: 'no-store' },
      )
      if (sigR.ok) {
        const arr = await sigR.json()
        const v = arr?.[0]?.xau_price
        if (typeof v === 'number') lastPrice = v
      }
    } catch {/* ignore */}

    const patch: Record<string, unknown> = {
      status:        'MANUAL',
      exit_reason:   'manual_reset',
      closed_at:     new Date().toISOString(),
      pnl_r:         0,
      pnl_pct:       0,
    }
    if (lastPrice !== null) patch.exit_price = Math.round(lastPrice * 100) / 100

    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/active_trades?user_id=eq.${USER_ID}&status=eq.OPEN`,
      { method: 'PATCH', headers, body: JSON.stringify(patch), cache: 'no-store' },
    )
    if (!r.ok) {
      const text = await r.text()
      return NextResponse.json({ ok: false, error: `close open failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
    }
    const rows = await r.json().catch(() => [])
    return NextResponse.json({
      ok: true,
      scope,
      closed: Array.isArray(rows) ? rows.length : 0,
      exit_price: lastPrice,
    })
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 })
  }
}
