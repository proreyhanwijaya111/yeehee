// RCS Monitor — Server Component fetches recent RCS signals + aggregates stats.
import Link from 'next/link'
import { ArrowLeft, Sparkles, TrendingUp, TrendingDown, Pause, AlertCircle } from 'lucide-react'
import { getRcsHistory, type RCSSignalRow } from '@/lib/server-api'

export const revalidate = 30

export default async function RcsMonitorPage() {
  const history = await getRcsHistory(50).catch(() => [])
  const latest  = history[0] ?? null

  // Aggregate stats (across all rows for now; Phase 9 will use rcs_performance_daily)
  const total       = history.length
  const longCount   = history.filter(r => r.direction === 'LONG').length
  const shortCount  = history.filter(r => r.direction === 'SHORT').length
  const waitCount   = history.filter(r => r.direction === 'WAIT').length
  const avgConf     = total > 0 ? history.reduce((a, r) => a + (r.confidence_pct || 0), 0) / total : 0
  const withOutcome = history.filter(r => r.outcome && r.outcome !== 'PENDING')
  const correct     = withOutcome.filter(r => r.prediction_correct === true).length
  const directionalAcc = withOutcome.length > 0 ? (correct / withOutcome.length) * 100 : null

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/40 flex items-center justify-center">
          <Sparkles size={16} className="text-violet-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">RCS Monitor</h1>
          <p className="text-[11px] text-slate-500">Composite indicator — kombinasi semua signal jadi satu referensi.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Status banner */}
        {total === 0 ? (
          <div className="bg-amber-950/30 border border-amber-700/40 rounded-2xl p-4 flex gap-3">
            <AlertCircle size={20} className="text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-amber-100">Belum ada data RCS</p>
              <p className="text-[11px] text-amber-200/70 mt-1 leading-relaxed">
                Daemon belum push RCS cycle. Pastikan:
                (1) Migration 008 di Supabase sudah di-apply,
                (2) Daemon di PC rumah pakai code latest dengan <span className="font-mono">rcs/</span> folder,
                (3) Daemon sudah restart minimal sekali.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Latest signal — big card */}
            {latest && <LatestRcsCard latest={latest} />}

            {/* Aggregate stats */}
            <Section title="Statistik 50 sinyal terakhir">
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Total" value={String(total)} />
                <Stat label="Avg conf" value={`${avgConf.toFixed(0)}%`} />
                <Stat label="Akurasi"
                      value={directionalAcc !== null ? `${directionalAcc.toFixed(0)}%` : '–'}
                      hint={`${withOutcome.length} sample`} />
              </div>
              <div className="grid grid-cols-3 gap-2 mt-2">
                <Stat label="LONG"  value={String(longCount)}  tone="ok" />
                <Stat label="SHORT" value={String(shortCount)} tone="bad" />
                <Stat label="WAIT"  value={String(waitCount)}  tone="neutral" />
              </div>
            </Section>

            {/* Recent history */}
            <Section title="Riwayat (10 terbaru)">
              <div className="space-y-1.5">
                {history.slice(0, 10).map(row => <HistoryRow key={row.id} row={row} />)}
              </div>
            </Section>
          </>
        )}

        <Section title="Apa itu RCS?">
          <div className="space-y-2 text-[11px] text-slate-400 leading-relaxed">
            <p>
              <span className="font-bold text-violet-300">RCS</span> (REY Composite Signal) =
              indikator pamungkas yang gabungin <span className="font-mono">trend, momentum, structure (SMC),
              intermarket, volatility, session</span> jadi satu score tunggal di range [-1, +1].
            </p>
            <p>
              Output dipakai sebagai <span className="font-bold">referensi tambahan</span> untuk sistem 12-agent LLM
              (bukan replacement). Score &gt; +0.40 = LONG kuat, &lt; -0.40 = SHORT kuat, di antara = WAIT.
            </p>
            <p className="text-slate-500">
              <span className="font-bold">v0.1</span> = manual heuristic weights.
              <span className="font-bold"> v0.2 (future)</span> = ML-fit weights via XGBoost on historical outcome.
              <span className="font-bold"> v1.0 (future)</span> = MT5 EA auto-execute trades based on RCS.
            </p>
          </div>
        </Section>
      </div>
    </main>
  )
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function LatestRcsCard({ latest }: { latest: RCSSignalRow }) {
  const score    = latest.rcs_score
  const isLong   = latest.direction === 'LONG'
  const isShort  = latest.direction === 'SHORT'
  const dirColor =
    isLong  ? 'text-emerald-300' :
    isShort ? 'text-rose-300'    : 'text-slate-400'
  const dirIcon  = isLong  ? <TrendingUp size={20} /> :
                   isShort ? <TrendingDown size={20} /> :
                             <Pause size={20} />
  const time = new Date(latest.generated_at).toLocaleString('id-ID', {
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short',
  })

  return (
    <div className="bg-violet-950/30 border border-violet-800/50 rounded-2xl p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[10px] text-violet-400/80 uppercase tracking-wider font-semibold">Sinyal terkini</p>
          <p className="text-[10px] text-violet-300/60 mt-0.5">{time} · {latest.timeframe} · {latest.broker_symbol}</p>
        </div>
        <div className="text-right">
          <p className="text-[9px] text-violet-400/70 uppercase tracking-wider">Model</p>
          <p className="text-[10px] text-violet-300/70 font-mono">{latest.model_version}</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className={`flex items-center gap-1.5 ${dirColor}`}>
          {dirIcon}
          <span className="text-2xl font-black">{latest.direction}</span>
        </div>
        <div className="flex-1 text-right">
          <p className={`text-3xl font-black tabular-nums ${
            score > 0 ? 'text-emerald-300' : score < 0 ? 'text-rose-300' : 'text-slate-400'
          }`}>
            {score >= 0 ? '+' : ''}{score.toFixed(3)}
          </p>
          <p className="text-[10px] text-violet-300/60 uppercase tracking-wider mt-0.5">
            {latest.confidence_pct}% confidence
          </p>
        </div>
      </div>

      {/* Probability breakdown */}
      <div className="mt-3 pt-3 border-t border-violet-800/40 space-y-1">
        <div className="flex h-1.5 rounded-full overflow-hidden bg-slate-800">
          <div className="bg-emerald-500" style={{ width: `${latest.prob_long * 100}%` }} />
          <div className="bg-slate-500"   style={{ width: `${latest.prob_neutral * 100}%` }} />
          <div className="bg-rose-500"    style={{ width: `${latest.prob_short * 100}%` }} />
        </div>
        <div className="flex justify-between text-[10px] tabular-nums">
          <span className="text-emerald-400">LONG {(latest.prob_long * 100).toFixed(0)}%</span>
          <span className="text-slate-400">NEU {(latest.prob_neutral * 100).toFixed(0)}%</span>
          <span className="text-rose-400">SHORT {(latest.prob_short * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Top drivers */}
      {latest.shap_top_5?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-violet-800/40">
          <p className="text-[10px] text-violet-400/70 uppercase tracking-wider font-semibold mb-1.5">Driver utama</p>
          <div className="space-y-1">
            {latest.shap_top_5.slice(0, 3).map((d, i) => (
              <div key={i} className="flex items-baseline justify-between text-[11px]">
                <span className="text-violet-200/80 truncate flex-1">
                  <span className="font-bold">{d.name}</span>
                  <span className="text-violet-200/50 ml-1.5">{d.detail}</span>
                </span>
                <span className={`font-mono tabular-nums ml-2 shrink-0 ${
                  d.contribution > 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}>
                  {d.contribution >= 0 ? '+' : ''}{d.contribution.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function HistoryRow({ row }: { row: RCSSignalRow }) {
  const time = new Date(row.generated_at).toLocaleString('id-ID', {
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short',
  })
  const dirColor =
    row.direction === 'LONG'  ? 'text-emerald-400' :
    row.direction === 'SHORT' ? 'text-rose-400'    : 'text-slate-500'
  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-lg px-3 py-2 flex items-center gap-2 text-[11px]">
      <span className="text-slate-500 font-mono w-20 shrink-0">{time}</span>
      <span className="text-slate-600 w-8 shrink-0">{row.timeframe}</span>
      <span className={`font-bold w-12 shrink-0 ${dirColor}`}>{row.direction}</span>
      <span className={`font-mono tabular-nums shrink-0 ${
        row.rcs_score > 0 ? 'text-emerald-400' : row.rcs_score < 0 ? 'text-rose-400' : 'text-slate-500'
      }`}>
        {row.rcs_score >= 0 ? '+' : ''}{row.rcs_score.toFixed(2)}
      </span>
      <span className="text-slate-600 ml-auto">{row.confidence_pct}%</span>
      {row.outcome && row.outcome !== 'PENDING' && (
        <span className={`text-[9px] uppercase font-bold px-1.5 py-0.5 rounded shrink-0 ${
          row.prediction_correct ? 'bg-emerald-900/40 text-emerald-300' : 'bg-rose-900/40 text-rose-300'
        }`}>
          {row.outcome}
        </span>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">{title}</p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 px-3.5 py-3">
        {children}
      </div>
    </section>
  )
}

function Stat({ label, value, tone, hint }: {
  label: string; value: string; tone?: 'ok' | 'bad' | 'neutral'; hint?: string
}) {
  const valueColor =
    tone === 'ok'  ? 'text-emerald-300' :
    tone === 'bad' ? 'text-rose-300'    : 'text-slate-100'
  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-lg px-2.5 py-2">
      <p className="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">{label}</p>
      <p className={`text-base font-bold tabular-nums mt-0.5 ${valueColor}`}>{value}</p>
      {hint && <p className="text-[9px] text-slate-600 mt-0.5">{hint}</p>}
    </div>
  )
}
