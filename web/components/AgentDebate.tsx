import type { Debate } from '@/lib/types'
import {
  ACTION_LABEL, ACTION_COLOR, STRENGTH_LABEL, STRENGTH_COLOR, STRENGTH_DESC,
  humanizeAgent, fmtPct, cn,
} from '@/lib/utils'

interface Props {
  debate: Debate
}

export default function AgentDebate({ debate }: Props) {
  const { final_action, signal_strength, confidence, agents, reasoning_chain, risks, primary_driver } = debate

  const strengthColor = STRENGTH_COLOR[signal_strength]
  const actionLabel   = ACTION_LABEL[final_action]
  const strengthLabel = STRENGTH_LABEL[signal_strength]
  const strDesc       = STRENGTH_DESC[signal_strength]

  // Count votes
  const voteLong  = agents.filter(a => a.verdict === 'LONG').length
  const voteShort = agents.filter(a => a.verdict === 'SHORT').length
  const voteFlat  = agents.filter(a => a.verdict === 'FLAT').length

  return (
    <div className="space-y-4">
      {/* Final verdict */}
      <div
        className="rounded-3xl p-5 border"
        style={{ background: `${strengthColor}22`, borderColor: `${strengthColor}55` }}
      >
        <p className="text-2xl font-black" style={{ color: strengthColor }}>
          {actionLabel}
        </p>
        <p className="font-semibold text-sm mt-0.5" style={{ color: strengthColor }}>
          {strengthLabel}
        </p>
        <p className="text-xs text-slate-400 mt-1">{strDesc}</p>
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <div className="bg-black/20 rounded-full px-3 py-1 text-xs font-semibold">
            Keyakinan: {fmtPct(confidence)}
          </div>
          {primary_driver && (
            <div className="bg-black/20 rounded-full px-3 py-1 text-xs text-slate-400">
              Driver: {primary_driver}
            </div>
          )}
        </div>

        {/* Vote pills */}
        <div className="mt-3 flex gap-2">
          <VotePill count={voteLong}  label="BELI"   color="#22c55e" />
          <VotePill count={voteShort} label="JUAL"   color="#ef4444" />
          <VotePill count={voteFlat}  label="TUNGGU" color="#64748b" />
        </div>
      </div>

      {/* Agents */}
      <div>
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">
          Pendapat 4 AI Agent
        </p>
        <div className="space-y-2">
          {agents.map((ag) => {
            const isLong  = ag.verdict === 'LONG'
            const isShort = ag.verdict === 'SHORT'
            const agColor = isLong ? '#22c55e' : isShort ? '#ef4444' : '#64748b'
            const agBg    = isLong ? 'bg-green-950/60 border-green-700/40'
                          : isShort ? 'bg-red-950/60 border-red-700/40'
                          : 'bg-slate-800/60 border-slate-700/40'

            return (
              <div key={ag.name} className={cn('rounded-2xl border p-3.5', agBg)}>
                <div className="flex justify-between items-center">
                  <p className="font-semibold text-sm">{humanizeAgent(ag.name)}</p>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold" style={{ color: agColor }}>
                      {ACTION_LABEL[ag.verdict]}
                    </span>
                    <span className="text-[11px] text-slate-400">{fmtPct(ag.confidence)}</span>
                  </div>
                </div>
                {ag.reasoning.length > 0 && (
                  <p className="text-xs text-slate-400 mt-1.5 leading-relaxed line-clamp-2">
                    {ag.reasoning.slice(0, 3).join(' · ')}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Reasoning chain */}
      {reasoning_chain?.length > 0 && (
        <details className="bg-slate-800/40 rounded-2xl border border-slate-700/40">
          <summary className="px-4 py-3 text-xs text-slate-400 cursor-pointer select-none font-semibold">
            🔗 Detail alur penalaran ({reasoning_chain.length} langkah)
          </summary>
          <div className="px-4 pb-4 space-y-1">
            {reasoning_chain.map((line, i) => (
              <p key={i} className="text-xs text-slate-300 leading-relaxed">• {line}</p>
            ))}
          </div>
        </details>
      )}

      {/* Risks */}
      {risks?.length > 0 && (
        <div className="bg-amber-950/30 border border-amber-700/30 rounded-2xl p-4">
          <p className="text-xs text-amber-400 font-semibold uppercase tracking-wide mb-2">
            ⚠️ Risiko Yang Dideteksi
          </p>
          {risks.map((r, i) => (
            <p key={i} className="text-xs text-amber-300/80 leading-relaxed">• {r}</p>
          ))}
        </div>
      )}
    </div>
  )
}

function VotePill({ count, label, color }: { count: number; label: string; color: string }) {
  return (
    <div
      className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-black/20"
      style={{ color }}
    >
      <span className="text-base leading-none">{count}</span>
      <span className="opacity-80">{label}</span>
    </div>
  )
}
