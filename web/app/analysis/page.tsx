'use client'
import useSWR from 'swr'
import { Brain } from 'lucide-react'
import { getSignals } from '@/lib/api'
import AgentDebate from '@/components/AgentDebate'
import LoadingSpinner, { ErrorState } from '@/components/LoadingSpinner'

export default function AnalysisPage() {
  const { data, isLoading, error, mutate } = useSWR(
    'signals',
    () => getSignals('signals'),
    { refreshInterval: 5 * 60 * 1000, revalidateOnFocus: false },
  )

  if (isLoading) return <LoadingSpinner text="Memuat analisis AI..." />
  if (error)     return <ErrorState error={error} onRetry={() => mutate()} />
  if (!data)     return null

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/30 flex items-center justify-center">
          <Brain size={16} className="text-violet-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Analisis AI</h1>
          <p className="text-[11px] text-slate-500">9 agent debat · butuh 3 dari 4 setuju → sinyal keluar</p>
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
            ? 'LLM agent aktif · narasi PM tersedia'
            : 'LLM agent disabled · pakai rule engine. Set di Lainnya → Pengaturan → 9 AI Agent.'}
        </div>
      </div>
    </main>
  )
}
