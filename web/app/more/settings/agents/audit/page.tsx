// Server Component — fetches last 20 cycles from agent_audit_recent view (or
// signal_bundles fallback), renders per-agent verdicts + engine stats.
import Link from 'next/link'
import { ArrowLeft, Activity, AlertTriangle, Cpu, Clock } from 'lucide-react'
import { supabaseGet } from '@/lib/server-api'

export const runtime = 'edge'

export const dynamic = 'force-dynamic'
export const revalidate = 30

interface AgentVerdictRow {
  name: string
  verdict: string
  confidence: number
  reasoning: string[]
  engine?: string
  latency_ms?: number
}

interface AuditRow {
  timestamp: string
  engine: string | null
  final_action: string | null
  confidence: number | null
  da_engine: string | null
  da_fallback_used: boolean | null
  total_latency_ms: number | null
  agent_verdicts: AgentVerdictRow[] | null
}

async function fetchAuditRows(): Promise<AuditRow[]> {
  // Try the convenience view first; fall back to direct signal_bundles select
  let rows = await supabaseGet<AuditRow[]>(
    'agent_audit_recent?select=*&limit=20',
    { revalidate: 30 },
  )
  if (!rows) {
    rows = await supabaseGet<AuditRow[]>(
      'signal_bundles?select=timestamp,debate,engine_meta,agent_verdicts&order=timestamp.desc&limit=20',
      { revalidate: 30 },
    )
    if (rows) {
      rows = rows.map(r => {
        const debate = (r as unknown as { debate?: { engine?: string; final_action?: string; confidence?: number } }).debate
        const meta = (r as unknown as { engine_meta?: { da_engine?: string; da_fallback_used?: boolean; total_latency_ms?: number } }).engine_meta
        return {
          timestamp:        r.timestamp,
          engine:           debate?.engine ?? null,
          final_action:     debate?.final_action ?? null,
          confidence:       debate?.confidence ?? null,
          da_engine:        meta?.da_engine ?? null,
          da_fallback_used: meta?.da_fallback_used ?? null,
          total_latency_ms: meta?.total_latency_ms ?? null,
          agent_verdicts:   r.agent_verdicts,
        }
      })
    }
  }
  return rows ?? []
}

