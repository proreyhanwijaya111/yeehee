'use client'
import useSWR from 'swr'
import { Calendar, AlertOctagon, CheckCircle2 } from 'lucide-react'
import { getCalendar } from '@/lib/api'
import LoadingSpinner, { ErrorState } from '@/components/LoadingSpinner'

const IMPACT_DOT: Record<string, string> = {
  HIGH:   'bg-rose-500',
  MEDIUM: 'bg-amber-500',
  LOW:    'bg-slate-500',
}

const IMPACT_TEXT: Record<string, string> = {
  HIGH:   'text-rose-300',
  MEDIUM: 'text-amber-300',
  LOW:    'text-slate-400',
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
    { refreshInterval: 60 * 60 * 1000 },
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
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-amber-700/30 border border-amber-600/30 flex items-center justify-center">
          <Calendar size={16} className="text-amber-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Berita ekonomi</h1>
          <p className="text-[11px] text-slate-500">Engine skip entry 30 menit sebelum/sesudah event HIGH</p>
        </div>
      </header>

      {events.length === 0 && (
        <div className="text-center py-12">
          <CheckCircle2 size={28} className="text-emerald-400 mx-auto mb-2" />
          <p className="text-xs text-slate-500">Tidak ada event dalam 7 hari ke depan</p>
        </div>
      )}

      <div className="space-y-5">
        {high.length > 0 && (
          <section>
            <p className="text-[10px] font-semibold text-rose-400 uppercase tracking-widest mb-1.5 px-2 flex items-center gap-1.5">
              <AlertOctagon size={10} /> High impact ({high.length})
            </p>
            <div className="bg-rose-950/20 rounded-2xl border border-rose-900/40 overflow-hidden divide-y divide-rose-900/30">
              {high.map((e, i) => <EventRow key={i} event={e} />)}
            </div>
          </section>
        )}

        {others.length > 0 && (
          <section>
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
              Medium / Low impact
            </p>
            <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
              {others.map((e, i) => <EventRow key={i} event={e} />)}
            </div>
          </section>
        )}
      </div>
    </main>
  )
}

function EventRow({ event }: { event: { when_utc: string; currency: string; impact: string; title: string; forecast: string | null; previous: string | null } }) {
  const impact  = event.impact.toUpperCase()
  const dot     = IMPACT_DOT[impact]   ?? IMPACT_DOT.LOW
  const text    = IMPACT_TEXT[impact]  ?? IMPACT_TEXT.LOW
  const timeWib = parseWib(event.when_utc)

  return (
    <div className="px-3.5 py-3">
      <div className="flex items-start gap-3">
        <span className={`w-2 h-2 rounded-full ${dot} shrink-0 mt-1.5`} />
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium leading-snug ${text}`}>{event.title}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">{timeWib}</p>
          {(event.forecast || event.previous) && (
            <div className="flex gap-3 mt-1.5 text-[10px] text-slate-500 font-mono">
              <span className="text-slate-400">{event.currency}</span>
              {event.forecast && <span>fcst: {event.forecast}</span>}
              {event.previous && <span>prev: {event.previous}</span>}
            </div>
          )}
        </div>
        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider shrink-0">
          {impact}
        </span>
      </div>
    </div>
  )
}
