// Server Component (no 'use client') — fetches signal_bundle at request time,
// passes to HomeClient as initialBundle. SWR client-side hydrates from this
// instead of showing "Memuat..." skeleton on first paint.
//
// SEO: HTML rendered to crawler now contains actual signal data.
// First paint: instant (no JS round-trip needed for above-fold content).
// Errors: server can render fallback UI without waiting for client JS.
import HomeClient from './HomeClient'
import { getLatestSignalBundle } from '@/lib/server-api'

// Cache for 60s — daemon refreshes every 5 min, so 60s gives reasonable freshness
// without slamming Supabase on every page view. Vercel CDN handles further caching.
export const revalidate = 60

export default async function HomePage() {
  let initialBundle = null
  let serverError: string | null = null
  try {
    initialBundle = await getLatestSignalBundle()
  } catch (e) {
    serverError = e instanceof Error ? e.message : 'Failed to load initial signal'
  }
  return <HomeClient initialBundle={initialBundle} serverError={serverError} />
}
