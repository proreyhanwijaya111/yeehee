'use client'
import { useState } from 'react'
import { runBacktest } from '@/lib/api'
import type { BacktestResult } from '@/lib/types'
import { cn, fmtUSD } from '@/lib/utils'
import { InlineLoader } from '@/components/LoadingSpinner'

const INTERVALS = ['1h', '4h', '1d']

export default function BacktestPage() {
  const [interval, setInterval] = useState('4h')
  const [equity,   setEquity]   = useState(10_000)
  const [riskPct,  setRiskPct]  = useState(1.0)
  const [mcRuns,   setMcRuns]   = useState(10_000)
  const [loading,  setLoading]  = useState(false)
  const [result,   setResult]   = useState<BacktestResult | null>(null)
  const [err,      setErr]      = useState('')

  const handleRun = async () => {
    setLoading(true)
    setErr('')
    try {
      const r = await runBacktest({
        interval,
        starting_equity: equity,
        risk_per_trade: riskPct / 100,
        mc_runs: mcRuns,
      })
      setResult(r)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Backtest gagal')
    } finally {
      setLoading(false)
    }
  }

  const mc = result?.monte_carlo

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <h1 className="text-lg font-black text-slate-100">🔬 Test Strategi</h1>

      {/* Config */}
      <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50 space-y-3">
        <div>
          <p className="text-xs text-slate-400 mb-2">Timeframe</p>
          <div className="flex gap-2">
            {INTERVALS.map(iv => (
              <button
                key={iv}
                onClick={() => setInterval(iv)}
                className={cn(
                  'flex-1 py-2 rounded-xl text-sm font-semibold transition-all touch-action',
                  interval === iv ? 'bg-sky-600 text-white' : 'bg-slate-700/50 text-slate-300',
                )}
              >
                {iv}
              </button>
            ))}
          </div>
        </div>

        <label className="block">
          <span className="text-xs text-slate-400">Modal Awal (USD)</span>
          <input
            type="number"
            value={equity}
            onChange={e => setEquity(Number(e.target.value))}
            className="mt-1 w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
          />
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Risk per trade: {riskPct.toFixed(1)}%</span>
          <input
            type="range"
            min={0.1} max={5} step={0.1}
            value={riskPct}
            onChange={e => setRiskPct(Number(e.target.value))}
            className="w-full mt-1 accent-sky-500"
          />
        </label>

        <div>
          <p className="text-xs text-slate-400 mb-2">Monte Carlo Runs</p>
          <div className="flex gap-2">
            {[5_000, 10_000, 50_000].map(n => (
              <button
                key={n}
                onClick={() => setMcRuns(n)}
                className={cn(
                  'flex-1 py-2 rounded-xl text-xs font-semibold transition-all touch-action',
                  mcRuns === n ? 'bg-sky-600 text-white' : 'bg-slate-700/50 text-slate-300',
                )}
              >
                {n.toLocaleString()}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button
        onClick={handleRun}
        disabled={loading}
        className="w-full py-3.5 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white font-bold rounded-2xl transition-all touch-action disabled:opacity-50"
      >
        {loading ? '⏳ Menjalankan simulasi...' : '🚀 Jalankan Backtest'}
      </button>

      {loading && <InlineLoader />}
      {err && <p className="text-red-400 text-sm text-center">{err}</p>}

      {result && (
        <div className="space-y-3 animate-fade-in">
          <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">
            Hasil — {result.n_bars} bar data, {result.stats.n_trades} trade
          </p>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-2">
            <StatCard label="Win Rate"     value={`${(result.stats.win_rate * 100).toFixed(1)}%`} />
            <StatCard label="Expectancy"   value={`${result.stats.expectancy_r.toFixed(2)} R`} />
            <StatCard label="Total Return" value={`${result.stats.total_return_pct.toFixed(1)}%`} green={result.stats.total_return_pct > 0} />
            <StatCard label="Max Drawdown" value={`${result.stats.max_drawdown_pct.toFixed(1)}%`} red />
            <StatCard label="Sharpe"       value={result.stats.sharpe.toFixed(2)} green={result.stats.sharpe > 1} />
            <StatCard label="Jumlah Trade" value={String(result.stats.n_trades)} />
          </div>

          {/* Monte Carlo */}
          {mc && (
            <>
              <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mt-2">
                Monte Carlo ({mcRuns.toLocaleString()} simulasi)
              </p>
              <div className="grid grid-cols-2 gap-2">
                <StatCard label="Median Akhir"   value={fmtUSD(mc.final_equity_p50)} sub={`+${((mc.final_equity_p50 / mc.starting_equity - 1) * 100).toFixed(1)}%`} green />
                <StatCard label="P5 (Terburuk)"  value={fmtUSD(mc.final_equity_p5)} red />
                <StatCard label="P95 (Terbaik)"  value={fmtUSD(mc.final_equity_p95)} green />
                <StatCard label="Prob Profit"    value={`${(mc.prob_profit * 100).toFixed(1)}%`} green={mc.prob_profit > 0.5} />
                <StatCard label="Prob DD >30%"   value={`${(mc.prob_30pct_dd * 100).toFixed(1)}%`} red={mc.prob_30pct_dd > 0.3} />
                <StatCard label="Prob Blowup"    value={`${(mc.prob_blowup * 100).toFixed(1)}%`} red={mc.prob_blowup > 0.05} />
              </div>
            </>
          )}

          <p className="text-xs text-slate-600 text-center">
            ⚠️ Past performance ≠ future result
          </p>
        </div>
      )}
    </main>
  )
}

function StatCard({ label, value, sub, green, red }: {
  label: string; value: string; sub?: string; green?: boolean; red?: boolean
}) {
  return (
    <div className="bg-slate-800/60 rounded-xl border border-slate-700/40 px-3 py-2.5">
      <p className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</p>
      <p className={cn(
        'text-sm font-bold tabular-nums mt-0.5',
        green ? 'text-green-400' : red ? 'text-red-400' : 'text-slate-100',
      )}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}
