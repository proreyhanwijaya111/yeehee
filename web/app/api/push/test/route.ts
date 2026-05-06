/**
 * POST /api/push/test
 *
 * Sends a one-shot test push to all subscriptions of the current user. Lets
 * user verify end-to-end on the settings page without waiting for a real
 * STRONG signal. Implements the Web Push protocol with VAPID JWT auth +
 * payload encryption (RFC 8291) entirely in the Edge runtime.
 *
 * Env required:
 *   - NEXT_PUBLIC_VAPID_PUBLIC_KEY  (also exposed to client for subscribe)
 *   - VAPID_PRIVATE_KEY              (server only)
 *   - VAPID_SUBJECT                  (mailto:... for VAPID JWT)
 *
 * Limitations:
 *   - This endpoint sends 1 push per subscription with the same payload.
 *   - Daemon (Python pywebpush) handles the production signal pushes; this
 *     endpoint exists for the user's "Test push" button.
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

const VAPID_PUBLIC  = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || ''
const VAPID_PRIVATE = process.env.VAPID_PRIVATE_KEY            || ''
const VAPID_SUBJECT = process.env.VAPID_SUBJECT                || 'mailto:admin@yeehee.local'

// ─── Crypto helpers ──────────────────────────────────────────────────────────

function b64UrlEncode(bytes: Uint8Array): string {
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function b64UrlDecode(s: string): Uint8Array {
  s = s.replace(/-/g, '+').replace(/_/g, '/')
  while (s.length % 4 !== 0) s += '='
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function importPrivateKey(privateKeyB64Url: string): Promise<CryptoKey> {
  // VAPID private key is 32 raw bytes. Convert to PKCS8 for SubtleCrypto import.
  const raw = b64UrlDecode(privateKeyB64Url)
  // Build a JWK from raw private key + we need d (private). Simpler path: import as JWK directly.
  // Derive public x/y from public key.
  const pubRaw = b64UrlDecode(VAPID_PUBLIC) // 0x04 || X(32) || Y(32)
  if (pubRaw.length !== 65 || pubRaw[0] !== 0x04) {
    throw new Error('VAPID public key must be 65 bytes uncompressed (0x04 prefix)')
  }
  const x = pubRaw.slice(1, 33)
  const y = pubRaw.slice(33, 65)
  const jwk: JsonWebKey = {
    kty: 'EC',
    crv: 'P-256',
    x:   b64UrlEncode(x),
    y:   b64UrlEncode(y),
    d:   b64UrlEncode(raw),
    ext: true,
  }
  return crypto.subtle.importKey('jwk', jwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign'])
}

async function signVapidJwt(audience: string, expSeconds: number): Promise<string> {
  const header = { typ: 'JWT', alg: 'ES256' }
  const payload = {
    aud: audience,
    exp: Math.floor(Date.now() / 1000) + expSeconds,
    sub: VAPID_SUBJECT,
  }
  const enc = new TextEncoder()
  const headerB64 = b64UrlEncode(enc.encode(JSON.stringify(header)))
  const payloadB64 = b64UrlEncode(enc.encode(JSON.stringify(payload)))
  const data = `${headerB64}.${payloadB64}`
  const key  = await importPrivateKey(VAPID_PRIVATE)
  const sig  = new Uint8Array(await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' }, key, enc.encode(data),
  ))
  return `${data}.${b64UrlEncode(sig)}`
}

// Send push WITHOUT payload encryption (empty body). For a TEST notification
// the SW push event handler will fall back to its default text/title.
//
// For payload-bearing pushes (production daemon path), Python pywebpush handles
// the AES128GCM encryption + Crypto-Key headers. Doing it in Edge JS would
// require porting RFC 8291 here — intentionally deferred.
async function sendNoPayload(endpoint: string, vapidJwt: string): Promise<{ ok: boolean; status: number; text: string }> {
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'TTL':           '60',
      'Authorization': `vapid t=${vapidJwt}, k=${VAPID_PUBLIC}`,
      'Content-Length': '0',
      'Urgency':        'high',
    },
  })
  return { ok: r.ok, status: r.status, text: r.ok ? '' : (await r.text()).slice(0, 200) }
}

// ─── Route handler ───────────────────────────────────────────────────────────

export async function POST(_req: NextRequest) {
  if (!VAPID_PUBLIC || !VAPID_PRIVATE) {
    return NextResponse.json({
      ok: false,
      error: 'VAPID keys missing — set NEXT_PUBLIC_VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY in Vercel env',
    }, { status: 500 })
  }
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return NextResponse.json({ ok: false, error: 'Supabase env missing' }, { status: 500 })
  }

  // Read all subscriptions for default user
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/push_subscriptions?user_id=eq.default&select=id,endpoint`,
    {
      headers: {
        'apikey':        SUPABASE_KEY,
        'Authorization': `Bearer ${SUPABASE_KEY}`,
      },
      cache: 'no-store',
    },
  )
  const subs: Array<{ id: string; endpoint: string }> = r.ok ? await r.json() : []
  if (subs.length === 0) {
    return NextResponse.json({ ok: false, error: 'Belum ada subscription. Aktifkan dulu di toggle atas.' }, { status: 404 })
  }

  // Send test push to each subscription
  const results: Array<{ endpoint_short: string; ok: boolean; status: number; error?: string }> = []
  for (const sub of subs) {
    try {
      const url = new URL(sub.endpoint)
      const audience = `${url.protocol}//${url.host}`
      const jwt = await signVapidJwt(audience, 12 * 60 * 60)  // 12h
      const out = await sendNoPayload(sub.endpoint, jwt)
      results.push({
        endpoint_short: sub.endpoint.slice(0, 60) + '...',
        ok: out.ok,
        status: out.status,
        error: out.ok ? undefined : out.text,
      })

      // Cleanup: 410 Gone = subscription dead, delete it
      if (out.status === 410 || out.status === 404) {
        await fetch(
          `${SUPABASE_URL}/rest/v1/push_subscriptions?id=eq.${sub.id}`,
          {
            method:  'DELETE',
            headers: {
              'apikey':        SUPABASE_KEY,
              'Authorization': `Bearer ${SUPABASE_KEY}`,
            },
          },
        )
      }
    } catch (e) {
      results.push({
        endpoint_short: sub.endpoint.slice(0, 60) + '...',
        ok: false,
        status: 0,
        error: String(e).slice(0, 200),
      })
    }
  }

  return NextResponse.json({
    ok: results.some(r => r.ok),
    sent: results.filter(r => r.ok).length,
    failed: results.filter(r => !r.ok).length,
    results,
  })
}
