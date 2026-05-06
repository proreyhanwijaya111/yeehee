'use client'
import useSWR from 'swr'
import { RefreshCw, Coins, Zap } from 'lucide-react'
import { getSignals } from '@/lib/api'
import HeroCard from '@/components/HeroCard'
import MacroSnapshot from '@/components/MacroSnapshot'
import NewsAlert from '@/components/NewsAlert'
import SignalCard from '@/components/SignalCard'
import LiveTicker from '@/components/LiveTicker'
import PortfolioGlance from '@/components/PortfolioGlance'
import RcsPanel from '@/components/RcsPanel'
import { ErrorState } from '@/components/LoadingSpinner'
import { clearApiCache } from '@/lib/api'
import { formatTriggerReason } from '@/lib/utils'
import type { SignalBundle } from '@/lib/types'
import type { ActiveTrade, PortfolioStats } from '@/lib/server-api'

interface Props {
  initialBundle:    SignalBundle | null
  serverError?:     string | null
  openTrades?:      ActiveTrade[]
  closedTrades?:    ActiveTrade[]
  portfolioStats?:  PortfolioStats | null
}

export default function HomeClient({
  initialBundle, serverError, openTrades = [], closedTrades = [], portfolioStats = null,
}: Props) {
  // SWR with fallbackData = no loading flash. Hydrates from server-rendered HTML.
  // 2026-05-06: tightened refresh from 5min -> 60s. Daemon pushes ~3min cycles,
  // so 60s catches new bundles within 1-2x cycle. Old 5min interval meant
  // "5m lalu" stayed visible for 8+ minutes after a new bundle landed in DB.
  const { data, error, mutate } = useSWR(
    'signals',
    () => getSignals('signals'),
    {
      fallbackData:        initialBundle ?? undefined,
      refreshInterval:     60 * 1000,
      revalidateOnFocus:   false,
      revalidateOnMount:   !initialBundle,  // only fetch on mount if no SSR data
    },
  )

  const handleRefresh = async () => {
    await clearApiCache()
    await mutate()
  }

  // No data: server fetched nothing, show error UI server-rendered
  if (!data && (error || serverError)) {
    return <ErrorState error={error ?? new Error(serverError ?? 'Belum ada signal')} onRetry={() => mutate()} />
  }
  if (!data) {
    // Server had no data at all (daemon not running / Supabase empty)
    return (
      <main className="max-w-lg mx-auto px-4 pt-12 pb-2 animate-fade-in">
        <div className="bg-slate-800/40 border border-slate-800 rounded-2xl p-6 text-center">
          <Coins size={32} className="text-amber-400/50 mx-auto mb-3" />
          <p className="text-sm font-semibold text-slate-200 mb-1">Belum ada signal</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            Daemon di PC rumah belum push cycle pertama. Pastikan daemon jalan di
            <span className="font-mono"> $HOME\yeehee-daemon</span> dan koneksi Supabase OK.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
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
        {/* Live spot price ticker — independent dari daemon refresh */}
        <LiveTicker />

        {/* Portfolio glance — production-grade quick access to /portfolio */}
        <PortfolioGlance stats={portfolioStats} openTrades={openTrades} closedTrades={closedTrades} />

        {data.in_news_blackout && <NewsAlert type="blackout" event={data.blackout_event} />}
        {!data.in_news_blackout && data.upcoming_events?.[0] && (
          <NewsAlert type="warning" event={data.upcoming_events[0]} />
        )}

        <HeroCard
          bundle={data}
          isExecuted={openTrades.some(t => t.status === 'OPEN')}
        />

        <div>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
            Sinyal per gaya trading
          </p>
          <div className="flex gap-3 overflow-x-auto pb-1 -mx-1 px-1 snap-x snap-mandatory">
            {[
              { style: 'scalper'  as const, sig: data.scalper_signal  },
              { style: 'intraday' as const, sig: data.intraday_signal },
              { style: 'swing'    as const, sig: data.swing_signal    },
            ].map(({ style, sig }) => {
              const isExecuted = openTrades.some(t => t.style === style && t.status === 'OPEN')
              return (
                <div key={style} className="min-w-[280px] snap-start">
                  <SignalCard
                    style={style}
                    signal={sig}
                    bundleTimestamp={data.timestamp}
                    isExecuted={isExecuted}
                  />
                </div>
              )
            })}
          </div>
        </div>

        <RcsPanel rcs={data.rcs ?? null} />

        <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />

        <FooterTrigger trigger_reason={data.trigger_reason} />
      </div>
    </main>
  )
}

function FooterTrigger({ trigger_reason }: { trigger_reason?: string }) {
  const t = formatTriggerReason(trigger_reason)
  const isMomentum = t.kind !== 'scheduled'
  return (
    <p className="text-center text-[10px] pt-1 pb-1 flex items-center justify-center gap-1">
      {isMomentum && <Zap size={10} className="text-amber-400" />}
      <span className={isMomentum ? 'text-amber-300 font-semibold' : 'text-slate-600'}>
        {t.label}
      </span>
      <span className="text-slate-600"> · personal use only</span>
    </p>
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
