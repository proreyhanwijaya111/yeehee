'use client'
import useSWR from 'swr'
import { RefreshCw, Coins } from 'lucide-react'
import { getSignals } from '@/lib/api'
import HeroCard from '@/components/HeroCard'
import MacroSnapshot from '@/components/MacroSnapshot'
import NewsAlert from '@/components/NewsAlert'
import SignalCard from '@/components/SignalCard'
import LoadingSpinner, { ErrorState } from '@/components/LoadingSpinner'
import { clearApiCache } from '@/lib/api'

export default function HomePage() {
  const { data, isLoading, error, mutate } = useSWR(
    'signals',
    () => getSignals('signals'),
    { refreshInterval: 5 * 60 * 1000, revalidateOnFocus: false },
  )

  const handleRefresh = async () => {
    await clearApiCache()
    await mutate()
  }

  if (isLoading) return <LoadingSpinner text="Memuat sinyal terbaru..." />
  if (error)     return <ErrorState error={error} onRetry={() => mutate()} />
  if (!data)     return null

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      {/* Header */}
      <header className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-amber-700/30 border border-amber-600/30 flex items-center justify-center">
            <Coins size={16} className="text-amber-300" />
          </div>
          <div>
            <h1 className="text-lg font-black text-slate-100 leading-tight">yeehee</h1>
            <p className="text-[10px] text-slate-500 font-mono">XAU/USD · {formatTime(data.timestamp)}</p>
          </div>
        </div>
        <button
          onClick={handleRefresh}
          className="p-2 rounded-lg bg-slate-800/60 border border-slate-700/50 hover:bg-slate-800 transition-colors touch-action active:scale-95"
          aria-label="Refresh"
        >
          <RefreshCw size={14} className="text-slate-400" />
        </button>
      </header>

      <div className="space-y-4">
        {/* News alerts */}
        {data.in_news_blackout && <NewsAlert type="blackout" event={data.blackout_event} />}
        {!data.in_news_blackout && data.upcoming_events?.[0] && (
          <NewsAlert type="warning" event={data.upcoming_events[0]} />
        )}

        {/* Hero */}
        <HeroCard bundle={data} />

        {/* Quick signal cards — horizontal scroll */}
        <div>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
            Sinyal per gaya trading
          </p>
          <div className="flex gap-3 overflow-x-auto pb-1 -mx-1 px-1 snap-x snap-mandatory">
            {[
              { style: 'scalper'  as const, sig: data.scalper_signal  },
              { style: 'intraday' as const, sig: data.intraday_signal },
              { style: 'swing'    as const, sig: data.swing_signal    },
            ].map(({ style, sig }) => (
              <div key={style} className="min-w-[280px] snap-start">
                <SignalCard style={style} signal={sig} />
              </div>
            ))}
          </div>
        </div>

        {/* Macro */}
        <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />

        <p className="text-center text-[10px] text-slate-600 pt-1 pb-1">
          Auto-refresh 5 menit · personal use only
        </p>
      </div>
    </main>
  )
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('id-ID', {
      hour: '2-digit', minute: '2-digit',
      day: '2-digit', month: 'short',
    })
  } catch {
    return iso
  }
}
