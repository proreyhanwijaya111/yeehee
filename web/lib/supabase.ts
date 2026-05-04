import { createClient } from '@supabase/supabase-js'

const supabaseUrl  = process.env.NEXT_PUBLIC_SUPABASE_URL  ?? ''
const supabaseAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ''

// Returns null if not configured (graceful degradation)
export const supabase = supabaseUrl && supabaseAnon
  ? createClient(supabaseUrl, supabaseAnon)
  : null

export type Json = string | number | boolean | null | { [key: string]: Json } | Json[]

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Ambil 50 signal history terbaru dari Supabase */
export async function getSignalHistory(style?: string, limit = 50) {
  if (!supabase) return []
  let query = supabase
    .from('signals')
    .select('created_at,style,action,confidence,entry,sl,tp1,rr_to_tp1,regime,xau_price')
    .order('created_at', { ascending: false })
    .limit(limit)
  if (style) query = query.eq('style', style)
  const { data } = await query
  return data ?? []
}

/** Subscribe ke update realtime signal_bundles */
export function subscribeSignals(callback: (payload: unknown) => void) {
  if (!supabase) return null
  return supabase
    .channel('signal_bundles')
    .on('postgres_changes', {
      event:  'INSERT',
      schema: 'public',
      table:  'signal_bundles',
    }, callback)
    .subscribe()
}
