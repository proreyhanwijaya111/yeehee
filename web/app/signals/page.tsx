'use client'
import useSWR from 'swr'
import { TrendingUp } from 'lucide-react'
import { getSignals } from '@/lib/api'
import SignalCard from '@/components/SignalCard'
import MacroSnapshot from '@/components/MacroSnapshot'
import LoadingSpinner, { ErrorState } from '@/components/LoadingSpinner'
import { STRENGTH_LABEL, STRENGTH_COLOR, fmtPrice } from '@/lib/utils'

export default function SignalsPage() {
  const { data, isLoading, error, mutate } = useSWR(
    'signals',
    () => getSignals('signals'),
    { refreshInterval: 5 * 60 * 1000, revalidateOnFocus: false },
  )

  if (isLoading) return <LoadingSpinner text="Memuat sinyal..." />
  if (error)     return <ErrorState error={error} onRetry={() => mutate()} />
  if (!data)     return null

  const { signal_strength, confidence } = data
  const strColor = STRENGTH_COLOR[signal_strength]
  const strLabel = STRENGTH_LABEL[signal_strength]

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-sky-700/30 border border-sky-600/30 flex items-center justify-center">
          <TrendingUp size={16} className="text-sky-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Sinyal sekarang</h1>
          <p className="text-[11px] text-slate-500">3 gaya trading · auto-refresh 5 menit</p>
        </div>
      </header>

      <div className="space-y-4">
        {/* Summary pill */}
        <div
          className="rounded-xl px-3.5 py-2.5 text-xs font-semibold border tabular-nums flex items-center justify-between"
          style={{ background: `${strColor}1c`, borderColor: `${strColor}55`, color: strColor }}
        >
          <span>{strLabel}</span>
          <span className="text-slate-300">
            {(confidence * 100).toFixed(0)}% · XAU ${fmtPrice(data.xau_price)}
          </span>
        </div>

        {/* Signals stacked */}
        <div className="space-y-3">
          <SignalCard style="scalper"  signal={data.scalper_signal} />
          <SignalCard style="intraday" signal={data.intraday_signal} />
          <SignalCard style="swing"    signal={data.swing_signal} />
        </div>

        <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />
      </div>
    </main>
  )
}
