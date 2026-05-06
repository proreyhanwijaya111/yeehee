/**
 * POST /api/auth/logout
 * Clears the yeehee_session cookie. UI should redirect to /login afterward.
 */
import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

export async function POST() {
  const res = NextResponse.json({ ok: true })
  res.cookies.set('yeehee_session', '', {
    httpOnly: true,
    secure:   true,
    sameSite: 'lax',
    path:     '/',
    maxAge:   0,
  })
  return res
}