export default async function AgentAuditPage() {
  const rows = await fetchAuditRows()
  const last = rows[0]

  // Aggregate stats over last 24h (or 20 cycles, whichever is less)
  const cutoffMs = Date.now() - 24 * 3600_000
  const recent = rows.filter(r => new Date(r.timestamp).getTime() >= cutoffMs)
  const total = recent.length
  const localCycles = recent.filter(r => r.engine === 'local-12-agent').length
  const llmCycles   = recent.filter(r => r.engine?.startsWith('llm')).length
  const fallbackCycles = recent.filter(r => r.da_fallback_used === true).length
  const avgLatency = recent.length > 0
    ? Math.round(recent.reduce((sum, r) => sum + (r.total_latency_ms || 0), 0) / recent.length)
    : 0

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings/agents" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-amber-700/30 border border-amber-600/30 flex items-center justify-center">
          <Activity size={16} className="text-amber-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Agent Audit</h1>
          <p className="text-[11px] text-slate-500">Last 20 cycles · per-agent verdict + fallback log.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Stats 24h */}
        <div className="bg-gradient-to-br from-slate-800/60 to-slate-900/60 rounded-2xl border border-slate-800 p-4">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-3">
            Stats 24 jam terakhir
          </p>
          <div className="grid grid-cols-4 gap-2 text-center">
            <Stat label="Cycle" value={`${total}`} />
            <Stat label="Local" value={`${localCycles}`} tone="ok" />
            <Stat label="LLM" value={`${llmCycles}`} tone={llmCycles > 0 ? 'amber' : undefined} />
            <Stat label="DA fallback" value={`${fallbackCycles}`} tone={fallbackCycles > 0 ? 'amber' : 'ok'} />
          </div>
          <p className="text-[10px] text-slate-500 mt-3 text-center">
            avg latency: <span className="font-mono text-slate-300">{avgLatency}ms</span>
          </p>
        </div>

        {/* Last cycle detail */}
        {last && last.agent_verdicts && last.agent_verdicts.length > 0 && (
          <section>
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
              Cycle terakhir ({fmtTime(last.timestamp)}Z)
            </p>
            <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden">
              <div className="px-3.5 py-3 border-b border-slate-800/80">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-100">
                    {last.final_action ?? '?'} · conf {((last.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                  <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                    last.engine === 'local-12-agent' ? 'bg-emerald-900/40 text-emerald-300' :
                    last.engine?.startsWith('llm') ? 'bg-sky-900/40 text-sky-300' :
                    'bg-slate-800 text-slate-400'
                  }`}>
                    {last.engine ?? 'unknown'}
                  </span>
                </div>
                <p className="text-[10px] text-slate-500 mt-1">
                  DA: {last.da_engine ?? '—'} {last.da_fallback_used ? '(fallback used)' : ''} · latency {last.total_latency_ms ?? 0}ms
                </p>
              </div>
              <div className="divide-y divide-slate-800/80">
                {last.agent_verdicts.map((v, i) => (
                  <div key={i} className="px-3.5 py-2.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs font-medium text-slate-100">{v.name}</span>
                        <span className={`text-[9px] font-bold uppercase tracking-wider px-1 py-0.5 rounded shrink-0 ${
                          v.verdict === 'LONG'   ? 'bg-emerald-900/40 text-emerald-300' :
                          v.verdict === 'SHORT'  ? 'bg-rose-900/40 text-rose-300' :
                                                   'bg-slate-800 text-slate-400'
                        }`}>
                          {v.verdict}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                        <span>{(v.confidence * 100).toFixed(0)}%</span>
                        {v.engine && v.engine !== 'local' && (
                          <span className="text-sky-400">{v.engine}</span>
                        )}
                        {v.latency_ms !== undefined && v.latency_ms > 0 && (
                          <span className="text-slate-600">{v.latency_ms}ms</span>
                        )}
                      </div>
                    </div>
                    {v.reasoning && v.reasoning.length > 0 && (
                      <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">
                        {v.reasoning.slice(0, 2).join(' · ')}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* History list — compact */}
        {rows.length > 1 && (
          <section>
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
              History 20 cycle
            </p>
            <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
              {rows.slice(1, 21).map((r, i) => (
                <div key={i} className="px-3.5 py-2 flex items-center gap-2 text-[10px] font-mono">
                  <Clock size={10} className="text-slate-600 shrink-0" />
                  <span className="text-slate-400 w-12 shrink-0">{fmtTime(r.timestamp)}</span>
                  <span className={`px-1 py-0.5 rounded shrink-0 ${
                    r.engine === 'local-12-agent' ? 'bg-emerald-900/40 text-emerald-400' :
                    r.engine?.startsWith('llm') ? 'bg-sky-900/40 text-sky-400' :
                                                  'bg-slate-800 text-slate-500'
                  }`}>
                    {r.engine === 'local-12-agent' ? 'local' :
                     r.engine?.startsWith('llm') ? 'llm' : '?'}
                  </span>
                  <span className={`shrink-0 ${
                    r.final_action === 'LONG'  ? 'text-emerald-300' :
                    r.final_action === 'SHORT' ? 'text-rose-300' :
                                                 'text-slate-500'
                  }`}>
                    {r.final_action ?? '—'}
                  </span>
                  <span className="text-slate-500 shrink-0">
                    {((r.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                  {r.da_fallback_used && (
                    <span className="text-amber-400 shrink-0 flex items-center gap-0.5">
                      <AlertTriangle size={9} /> DA fallback
                    </span>
                  )}
                  <span className="ml-auto text-slate-600 shrink-0">
                    {r.total_latency_ms ?? 0}ms
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {rows.length === 0 && (
          <div className="bg-slate-800/40 border border-slate-800 rounded-2xl p-6 text-center">
            <Cpu size={28} className="text-slate-500 mx-auto mb-2" />
            <p className="text-sm text-slate-300 mb-1">Belum ada audit data</p>
            <p className="text-[11px] text-slate-500 max-w-xs mx-auto leading-relaxed">
              Apply migration 016 di Supabase, restart daemon. Audit data muncul setelah cycle pertama dengan local agents.
            </p>
          </div>
        )}
      </div>
    </main>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'amber' }) {
  const color =
    tone === 'ok'    ? 'text-emerald-300' :
    tone === 'amber' ? 'text-amber-300'   : 'text-slate-100'
  return (
    <div className="bg-slate-900/40 rounded-lg px-2 py-1.5">
      <p className="text-[9px] text-slate-500 uppercase tracking-wide font-semibold">{label}</p>
      <p className={`text-base font-bold tabular-nums ${color}`}>{value}</p>
    </div>
  )
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return '?'
  }
}
