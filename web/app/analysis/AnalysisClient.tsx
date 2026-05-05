'use client'
import useSWR from 'swr'
import { Brain } from 'lucide-react'
import { getSignals } from '@/lib/api'
import AgentDebate from '@/components/AgentDebate'
import { ErrorState } from '@/components/LoadingSpinner'
import type { SignalBundle } from '@/lib/types'

interface Props {
  initialBundle: SignalBundle | null
  serverError?: string | null
}

export default function AnalysisClient({ initialBundle, serverError }: Props) {
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
          <Brain size={32} className="text-violet-400/50 mx-auto mb-3" />
          <p className="text-sm font-semibold text-slate-200 mb-1">Belum ada analisis</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            Daemon belum push hasil 12-agent debate.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/30 flex items-center justify-center">
          <Brain size={16} className="text-violet-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Analisis AI</h1>
          <p className="text-[11px] text-slate-500">12 agent debat · butuh 3+ setuju → sinyal keluar</p>
        </div>
      </header>

      <div className="space-y-4">
        <AgentDebate debate={data.debate} />

        <div className={`rounded-xl px-3.5 py-2.5 border text-[11px] flex items-center gap-2 ${
          data.ai_pm_used
            ? 'bg-violet-950/30 border-violet-800/40 text-violet-300'
            : 'bg-slate-800/40 border-slate-800 text-slate-500'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${data.ai_pm_used ? 'bg-violet-400' : 'bg-slate-600'}`} />
          {data.ai_pm_used
            ? 'LLM agent aktif · 12-agent debate dengan tier pipeline'
            : 'LLM agent disabled · pakai rule engine. Set di Lainnya → Pengaturan.'}
        </div>
      </div>
    </main>
  )
}
