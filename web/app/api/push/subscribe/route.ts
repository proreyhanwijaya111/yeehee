/**
 * POST /api/push/subscribe
 *
 * Body: PushSubscription JSON from serviceWorker.pushManager.subscribe()
 *   {
 *     endpoint: "https://fcm.googleapis.com/...",
 *     keys: { p256dh: "...", auth: "..." }
 *   }
 *
 * Stores the subscription in Supabase push_subscriptions so the daemon can
 * later post web push messages to this endpoint.
 *
 * Idempotent: same endpoint UPSERTs (re-subscribing on different browser
 * sessions just refreshes the keys + last_used_at).
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

interface PushSubscriptionPayload {
  endpoint?: string
  keys?: { p256dh?: string; auth?: string }
  label?: string
}

export async function POST(req: NextRequest) {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({ ok: false, error: 'Supabase env missing' }, { status: 500 })
  }

  let body: PushSubscriptionPayload = {}
  try { body = await req.json() } catch {/* ignore */}

  const endpoint = body.endpoint
  const p256dh   = body.keys?.p256dh
  const auth     = body.keys?.auth
  const label    = body.label

  if (!endpoint || !p256dh || !auth) {
    return NextResponse.json({ ok: false, error: 'endpoint, keys.p256dh, keys.auth wajib' }, { status: 400 })
  }

  const userAgent = req.headers.get('user-agent') || null

  const r = await fetch(`${SUPABASE_URL}/rest/v1/push_subscriptions?on_conflict=endpoint`, {
    method: 'POST',
    headers: {
      'apikey':         SUPABASE_KEY,
      'Authorization':  `Bearer ${SUPABASE_KEY}`,
      'Content-Type':   'application/json',
      'Prefer':         'resolution=merge-duplicates,return=representation',
    },
    body: JSON.stringify({
      user_id:      'default',
      endpoint,
      p256dh,
      auth,
      user_agent:   userAgent,
      label:        label || null,
      last_used_at: new Date().toISOString(),
      last_error:   null,
    }),
    cache: 'no-store',
  })

  if (!r.ok) {
    const text = await r.text()
    return NextResponse.json({ ok: false, error: `Supabase HTTP ${r.status}: ${text.slice(0, 200)}` }, { status: 500 })
  }

  const rows = await r.json().catch(() => [])
  return NextResponse.json({ ok: true, subscription: Array.isArray(rows) ? rows[0] : rows })
}
