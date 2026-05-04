'use client'
import useSWR from 'swr'
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

  const { final_action, signal_strength, confidence } = data
  const strColor = STRENGTH_COLOR[signal_strength]
  const strLabel = STRENGTH_LABEL[signal_strength]

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <h1 className="text-lg font-black text-slate-100">📊 Sinyal Sekarang</h1>

      {/* Summary banner */}
      <div
        className="rounded-2xl px-4 py-3 text-sm font-semibold border"
        style={{ background: `${strColor}22`, borderColor: `${strColor}55`, color: strColor }}
      >
        {strLabel} · Keyakinan {(confidence * 100).toFixed(0)}% · XAU ${fmtPrice(data.xau_price)}
      </div>

      {/* 3 signal cards stacked */}
      <div className="space-y-3">
        <SignalCard style="scalper"  signal={data.scalper_signal} />
        <SignalCard style="intraday" signal={data.intraday_signal} />
        <SignalCard style="swing"    signal={data.swing_signal} />
      </div>

      <MacroSnapshot intermarket={data.intermarket} cot={data.cot} />
    </main>
  )
}
