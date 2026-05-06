/**
 * Middleware — gate every page route except /login + auth/static APIs.
 *
 * Cookie format: base64(username) + . + sha256(username:AUTH_SECRET)
 * Same as set by /api/auth/login. We re-derive the expected signature here
 * (Edge runtime supports crypto.subtle) and compare.
 *
 * Protected routes redirect to /login?next=<original-path>.
 */
import { NextRequest, NextResponse } from 'next/server'

// Public paths — no auth required. Extend if you add public marketing pages.
const PUBLIC_PATHS = [
  '/login',
  '/api/auth/login',
  '/api/auth/logout',
  '/api/auth/me',
  '/api/setup/script',     // installer script — must be public for fresh PC
  '/manifest.json',
  '/manifest.webmanifest',
  '/sw.js',
  '/icons',                // PWA icons
  '/favicon.ico',
  '/_next',
]

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some(p => pathname === p || pathname.startsWith(`${p}/`) || pathname.startsWith(p + '?'))
}

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

async function verifyCookie(token: string | undefined): Promise<boolean> {
  if (!token) return false
  const [b64u, sig] = token.split('.')
  if (!b64u || !sig) return false
  let username = ''
  try { username = atob(b64u) } catch { return false }
  const secret = process.env.AUTH_SECRET || 'yeehee_session_secret_v1'
  const expected = await sha256Hex(`${username}:${secret}`)
  return expected === sig
}

export async function middleware(req: NextRequest) {
  const pathname = req.nextUrl.pathname
  if (isPublic(pathname)) {
    return NextResponse.next()
  }

  // Defensive: any unexpected error in cookie verification should NOT crash
  // the middleware (which would cause ERR_CONNECTION_ABORTED in PWA standalone
  // mode). Treat verify failure as "not logged in" and redirect to /login.
  let valid = false
  try {
    const cookie = req.cookies.get('yeehee_session')?.value
    valid = await verifyCookie(cookie)
  } catch {
    valid = false
  }

  if (valid) {
    return NextResponse.next()
  }

  // Redirect to login with `next` param. Build absolute URL using request
  // origin so PWA standalone mode handles it correctly (don't rely on relative).
  const loginUrl = new URL('/login', req.url)
  if (pathname !== '/' && pathname !== '/login') {
    loginUrl.searchParams.set('next', pathname + (req.nextUrl.search || ''))
  }
  const res = NextResponse.redirect(loginUrl)
  // Prevent stale cache from serving old failed responses to PWA
  res.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate')
  return res
}

// Skip static files at the matcher level so middleware doesn't run unnecessarily
export const config = {
  matcher: [
    /*
     * Match all paths EXCEPT:
     *   - _next/static, _next/image (Next.js internals)
     *   - favicon.ico, manifest, icons (static assets)
     *   - .png, .jpg, .svg, .ico, .css, .js (other static)
     */
    '/((?!_next/static|_next/image|favicon.ico|manifest.json|manifest.webmanifest|sw.js|icons/|.*\\.(?:png|jpg|jpeg|svg|ico|css|js|webmanifest)$).*)',
  ],
}
