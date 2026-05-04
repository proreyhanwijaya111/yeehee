'use client'
import useSWR from 'swr'
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
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <div>
        <h1 className="text-lg font-black text-slate-100">🧠 Analisis AI</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          4 AI agent debat → butuh 3 dari 4 sepakat baru sinyal keluar
        </p>
      </div>

      <AgentDebate debate={data.debate} />

      {/* PM Narrative */}
      {data.ai_pm_used && (
        <div className="bg-purple-950/40 border border-purple-700/40 rounded-2xl p-4">
          <p className="text-xs text-purple-400 font-semibold uppercase tracking-wide mb-2">
            🎩 Claude PM Narrative
          </p>
          <p className="text-xs text-purple-300/80">PM AI aktif dan memberikan narasi tambahan.</p>
        </div>
      )}
      {!data.ai_pm_used && (
        <p className="text-xs text-slate-500 text-center">
          💡 Set ANTHROPIC_API_KEY untuk mengaktifkan Claude PM narrative
        </p>
      )}
    </main>
  )
}
