'use client'
import useSWR from 'swr'
import { TrendingUp, Zap, Clock } from 'lucide-react'
import { getSignals } from '@/lib/api'
import SignalCard from '@/components/SignalCard'
import MacroSnapshot from '@/components/MacroSnapshot'
import RcsPanel from '@/components/RcsPanel'
import { ErrorState } from '@/components/LoadingSpinner'
import { STRENGTH_LABEL, STRENGTH_COLOR, fmtPrice, formatTriggerReason } from '@/lib/utils'
import type { SignalBundle } from '@/lib/types'
import type { ActiveTrade } from '@/lib/server-api'

interface Props {
  initialBundle: SignalBundle | null
  serverError?: string | null
  openTrades?:  ActiveTrade[]
}

export default function SignalsClient({ initialBundle, serverError, openTrades = [] }: Props) {
  // 2026-05-07: 5min refresh (was 60s) — Vercel free tier exceeded by tighter
  // refresh schedule. Each SWR fetch hits Supabase REST + Vercel function.
  // Daemon push 3min, so 5min catches every other cycle. Trade staleness for
  // not blowing through 1M function invocations cap.
  const { data, error, mutate } = useSWR(
    'signals',
    () => getSignals('signals'),
    {
      fallbackData:      initialBundle ?? undefined,
      refreshInterval:   5 * 60 * 1000,
      revalidateOnFocus: false,
      revalidateOnMount: !initialBundle,
    },
  )

  if (!data && (error || serverError)) {
    return <ErrorState error={error ?? new Error(serverError ?? 'Gagal load')} onRetry={() => mutate()} />
  }
  if (!data) {
    return (
      <main className="max-w-lg mx-auto px-4 pt-12 pb-2 animate-fade-in">
        <div className="bg-slate-800/40 border border-slate-800 rounded-2xl p-6 text-center">
          <TrendingUp size={32} className="text-sky-400/50 mx-auto mb-3" />
          <p className="text-sm font-semibold text-slate-200 mb-1">Belum ada signal</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            Tunggu daemon di PC rumah push cycle pertama, lalu refresh.
          </p>
        </div>
      </main>
    )
  }

  const { signal_strength, confidence } = data
  const strColor = STRENGTH_COLOR[signal_strength]
  const strLabel = STRENGTH_LABEL[signal_strength]
  const trigger = formatTriggerReason(data.trigger_reason)
  const isMomentum = trigger.kind !== 'scheduled'

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-sky-700/30 border border-sky-600/30 flex items-center justify-center">
          <TrendingUp size={16} className="text-sky-300" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-black text-slate-100 leading-tight">Sinyal sekarang</h1>
          <p className="text-[11px] text-slate-500 flex items-center gap-1.5">
            {isMomentum
              ? <Zap size={11} className="text-amber-400 shrink-0" />
              : <Clock size={11} className="text-slate-500 shrink-0" />}
            <span className={isMomentum ? 'text-amber-300 font-semibold' : ''}>
              {trigger.label}
            </span>
          </p>
        </div>
      </header>

      <div className="space-y-4">
        <div
          className="rounded-xl px-3.5 py-2.5 text-xs font-semibold border tabular-nums flex items-center justify-between"
          style={{ background: `${strColor}1c`, borderColor: `${strColor}55`, color: strColor }}
        >
          <span>{strLabel}</span>
          <span className="text-slate-300">
            {(confidence * 100).toFixed(0)}% · XAU ${fmtPrice(data.xau_price)}
          </span>
        </div>

        <div className="space-y-3">
          <SignalCard
            style="scalper"
            signal={data.scalper_signal}
            bundleTimestamp={data.timestamp}
            isExecuted={openTrades.some(t => t.style === 'scalper' && t.status === 'OPEN')}
          />
          <SignalCard
            style="intraday"
            signal={data.intraday_signal}
            bundleTimestamp={data.timestamp}
            isExecuted={openTrades.some(t => t.style === 'intraday' && t.status === 'OPEN')}
          />
          <SignalCard
            style="swing"
            signal={data.swing_signal}
            bundleTimestamp={data.timestamp}
            isExecuted={openTrades.some(t => t.style === 'swing' && t.status === 'OPEN')}
          />
        </div>

        <RcsPanel rcs={data.rcs ?? null} />

        <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />
      </div>
    </main>
  )
}
