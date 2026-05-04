'use client'
import useSWR from 'swr'
import { getCalendar } from '@/lib/api'
import LoadingSpinner, { ErrorState } from '@/components/LoadingSpinner'
import { cn } from '@/lib/utils'

const IMPACT_STYLE = {
  HIGH:   { bg: 'bg-red-950/60',    border: 'border-red-700/40',    text: 'text-red-300',    badge: 'bg-red-800/80 text-red-200' },
  MEDIUM: { bg: 'bg-amber-950/40',  border: 'border-amber-700/30',  text: 'text-amber-300',  badge: 'bg-amber-800/60 text-amber-200' },
  LOW:    { bg: 'bg-slate-800/40',  border: 'border-slate-700/30',  text: 'text-slate-400',  badge: 'bg-slate-700/60 text-slate-400' },
}

function parseWib(utcStr: string) {
  try {
    const t = new Date(utcStr)
    const wib = new Date(t.getTime() + 7 * 3600_000)
    return wib.toLocaleString('id-ID', {
      weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit',
    }) + ' WIB'
  } catch { return utcStr }
}

export default function NewsPage() {
  const { data, isLoading, error, mutate } = useSWR(
    'calendar',
    getCalendar,
    { refreshInterval: 60 * 60 * 1000 }, // refresh 1 jam
  )

  if (isLoading) return <LoadingSpinner text="Memuat kalender berita..." />
  if (error)     return <ErrorState error={error} onRetry={() => mutate()} />

  const now    = new Date()
  const in7d   = new Date(now.getTime() + 7 * 86_400_000)
  const events = (data ?? []).filter(e => {
    try {
      const t = new Date(e.when_utc)
      return t >= new Date(now.getTime() - 3 * 3600_000) && t <= in7d
    } catch { return false }
  })

  const high   = events.filter(e => e.impact.toUpperCase() === 'HIGH')
  const others = events.filter(e => e.impact.toUpperCase() !== 'HIGH')

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <div>
        <h1 className="text-lg font-black text-slate-100">📅 Berita Ekonomi</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Event HIGH = dampak besar · engine skip entry 30 mnt sebelum/sesudah
        </p>
      </div>

      {events.length === 0 && (
        <div className="text-center py-12 text-slate-500">
          <p className="text-3xl mb-2">✅</p>
          <p>Tidak ada event dalam 7 hari ke depan</p>
        </div>
      )}

      {high.length > 0 && (
        <section>
          <p className="text-xs text-red-400 font-semibold uppercase tracking-wider mb-2">
            🚨 High Impact ({high.length})
          </p>
          <div className="space-y-2">
            {high.map((e, i) => <EventCard key={i} event={e} />)}
          </div>
        </section>
      )}

      {others.length > 0 && (
        <section>
          <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">
            Medium / Low Impact
          </p>
          <div className="space-y-2">
            {others.map((e, i) => <EventCard key={i} event={e} />)}
          </div>
        </section>
      )}
    </main>
  )
}

function EventCard({ event }: { event: { when_utc: string; currency: string; impact: string; title: string; forecast: string | null; previous: string | null } }) {
  const impact = event.impact.toUpperCase() as 'HIGH' | 'MEDIUM' | 'LOW'
  const style  = IMPACT_STYLE[impact] ?? IMPACT_STYLE.LOW
  const timeWib = parseWib(event.when_utc)

  return (
    <div className={cn(
      'rounded-2xl border px-4 py-3',
      style.bg, style.border,
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className={cn('text-sm font-semibold leading-snug', style.text)}>
            {event.title}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">{timeWib}</p>
        </div>
        <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0', style.badge)}>
          {impact}
        </span>
      </div>
      <div className="flex gap-3 mt-2 text-xs text-slate-500">
        <span>{event.currency}</span>
        {event.forecast && <span>Perkiraan: {event.forecast}</span>}
        {event.previous  && <span>Sebelumnya: {event.previous}</span>}
      </div>
    </div>
  )
}
