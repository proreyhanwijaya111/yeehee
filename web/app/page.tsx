'use client'
import useSWR from 'swr'
import { RefreshCw } from 'lucide-react'
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
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-3 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black text-slate-100">🪙 yeehee</h1>
          <p className="text-[11px] text-slate-500">XAU/USD Signal · {data.timestamp}</p>
        </div>
        <button
          onClick={handleRefresh}
          className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 transition-colors touch-action active:scale-95"
        >
          <RefreshCw size={16} className="text-slate-400" />
        </button>
      </div>

      {/* News alerts */}
      {data.in_news_blackout && (
        <NewsAlert type="blackout" event={data.blackout_event} />
      )}
      {!data.in_news_blackout && data.upcoming_events?.[0] && (
        <NewsAlert type="warning" event={data.upcoming_events[0]} />
      )}

      {/* Hero */}
      <HeroCard bundle={data} />

      {/* Quick signal cards — horizontal scroll on mobile */}
      <div>
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">
          Sinyal Per Gaya Trading
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

      {/* Macro snapshot */}
      <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />

      <p className="text-center text-[10px] text-slate-600 pb-1">
        Auto-refresh tiap 5 mnt · Hanya untuk penggunaan pribadi
      </p>
    </main>
  )
}
