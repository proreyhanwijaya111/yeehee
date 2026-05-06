/**
 * GET /api/auth/me
 * Returns { ok: true, user: { username } } if cookie valid, else { ok: false }.
 * Used by login page to redirect already-authenticated visitors.
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function GET(req: NextRequest) {
  const cookie = req.cookies.get('yeehee_session')?.value
  if (!cookie) {
    return NextResponse.json({ ok: false, user: null })
  }
  const [b64u, sig] = cookie.split('.')
  if (!b64u || !sig) {
    return NextResponse.json({ ok: false, user: null })
  }
  let username = ''
  try { username = atob(b64u) } catch { return NextResponse.json({ ok: false, user: null }) }

  const secret = process.env.AUTH_SECRET || 'yeehee_session_secret_v1'
  const expected = await sha256Hex(`${username}:${secret}`)
  if (expected !== sig) {
    return NextResponse.json({ ok: false, user: null })
  }
  return NextResponse.json({ ok: true, user: { username } })
}
