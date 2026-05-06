/**
 * POST /api/push/unsubscribe
 *
 * Body: { endpoint: string }
 *
 * Deletes the subscription from Supabase. Frontend also calls
 * pushManager.subscription.unsubscribe() on the browser side.
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_KEY =
  process.env.SUPABASE_SERVICE_ROLE_KEY
  || process.env.SUPABASE_SERVICE_KEY
  || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  || ''

export async function POST(req: NextRequest) {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({ ok: false, error: 'Supabase env missing' }, { status: 500 })
  }
  let body: { endpoint?: string } = {}
  try { body = await req.json() } catch {/* ignore */}
  const endpoint = body.endpoint
  if (!endpoint) {
    return NextResponse.json({ ok: false, error: 'endpoint wajib' }, { status: 400 })
  }

  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/push_subscriptions?endpoint=eq.${encodeURIComponent(endpoint)}`,
    {
      method: 'DELETE',
      headers: {
        'apikey':        SUPABASE_KEY,
        'Authorization': `Bearer ${SUPABASE_KEY}`,
        'Prefer':        'return=representation',
      },
      cache: 'no-store',
    },
  )
  if (!r.ok) {
    const text = await r.text()
    return NextResponse.json({ ok: false, error: `HTTP ${r.status}: ${text.slice(0, 200)}` }, { status: 500 })
  }
  const rows = await r.json().catch(() => [])
  return NextResponse.json({ ok: true, deleted: Array.isArray(rows) ? rows.length : 0 })
}
