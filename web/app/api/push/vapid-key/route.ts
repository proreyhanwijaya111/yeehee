/**
 * GET /api/push/vapid-key
 * Returns the VAPID public key (b64url) so the client can pass it to
 * pushManager.subscribe({ applicationServerKey }). Public key is safe to
 * expose — backend keeps the private key.
 */
import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime  = 'edge'

export async function GET() {
  const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || ''
  if (!key) {
    return NextResponse.json({ ok: false, error: 'VAPID public key tidak di-set di env' }, { status: 503 })
  }
  return NextResponse.json({ ok: true, publicKey: key })
}
