// RCS Monitor — Server Component fetches recent RCS signals + aggregates stats.
import Link from 'next/link'
import { ArrowLeft, Sparkles, TrendingUp, TrendingDown, Pause, AlertCircle, Activity } from 'lucide-react'
import { getRcsHistory, type RCSSignalRow, supabaseGet } from '@/lib/server-api'

export const runtime = 'edge'

export const revalidate = 30

interface RcsModelRow {
  id: number
  version: string
  timeframe: string
  model_type: string
  trained_at: string
  oos_accuracy: number | null
  oos_precision_long: number | null
  oos_precision_short: number | null
  oos_f1_macro: number | null
  num_features: number | null
  is_active: boolean
}

interface RcsExecutionRow {
  id: number
  signal_id: number
  status: string
  execution_lot: number
  execution_price: number | null
  pnl_money: number | null
  executed_at: string | null
  rejected_reason: string | null
}

export default async function RcsMonitorPage() {
  const [history, models, executions] = await Promise.all([
    getRcsHistory(50).catch(() => []),
    supabaseGet<RcsModelRow[]>('rcs_models?select=*&order=trained_at.desc&limit=5', { revalidate: 60 }).catch(() => null),
    supabaseGet<RcsExecutionRow[]>('rcs_executions?select=*&order=created_at.desc&limit=10', { revalidate: 30 }).catch(() => null),
  ])
  const latest = history[0] ?? null
  const activeModel = (models ?? []).find(m => m.is_active) ?? null

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

        {/* Active ML Model */}
        {(models && models.length > 0) && (
          <Section title="ML Model (v0.2 trained)">
            {activeModel ? (
              <div className="bg-emerald-950/30 border border-emerald-800/40 rounded-xl p-3 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] text-emerald-200">{activeModel.version}</span>
                  <span className="text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-emerald-700/40 text-emerald-200">ACTIVE</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Stat label="Acc OOS" value={`${((activeModel.oos_accuracy || 0) * 100).toFixed(1)}%`} tone="ok" />
                  <Stat label="Prec LONG" value={`${((activeModel.oos_precision_long || 0) * 100).toFixed(0)}%`} />
                  <Stat label="Prec SHORT" value={`${((activeModel.oos_precision_short || 0) * 100).toFixed(0)}%`} />
                </div>
              </div>
            ) : (
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Ada {(models ?? []).length} model trained, belum ada yang di-aktivasi.
                Set <span className="font-mono">is_active=true</span> di rcs_models lalu daemon akan auto-pickup.
              </p>
            )}
            <details className="mt-2">
              <summary className="text-[10px] text-slate-500 uppercase tracking-wider cursor-pointer">Riwayat training</summary>
              <div className="mt-1.5 space-y-1">
                {(models ?? []).slice(0, 5).map(m => (
                  <div key={m.id} className="flex items-center gap-2 text-[10px] bg-slate-900/40 border border-slate-800 rounded-lg px-2 py-1.5">
                    <span className="font-mono text-slate-400 truncate flex-1">{m.version}</span>
                    <span className="text-slate-500 shrink-0">{m.timeframe}</span>
                    <span className="text-emerald-400 shrink-0">{((m.oos_accuracy || 0) * 100).toFixed(1)}%</span>
                    {m.is_active && <span className="text-amber-400 shrink-0">★</span>}
                  </div>
                ))}
              </div>
            </details>
          </Section>
        )}

        {/* EA Execution log */}
        {(executions && executions.length > 0) && (
          <Section title="EA Executions (Phase v1.0)">
            <div className="space-y-1">
              {executions.slice(0, 5).map(e => (
                <div key={e.id} className="flex items-center gap-2 text-[10px] bg-slate-900/40 border border-slate-800 rounded-lg px-2 py-1.5">
                  <Activity size={10} className="text-violet-400 shrink-0" />
                  <span className="text-slate-400 shrink-0">#{e.signal_id}</span>
                  <span className={`font-bold shrink-0 ${
                    e.status === 'OPEN' ? 'text-emerald-400' :
                    e.status?.startsWith('CLOSED_TP') ? 'text-emerald-400' :
                    e.status === 'REJECTED' ? 'text-rose-400' :
                    e.status?.startsWith('CLOSED_SL') ? 'text-rose-400' : 'text-slate-400'
                  }`}>{e.status}</span>
                  <span className="text-slate-500 shrink-0">{e.execution_lot} lot</span>
                  {e.pnl_money !== null && (
                    <span className={`tabular-nums shrink-0 ${e.pnl_money >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {e.pnl_money >= 0 ? '+' : ''}${e.pnl_money.toFixed(2)}
                    </span>
                  )}
                  <span className="text-slate-600 ml-auto truncate">{e.rejected_reason || ''}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-slate-600 mt-2">
              EA polls FastAPI at home PC port 8001. Setup: lihat <span className="font-mono">rcs/ea/DextradeEA.mq5</span>.
            </p>
          </Section>
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
              <span className="font-bold">v0.1</span> = manual heuristic weights (DEPLOYED, default jalan).<br/>
              <span className="font-bold">v0.2</span> = ML XGBoost on cross-TF features (built, opt-in lewat env var).<br/>
              <span className="font-bold">v0.3</span> = drift detection (built, runs each cycle).<br/>
              <span className="font-bold">v1.0</span> = MT5 EA auto-execute (built, scaffold, EnableExecution=false default).
            </p>
          </div>
        </Section>

        {/* Tutorial: Train ML model */}
        <Section title="Tutorial · Train ML model XGBoost (Phase v0.2)">
          <div className="text-[11px] text-slate-400 leading-relaxed space-y-2">
            <p>
              <span className="font-semibold text-slate-200">Realita:</span> v0.1 heuristic udah jalan tanpa training. ML model ini OPTIONAL — buat naikin akurasi dari ~50% (heuristic) ke 51-55% (ML XGBoost).
            </p>
            <p className="text-slate-300 font-semibold">Step-by-step di PC rumah lo:</p>
            <ol className="list-decimal pl-4 space-y-1.5">
              <li>Buka PowerShell di PC rumah → <span className="font-mono bg-slate-900 px-1 rounded">Set-Location $HOME\yeehee-daemon</span></li>
              <li>Install ML deps (1× saja):
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono mt-1 overflow-x-auto">.\.venv\Scripts\python.exe -m pip install -r rcs\requirements.txt</pre>
              </li>
              <li>Train M15 dengan Optuna (recommended, 1-2 menit):
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono mt-1 overflow-x-auto">.\.venv\Scripts\python.exe -m rcs.src.training --tf M15 --optuna --push</pre>
              </li>
              <li>Tunggu sampai output <span className="font-mono">"=== TRAINING COMPLETE ==="</span>. Lihat <span className="font-mono">xgb_oos_accuracy</span> — target 47-55%.</li>
              <li>Refresh halaman ini → riwayat training muncul di section <span className="font-bold">ML Model</span> di atas.</li>
              <li>Kalau accuracy ≥ 47% dan lo puas: aktivasi via Supabase SQL editor:
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono mt-1 overflow-x-auto">UPDATE rcs_models SET is_active=true WHERE version='xgb_M15_...';</pre>
              </li>
              <li>Tambah ke daemon <span className="font-mono">.env</span>:
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono mt-1 overflow-x-auto">RCS_USE_ML=1</pre>
              </li>
              <li>Restart daemon. Cycle berikutnya RCS akan pakai prediksi ML.</li>
            </ol>
            <details className="mt-2">
              <summary className="cursor-pointer text-slate-300 font-semibold">Train pakai data MT5 (lebih akurat tapi butuh setup MT5 client)</summary>
              <div className="mt-2 space-y-1.5">
                <p>Install MetaTrader5 di PC rumah lo (gratis), login demo/live broker, lalu:</p>
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono overflow-x-auto">.\.venv\Scripts\python.exe -m pip install MetaTrader5
# Tambah ke .env: MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
.\.venv\Scripts\python.exe -m rcs.src.training --tf M15 --source mt5 --optuna --trials 50 --push</pre>
                <p>Data 3+ tahun = lebih banyak sample = ML edge lebih real. Target accuracy: 53-58%.</p>
              </div>
            </details>
            <p className="text-amber-300/80 mt-2">
              ⚠️ Kalau accuracy {'>'}65%, kemungkinan besar OVERFIT. Jangan deploy. Kerja-in retrain dengan walk-forward CV.
            </p>
          </div>
        </Section>

        {/* Tutorial: MT5 EA auto-execute */}
        <Section title="Tutorial · MT5 EA auto-execute (Phase v1.0)">
          <div className="text-[11px] text-slate-400 leading-relaxed space-y-2">
            <p>
              <span className="font-semibold text-amber-300">⚠️ Advanced — JANGAN aktifkan kalau belum 30 hari paper test.</span>
            </p>
            <p>EA = bot di MT5 yang auto-execute order pas RCS kasih signal high-conf. Komponennya:</p>
            <ol className="list-decimal pl-4 space-y-1.5 mt-2">
              <li><span className="font-bold">FastAPI di PC rumah</span> — endpoint EA polling. Run dengan:
                <pre className="bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-[10px] text-slate-300 font-mono mt-1 overflow-x-auto">.\.venv\Scripts\python.exe -m rcs.src.execution_api</pre>
                Default port 8001. Test: <span className="font-mono">curl http://localhost:8001/healthz</span>
              </li>
              <li><span className="font-bold">EA file</span> — di repo: <span className="font-mono">rcs/ea/DextradeEA.mq5</span>
                <ul className="list-disc pl-4 mt-1 space-y-0.5 text-slate-500">
                  <li>Buka MT5 client → Navigator → Expert Advisors → Klik kanan → New (atau import file)</li>
                  <li>Paste isi <span className="font-mono">DextradeEA.mq5</span></li>
                  <li>F7 untuk compile (cek "0 errors" di bottom)</li>
                </ul>
              </li>
              <li><span className="font-bold">Whitelist URL</span>: MT5 → Tools → Options → Expert Advisors → Allow URL: <span className="font-mono">http://localhost:8001</span></li>
              <li><span className="font-bold">Drag EA ke chart XAUUSD</span>. Inputs:
                <ul className="list-disc pl-4 mt-1 space-y-0.5 text-slate-500">
                  <li><span className="font-mono">EnableExecution=false</span> + <span className="font-mono">EnablePaperMode=true</span> awalnya</li>
                  <li>Run paper mode 1-2 minggu, observe Tab Experts logs</li>
                  <li>Setelah confidence: switch <span className="font-mono">EnablePaperMode=false</span> + <span className="font-mono">EnableExecution=true</span></li>
                </ul>
              </li>
              <li><span className="font-bold">Promote signals to PENDING_PICKUP</span> (manual or auto-rule). EA cuma pickup signals dengan <span className="font-mono">execution_status='PENDING_PICKUP' AND is_executable=true</span>.</li>
            </ol>
            <p className="text-amber-300/80 mt-2 font-semibold">Safety defaults yang bagus untuk start:</p>
            <ul className="list-disc pl-4 text-amber-200/70 space-y-0.5">
              <li>RiskPercentPerTrade = 0.5% (jangan langsung 1%+)</li>
              <li>MaxOpenPositions = 1</li>
              <li>DailyLossPct = 3% kill switch</li>
              <li>MinConfidencePct = 70% (filter low-conf signals)</li>
            </ul>
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
