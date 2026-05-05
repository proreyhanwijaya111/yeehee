'use client'
import { useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, FlaskConical, Play, Loader2, AlertCircle,
  TrendingUp, TrendingDown, Activity, Target, Shield,
} from 'lucide-react'
import { runBacktest, type MCBacktestResult } from '@/lib/api'
import { fmtUSD, cn } from '@/lib/utils'

type Preset = '5k' | '10k' | '50k'
const PRESET_RUNS: Record<Preset, number> = { '5k': 5000, '10k': 10000, '50k': 50000 }

export default function BacktestPage() {
  const [equity,    setEquity]    = useState('10000')
  const [riskPct,   setRiskPct]   = useState(1.0)
  const [winRate,   setWinRate]   = useState(50)
  const [avgWinR,   setAvgWinR]   = useState(1.5)
  const [avgLossR,  setAvgLossR]  = useState(1.0)
  const [nTrades,   setNTrades]   = useState(100)
  const [preset,    setPreset]    = useState<Preset>('10k')
  const [loading,   setLoading]   = useState(false)
  const [result,    setResult]    = useState<MCBacktestResult | null>(null)
  const [err,       setErr]       = useState('')

  const equityNum = Number(equity) || 0
  const expectancy = (winRate / 100) * avgWinR - (1 - winRate / 100) * avgLossR
  const cleanNum = (v: string) => v.replace(/[^\d.]/g, '').replace(/^0+(?=\d)/, '')

  const handleRun = async () => {
    setLoading(true)
    setErr('')
    setResult(null)
    try {
      const r = await runBacktest({
        starting_equity: equityNum,
        risk_per_trade:  riskPct / 100,
        n_runs:          PRESET_RUNS[preset],
        n_trades:        nTrades,
        win_rate:        winRate / 100,
        avg_win_r:       avgWinR,
        avg_loss_r:      -Math.abs(avgLossR),
      })
      setResult(r)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Gagal jalankan backtest')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-sky-700/30 border border-sky-600/30 flex items-center justify-center">
          <FlaskConical size={16} className="text-sky-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Test strategi</h1>
          <p className="text-[11px] text-slate-500">Monte Carlo bootstrap — simulasi outcome equity.</p>
        </div>
      </header>

      <div className="space-y-5">
        <Group title="Modal & Risk">
          <Field label="Modal awal (USD)">
            <input
              type="text"
              inputMode="numeric"
              value={equity}
              onChange={e => setEquity(cleanNum(e.target.value))}
              placeholder="10000"
              className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500 tabular-nums"
            />
          </Field>
          <Slider
            label="Risk per trade" unit="%"
            value={riskPct} min={0.1} max={5.0} step={0.1}
            onChange={setRiskPct} format={v => v.toFixed(1)}
          />
        </Group>

        <Group title="Asumsi strategi">
          <Slider
            label="Win rate" unit="%"
            value={winRate} min={30} max={70} step={1}
            onChange={setWinRate} format={v => v.toFixed(0)}
            help="Persentase trade profit. 50% = adil, 60%+ = strategi unggul."
          />
          <Slider
            label="Avg Win" unit="R"
            value={avgWinR} min={0.5} max={5.0} step={0.1}
            onChange={setAvgWinR} format={v => v.toFixed(1)}
            help="Rata-rata profit per trade dalam R-multiple."
          />
          <Slider
            label="Avg Loss" unit="R"
            value={avgLossR} min={0.5} max={3.0} step={0.1}
            onChange={setAvgLossR} format={v => v.toFixed(1)}
            help="Rata-rata loss per trade. 1R = SL hit penuh."
          />
          <Slider
            label="Trades per path" unit=""
            value={nTrades} min={20} max={500} step={10}
            onChange={setNTrades} format={v => v.toFixed(0)}
            help="Berapa trade per simulasi path. 100 = ~1 bulan intraday."
          />

          <div className="px-3.5 py-2.5 flex items-center justify-between">
            <span className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Expectancy</span>
            <span className={cn(
              'text-sm font-mono font-bold tabular-nums',
              expectancy > 0.1 ? 'text-emerald-300' : expectancy < -0.1 ? 'text-rose-300' : 'text-slate-300',
            )}>
              {expectancy > 0 ? '+' : ''}{expectancy.toFixed(2)} R/trade
            </span>
          </div>
        </Group>

        <Group title="Monte Carlo runs">
          <div className="px-3.5 py-3">
            <div className="grid grid-cols-3 gap-px bg-slate-800/80 rounded-lg overflow-hidden p-px">
              {(['5k', '10k', '50k'] as Preset[]).map(p => (
                <button
                  key={p}
                  onClick={() => setPreset(p)}
                  className={cn(
                    'py-2 px-3 text-xs font-semibold transition-colors rounded-[6px]',
                    preset === p ? 'bg-sky-900/40 text-sky-100' : 'bg-slate-900/40 text-slate-400 hover:text-slate-200',
                  )}
                >
                  {p === '5k' ? '5,000' : p === '10k' ? '10,000' : '50,000'}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
              Total {(PRESET_RUNS[preset] * nTrades / 1_000_000).toFixed(1)}M trades disimulasiin via Vercel Edge.
            </p>
          </div>
        </Group>

        <button
          onClick={handleRun}
          disabled={loading || !equityNum}
          className="w-full py-3 rounded-xl text-sm font-semibold bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          {loading ? `Running ${PRESET_RUNS[preset].toLocaleString()} sims...` : 'Jalankan backtest'}
        </button>

        {err && (
          <div className="bg-rose-950/40 border border-rose-800/40 rounded-lg px-3 py-2 flex items-start gap-2">
            <AlertCircle size={14} className="text-rose-400 shrink-0 mt-0.5" />
            <p className="text-xs text-rose-300">{err}</p>
          </div>
        )}

        {result && <ResultBlock r={result} />}
      </div>
    </main>
  )
}

function ResultBlock({ r }: { r: MCBacktestResult }) {
  const isProfitable = r.expected_return_pct > 0
  const fe = r.percentiles.final_equity
  const dd = r.percentiles.max_drawdown
  const p  = r.probabilities

  return (
    <div className="space-y-4 animate-fade-in">
      <Group title="Hasil utama">
        <div className="px-3.5 py-3 grid grid-cols-2 gap-3">
          <Metric
            icon={isProfitable ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            label="Expected return"
            value={`${r.expected_return_pct >= 0 ? '+' : ''}${r.expected_return_pct.toFixed(1)}%`}
            tone={isProfitable ? 'ok' : 'bad'}
          />
          <Metric
            icon={<Target size={14} />}
            label="Expectancy"
            value={`${r.expectancy_r >= 0 ? '+' : ''}${r.expectancy_r.toFixed(2)} R`}
            tone={r.expectancy_r > 0.1 ? 'ok' : r.expectancy_r < -0.1 ? 'bad' : 'neutral'}
          />
        </div>
      </Group>

      <Group title="Distribusi equity akhir">
        <div className="px-3.5 py-3 space-y-2.5">
          <Bar label="Worst 5%"  value={fe.p5}  base={r.inputs.starting_equity} />
          <Bar label="P25"       value={fe.p25} base={r.inputs.starting_equity} />
          <Bar label="Median"    value={fe.p50} base={r.inputs.starting_equity} highlight />
          <Bar label="P75"       value={fe.p75} base={r.inputs.starting_equity} />
          <Bar label="Best 5%"   value={fe.p95} base={r.inputs.starting_equity} />
        </div>
      </Group>

      <Group title="Max drawdown">
        <div className="px-3.5 py-3 grid grid-cols-3 gap-3">
          <Metric icon={<Shield size={14} />} label="Best case (P5)"  value={`${dd.p5.toFixed(1)}%`}  tone="ok" />
          <Metric icon={<Activity size={14}/>} label="Median"          value={`${dd.p50.toFixed(1)}%`} tone="neutral" />
          <Metric icon={<Activity size={14}/>} label="Worst (P95)"    value={`${dd.p95.toFixed(1)}%`} tone="bad" />
        </div>
      </Group>

      <Group title="Probabilitas">
        <div className="px-3.5 py-3 grid grid-cols-2 gap-3">
          <Metric label="Profit"        value={`${(p.profit       * 100).toFixed(1)}%`} tone={p.profit > 0.5 ? 'ok' : 'bad'} />
          <Metric label="DD > 30%"      value={`${(p.drawdown_30  * 100).toFixed(1)}%`} tone={p.drawdown_30 < 0.10 ? 'ok' : p.drawdown_30 < 0.30 ? 'neutral' : 'bad'} />
          <Metric label="DD > 50%"      value={`${(p.drawdown_50  * 100).toFixed(1)}%`} tone={p.drawdown_50 < 0.05 ? 'ok' : 'bad'} />
          <Metric label="Blowup (>50%)" value={`${(p.blowup       * 100).toFixed(1)}%`} tone={p.blowup < 0.05 ? 'ok' : 'bad'} />
        </div>
      </Group>

      <div className="bg-amber-950/20 border border-amber-900/40 rounded-xl px-3 py-2.5">
        <p className="text-[11px] text-amber-300 leading-relaxed">
          ⚠️ <span className="font-semibold">Disclaimer:</span> simulasi pakai bernoulli win/loss + uniform noise.
          Belum model tail events (NFP/FOMC spike) atau streak regime — hasil cenderung optimistic.
          Real gold returns fat-tailed. Pakai sebagai sanity check, bukan precise prediction.
        </p>
      </div>
      <p className="text-[10px] text-slate-500 text-center">
        {r.n_runs.toLocaleString()} simulasi · {r.duration_ms}ms · Vercel Edge
      </p>
    </div>
  )
}

function Bar({ label, value, base, highlight }: {
  label: string; value: number; base: number; highlight?: boolean
}) {
  const pct  = (value / base - 1) * 100
  const isUp = pct >= 0
  const widthPct = Math.min(100, Math.abs(pct) / 200 * 100 + 5)
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] mb-0.5">
        <span className={cn('text-slate-400', highlight && 'text-slate-200 font-bold')}>{label}</span>
        <span className={cn(
          'font-mono tabular-nums',
          isUp ? 'text-emerald-300' : 'text-rose-300',
          highlight && 'font-bold',
        )}>
          {fmtUSD(value)}  ({isUp ? '+' : ''}{pct.toFixed(1)}%)
        </span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            isUp ? 'bg-emerald-500' : 'bg-rose-500',
            highlight ? 'opacity-100' : 'opacity-60',
          )}
          style={{ width: `${widthPct}%` }}
        />
      </div>
    </div>
  )
}

function Metric({ icon, label, value, tone }: {
  icon?: React.ReactNode; label: string; value: string; tone?: 'ok' | 'bad' | 'neutral'
}) {
  const color = tone === 'ok' ? 'text-emerald-300' : tone === 'bad' ? 'text-rose-300' : 'text-slate-100'
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[10px] text-slate-500 uppercase tracking-wide">
        {icon}<span>{label}</span>
      </div>
      <p className={cn('text-sm font-bold tabular-nums mt-0.5', color)}>{value}</p>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">{title}</p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
        {children}
      </div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block px-3.5 py-2.5">
      <span className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function Slider({ label, unit, value, min, max, step, onChange, format, help }: {
  label: string
  unit:  string
  value: number
  min:   number
  max:   number
  step:  number
  onChange: (v: number) => void
  format: (v: number) => string
  help?: string
}) {
  return (
    <div className="px-3.5 py-2.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">{label}</span>
        <span className="text-sm font-mono text-slate-100 tabular-nums">{format(value)}{unit}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full accent-sky-500"
      />
      {help && <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">{help}</p>}
    </div>
  )
}
