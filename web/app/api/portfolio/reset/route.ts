/**
 * POST /api/portfolio/reset
 *
 * Resets trade history. Two modes:
 *   { scope: 'open' }   — close all OPEN trades as MANUAL (no pnl impact)
 *   { scope: 'all' }    — delete EVERYTHING (open + closed). Clean slate.
 *
 * Source flag (default = both):
 *   { source: 'paper' }  — only active_trades (paper sim)
 *   { source: 'real'  }  — only rcs_executions (real broker)
 *   { source: 'both'  }  — paper + real (default; mirror Exness reset)
 *
 * 2026-05-07 fix: previously only touched active_trades. User reported
 * "reset gak reset broker tab" — now also handles rcs_executions when
 * source='both' or 'real'.
 *
 * Auth fallback chain (most permissive first):
 *   1. SUPABASE_SERVICE_ROLE_KEY (best — bypasses RLS)
 *   2. SUPABASE_SUPABASE_KEY (alias)
 *   3. NEXT_PUBLIC_SUPABASE_ANON_KEY (works since project has no RLS on
 *      active_trades — daemon uses same key for inserts)
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime = 'edge'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_KEY =
  process.env.SUPABASE_SERVICE_ROLE_KEY
  || process.env.SUPABASE_SUPABASE_KEY
  || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  || ''
const USER_ID      = 'default'

export async function POST(req: NextRequest) {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json(
      { ok: false, error: 'NEXT_PUBLIC_SUPABASE_URL or SUPABASE_ANON_KEY missing in Vercel env' },
      { status: 500 },
    )
  }

  let body: { scope?: 'open' | 'all'; source?: 'paper' | 'real' | 'both' } = {}
  try {
    body = await req.json()
  } catch {
    body = { scope: 'open' }
  }
  const scope = body.scope === 'all' ? 'all' : 'open'
  const source = body.source === 'paper' ? 'paper' : body.source === 'real' ? 'real' : 'both'

  const headers = {
    'apikey':         SUPABASE_KEY,
    'Authorization':  `Bearer ${SUPABASE_KEY}`,
    'Content-Type':   'application/json',
    'Prefer':         'return=representation',
  } as const

  // Helper: count rows from PostgREST representation array.
  const countRows = (v: unknown): number => Array.isArray(v) ? v.length : 0

  try {
    if (scope === 'all') {
      // Hard delete. Paper: filter by user_id. Real (rcs_executions): no
      // user_id column — delete all rows (safe for single-account demo setup).
      let paperDeleted = 0
      let realDeleted = 0

      if (source === 'paper' || source === 'both') {
        const r = await fetch(
          `${SUPABASE_URL}/rest/v1/active_trades?user_id=eq.${USER_ID}`,
          { method: 'DELETE', headers, cache: 'no-store' },
        )
        if (!r.ok) {
          const text = await r.text()
          return NextResponse.json({ ok: false, error: `delete paper failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
        }
        paperDeleted = countRows(await r.json().catch(() => []))
      }

      if (source === 'real' || source === 'both') {
        // rcs_executions has no user_id; delete via id range (id > 0 = all rows).
        const r = await fetch(
          `${SUPABASE_URL}/rest/v1/rcs_executions?id=gt.0`,
          { method: 'DELETE', headers, cache: 'no-store' },
        )
        if (!r.ok) {
          const text = await r.text()
          return NextResponse.json({ ok: false, error: `delete real failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
        }
        realDeleted = countRows(await r.json().catch(() => []))
      }

      return NextResponse.json({
        ok: true, scope, source,
        deleted: paperDeleted + realDeleted,
        paper_deleted: paperDeleted,
        real_deleted: realDeleted,
      })
    }

    // scope = 'open' — soft close. Paper marks MANUAL; Real marks CLOSED_MANUAL
    // with execution_lot=0 to clear UI without disturbing actual broker (broker
    // close must happen manually in MT5 — this only clears DB state).
    let lastPrice: number | null = null
    try {
      const sigR = await fetch(
        `${SUPABASE_URL}/rest/v1/signal_bundles?select=xau_price&order=timestamp.desc&limit=1`,
        { headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` }, cache: 'no-store' },
      )
      if (sigR.ok) {
        const arr = await sigR.json()
        const v = arr?.[0]?.xau_price
        if (typeof v === 'number') lastPrice = v
      }
    } catch {/* ignore */}

    let paperClosed = 0
    let realClosed = 0

    if (source === 'paper' || source === 'both') {
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
        return NextResponse.json({ ok: false, error: `close paper open failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
      }
      paperClosed = countRows(await r.json().catch(() => []))
    }

    if (source === 'real' || source === 'both') {
      const patch: Record<string, unknown> = {
        status:        'CLOSED_MANUAL',
        close_reason:  'manual_reset',
        closed_at:     new Date().toISOString(),
        pnl_money:     0,
      }
      if (lastPrice !== null) patch.close_price = Math.round(lastPrice * 100) / 100

      const r = await fetch(
        `${SUPABASE_URL}/rest/v1/rcs_executions?status=eq.OPEN`,
        { method: 'PATCH', headers, body: JSON.stringify(patch), cache: 'no-store' },
      )
      if (!r.ok) {
        const text = await r.text()
        return NextResponse.json({ ok: false, error: `close real open failed: HTTP ${r.status} ${text.slice(0, 200)}` }, { status: 500 })
      }
      realClosed = countRows(await r.json().catch(() => []))
    }

    return NextResponse.json({
      ok: true, scope, source,
      closed: paperClosed + realClosed,
      paper_closed: paperClosed,
      real_closed: realClosed,
      exit_price: lastPrice,
    })
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 })
  }
}
