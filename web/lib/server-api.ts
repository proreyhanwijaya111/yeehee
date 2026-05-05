/**
 * Server-side data layer (RSC / Edge runtime safe).
 *
 * Why separate from lib/api.ts:
 * - lib/api.ts uses @supabase/supabase-js client (browser-friendly, requires global state)
 * - Server Components need fetch() that runs at request time + Next.js cache integration
 * - This file uses raw fetch with `next: { revalidate: N }` for SSR caching control
 *
 * Used by:
 * - app/page.tsx (RSC) -> getLatestSignalBundle()
 * - app/signals/page.tsx (RSC) -> getLatestSignalBundle()
 * - app/analysis/page.tsx (RSC) -> getLatestSignalBundle()
 *
 * Note: env vars NEXT_PUBLIC_* tetap accessible di server-side. Anon key cocok
 * untuk public read (RLS sudah disabled / public policies).
 */
import 'server-only'
import type {
  SignalBundle, CalendarEvent, TradeAction, SignalStrength,
} from './types'

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// Cache TTL — 60s match daemon refresh cadence (default 5min)
// pakai 60s biar UI punya freshness window kalau user reload cepat
const REVALIDATE_S = 60

async function supabaseGet<T = unknown>(path: string, opts?: { revalidate?: number }): Promise<T | null> {
  if (!URL || !KEY) return null
  try {
    const r = await fetch(`${URL}/rest/v1/${path}`, {
      headers: {
        apikey:        KEY,
        Authorization: `Bearer ${KEY}`,
      },
      next: { revalidate: opts?.revalidate ?? REVALIDATE_S },
    })
    if (!r.ok) {
      console.warn(`[server-api] supabase ${path} HTTP ${r.status}`)
      return null
    }
    return await r.json() as T
  } catch (e) {
    console.warn(`[server-api] supabase ${path} fetch error:`, e)
    return null
  }
}

// ── Signal bundle (latest) ──────────────────────────────────────────────────────

export async function getLatestSignalBundle(): Promise<SignalBundle | null> {
  const rows = await supabaseGet<Array<Record<string, unknown>>>(
    'signal_bundles?select=*&order=created_at.desc&limit=1',
  )
  if (!rows || rows.length === 0) return null
  return mapBundleRowToSignalBundle(rows[0])
}

// ── Calendar events (from latest bundle's upcoming_events) ──────────────────────

export async function getCalendarEvents(): Promise<CalendarEvent[]> {
  const rows = await supabaseGet<Array<Record<string, unknown>>>(
    'signal_bundles?select=upcoming_events&order=created_at.desc&limit=1',
  )
  if (!rows || rows.length === 0) return []
  const upcoming = (rows[0].upcoming_events ?? []) as Array<{
    title?: string; when_utc?: string; currency?: string; impact?: string;
    forecast?: string | null; previous?: string | null;
  }>
  return upcoming.map(e => ({
    when_utc: String(e.when_utc ?? ''),
    currency: String(e.currency ?? ''),
    impact:   String(e.impact ?? 'LOW').toUpperCase(),
    title:    String(e.title ?? '(no title)'),
    forecast: e.forecast ?? null,
    previous: e.previous ?? null,
  }))
}

// ── Daemon heartbeat ────────────────────────────────────────────────────────────

export async function getDaemonHeartbeatServer(): Promise<{
  hostname: string | null
  last_signal_at: string | null
  updated_at: string | null
  error: string | null
} | null> {
  const rows = await supabaseGet<Array<Record<string, unknown>>>(
    'daemon_heartbeat?select=hostname,last_signal_at,updated_at,error&limit=1',
    { revalidate: 30 }, // heartbeat updates faster
  )
  if (!rows || rows.length === 0) return null
  const r = rows[0]
  return {
    hostname:       (r.hostname ?? null) as string | null,
    last_signal_at: (r.last_signal_at ?? null) as string | null,
    updated_at:     (r.updated_at ?? null) as string | null,
    error:          (r.error ?? null) as string | null,
  }
}

// ── Mapper (mirror of client-side, but pure function) ───────────────────────────

function mapBundleRowToSignalBundle(row: Record<string, unknown>): SignalBundle {
  const debate = (row.debate as Record<string, unknown>) ?? {}
  return {
    xau_price:        Number(row.xau_price ?? 0),
    timestamp:        String(row.created_at ?? new Date().toISOString()),
    regime:           String(row.regime ?? 'unknown'),
    session:          String(row.session ?? 'unknown'),
    in_news_blackout: Boolean(row.in_news_blackout),
    blackout_event:   (row.blackout_event as SignalBundle['blackout_event']) ?? null,
    upcoming_events:  (row.upcoming_events as SignalBundle['upcoming_events']) ?? [],
    scalper_signal:   normaliseSignal(row.scalper_signal),
    intraday_signal:  normaliseSignal(row.intraday_signal),
    swing_signal:     normaliseSignal(row.swing_signal),
    debate: {
      final_action:    (debate.final_action as TradeAction) ?? 'FLAT',
      signal_strength: (debate.signal_strength as SignalStrength) ?? 'FLAT',
      confidence:      Number(debate.confidence ?? 0),
      primary_driver:  String(debate.primary_driver ?? ''),
      agents:          Array.isArray(debate.agents) ? debate.agents as SignalBundle['debate']['agents'] : [],
      reasoning_chain: Array.isArray(debate.reasoning_chain) ? debate.reasoning_chain as string[] : [],
      risks:           Array.isArray(debate.risks) ? debate.risks as string[] : [],
    },
    intermarket: (row.intermarket as SignalBundle['intermarket']) ?? {
      score: 0, components: {},
    },
    cot: (row.cot as SignalBundle['cot']) ?? { z: null, net_long: null, signal: null },
    ai_pm_used:      Boolean(row.ai_pm_used),
    final_action:    (row.final_action as TradeAction) ?? 'FLAT',
    signal_strength: (row.signal_strength as SignalStrength) ?? 'FLAT',
    confidence:      Number(row.confidence ?? 0),
  }
}

function normaliseSignal(raw: unknown): SignalBundle['scalper_signal'] {
  const r = (raw as Record<string, unknown>) ?? {}
  const side = (r.side ?? r.action ?? 'FLAT') as TradeAction
  return {
    side,
    confidence:       Number(r.confidence ?? 0),
    confluence_count: Number(r.confluence_count ?? r.confluence ?? 0),
    entry:            Number(r.entry ?? 0),
    sl:               Number(r.sl ?? 0),
    tp1:              Number(r.tp1 ?? 0),
    tp2:              Number(r.tp2 ?? 0),
    tp3:              Number(r.tp3 ?? 0),
    rr_to_tp1:        Number(r.rr_to_tp1 ?? 0),
    rr_to_tp2:        Number(r.rr_to_tp2 ?? 0),
    regime:           String(r.regime ?? ''),
    session:          String(r.session ?? ''),
    timestamp:        String(r.timestamp ?? ''),
    reasons:          Array.isArray(r.reasons) ? r.reasons as string[] : [],
    risks:            Array.isArray(r.risks)   ? r.risks   as string[] : [],
  }
}
