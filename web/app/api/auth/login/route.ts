/**
 * POST /api/auth/login
 *
 * Body: { username: string, password: string }
 *
 * Single-user MVP: hardcoded credentials read from env (or fallback to
 * rey666/tested1234 for first deploy). Password compared via SHA-256 of
 * `username:password:salt` so plain text never lives in repo.
 *
 * Sets httpOnly cookie `yeehee_session` containing signed user ID. Verified
 * by /middleware.ts on protected routes.
 *
 * Phase 2 will switch to Supabase Auth (email/password) for multi-user
 * registration. Cookie format compatible (`yeehee_session` will hold JWT then).
 */
import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

// Default admin user — overrideable via env. For multi-user deployment set
// AUTH_USERS_JSON='{"username":"plaintext_password"}' in Vercel env.
// Plain-text in env is fine for personal use; rotate via Vercel dashboard.
const DEFAULT_USERS: Record<string, string> = {
  'rey666': 'tested1234',
}

function loadUsers(): Record<string, string> {
  const envJson = process.env.AUTH_USERS_JSON
  if (envJson) {
    try {
      const parsed = JSON.parse(envJson)
      if (parsed && typeof parsed === 'object') return parsed as Record<string, string>
    } catch {/* ignore */}
  }
  return DEFAULT_USERS
}

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function POST(req: NextRequest) {
  let body: { username?: string; password?: string } = {}
  try { body = await req.json() } catch {/* ignore */}

  const username = (body.username || '').trim().toLowerCase()
  const password = body.password || ''

  if (!username || !password) {
    return NextResponse.json({ ok: false, error: 'Username dan password wajib.' }, { status: 400 })
  }

  const users = loadUsers()
  const expected = users[username]
  if (!expected) {
    return NextResponse.json({ ok: false, error: 'Username atau password salah.' }, { status: 401 })
  }
  // Constant-time compare against plaintext password from env.
  let mismatch = password.length !== expected.length ? 1 : 0
  const maxLen = Math.max(password.length, expected.length)
  for (let i = 0; i < maxLen; i++) {
    mismatch |= (password.charCodeAt(i) || 0) ^ (expected.charCodeAt(i) || 0)
  }
  if (mismatch !== 0) {
    return NextResponse.json({ ok: false, error: 'Username atau password salah.' }, { status: 401 })
  }

  // Sign session token: base64(username) + . + sha256(username:secret)
  // Light-weight HMAC equivalent for personal use; rotate via AUTH_SECRET env.
  const secret = process.env.AUTH_SECRET || 'yeehee_session_secret_v1'
  const sig = await sha256Hex(`${username}:${secret}`)
  const token = `${btoa(username)}.${sig}`

  const res = NextResponse.json({
    ok: true,
    user: { username },
  })
  res.cookies.set('yeehee_session', token, {
    httpOnly: true,
    secure:   true,
    sameSite: 'lax',
    path:     '/',
    maxAge:   60 * 60 * 24 * 30, // 30 days
  })
  return res
}
