'use client'
import { useState } from 'react'
import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { getSignals, calcPosition } from '@/lib/api'
import type { PositionPlan, RiskProfile } from '@/lib/types'
import { PROFILE_LABEL, fmtUSD, fmtPrice, cn } from '@/lib/utils'
import LoadingSpinner from '@/components/LoadingSpinner'

const PROFILES: RiskProfile[] = ['konservatif', 'moderat', 'agresif', 'bebas']
const RISK_MAP: Record<RiskProfile, number> = {
  konservatif: 0.005,
  moderat:     0.010,
  agresif:     0.020,
  bebas:       0.050,
}

export default function CalculatorPage() {
  const { data: bundle } = useSWR('signals', () => getSignals('signals'))

  const [equity,    setEquity]   = useState(10_000)
  const [profile,   setProfile]  = useState<RiskProfile>('moderat')
  const [leverage,  setLeverage] = useState(100)
  const [sigSrc,    setSigSrc]   = useState<'intraday'|'scalper'|'swing'|'manual'>('intraday')
  const [entry,     setEntry]    = useState(0)
  const [sl,        setSl]       = useState(0)
  const [tp1,       setTp1]      = useState(0)
  const [tp2,       setTp2]      = useState(0)
  const [tp3,       setTp3]      = useState(0)
  const [side,      setSide]     = useState<'LONG'|'SHORT'>('LONG')
  const [plan,      setPlan]     = useState<PositionPlan | null>(null)
  const [loading,   setLoading]  = useState(false)
  const [err,       setErr]      = useState('')

  // Get levels from selected signal
  const sigMap = {
    intraday: bundle?.intraday_signal,
    scalper:  bundle?.scalper_signal,
    swing:    bundle?.swing_signal,
  }
  const selectedSig = sigSrc !== 'manual' ? sigMap[sigSrc] : null

  const resolvedEntry = sigSrc !== 'manual' && selectedSig ? selectedSig.entry : entry
  const resolvedSl    = sigSrc !== 'manual' && selectedSig ? selectedSig.sl    : sl
  const resolvedTp1   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp1   : tp1
  const resolvedTp2   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp2   : tp2
  const resolvedTp3   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp3   : tp3
  const resolvedSide  = sigSrc !== 'manual' && selectedSig && selectedSig.side !== 'FLAT'
    ? selectedSig.side as 'LONG'|'SHORT'
    : side

  const handleCalc = async () => {
    setLoading(true)
    setErr('')
    try {
      const result = await calcPosition({
        equity_usd: equity,
        entry:  resolvedEntry || bundle?.xau_price || 3000,
        sl:     resolvedSl    || (bundle?.xau_price ?? 3000) - 10,
        tp1:    resolvedTp1   || (bundle?.xau_price ?? 3000) + 15,
        tp2:    resolvedTp2   || (bundle?.xau_price ?? 3000) + 30,
        tp3:    resolvedTp3   || (bundle?.xau_price ?? 3000) + 50,
        side:   resolvedSide,
        profile,
        broker_max_leverage: leverage,
        custom_risk_pct: null,
      })
      setPlan(result)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Gagal kalkulasi')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <h1 className="text-lg font-black text-slate-100">💰 Kalkulator Posisi</h1>

      {/* Profil risiko */}
      <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50">
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">Profil Risiko</p>
        <div className="grid grid-cols-2 gap-2">
          {PROFILES.map(p => (
            <button
              key={p}
              onClick={() => setProfile(p)}
              className={cn(
                'rounded-xl px-3 py-2.5 text-left transition-all touch-action',
                profile === p
                  ? 'bg-sky-600 text-white'
                  : 'bg-slate-700/50 text-slate-300 hover:bg-slate-700',
              )}
            >
              <p className="text-xs font-bold">{PROFILE_LABEL[p].label}</p>
              <p className="text-[10px] opacity-70 mt-0.5">{PROFILE_LABEL[p].desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Modal + Leverage */}
      <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50 space-y-3">
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Akun</p>
        <label className="block">
          <span className="text-xs text-slate-400">Modal (USD)</span>
          <input
            type="number"
            value={equity}
            onChange={e => setEquity(Number(e.target.value))}
            className="mt-1 w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-sky-500"
          />
        </label>
        <label className="block">
          <span className="text-xs text-slate-400">Leverage Broker</span>
          <input
            type="number"
            value={leverage}
            onChange={e => setLeverage(Number(e.target.value))}
            className="mt-1 w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-sky-500"
          />
        </label>
      </div>

      {/* Level source */}
      <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50 space-y-3">
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Pakai Level Sinyal</p>
        <div className="grid grid-cols-2 gap-2">
          {[
            { k: 'intraday', l: '🎯 Intraday' },
            { k: 'scalper',  l: '⚡ Scalper'  },
            { k: 'swing',    l: '🌊 Swing'    },
            { k: 'manual',   l: '✏️ Manual'   },
          ].map(({ k, l }) => (
            <button
              key={k}
              onClick={() => setSigSrc(k as typeof sigSrc)}
              className={cn(
                'rounded-xl px-3 py-2.5 text-xs font-semibold transition-all touch-action',
                sigSrc === k
                  ? 'bg-sky-600 text-white'
                  : 'bg-slate-700/50 text-slate-300 hover:bg-slate-700',
              )}
            >
              {l}
            </button>
          ))}
        </div>

        {/* Signal preview */}
        {sigSrc !== 'manual' && selectedSig && (
          <div className={cn(
            'rounded-xl px-3 py-2 text-xs',
            selectedSig.side === 'FLAT'
              ? 'bg-slate-700/40 text-slate-400'
              : 'bg-green-950/40 text-green-300',
          )}>
            {selectedSig.side === 'FLAT'
              ? 'Sinyal sedang FLAT — pakai harga terakhir'
              : `${selectedSig.side} @ $${fmtPrice(selectedSig.entry)} · SL $${fmtPrice(selectedSig.sl)} · TP1 $${fmtPrice(selectedSig.tp1)}`
            }
          </div>
        )}

        {/* Manual inputs */}
        {sigSrc === 'manual' && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: 'Entry', val: entry, set: setEntry },
                { label: 'SL',    val: sl,    set: setSl    },
                { label: 'TP1',   val: tp1,   set: setTp1   },
                { label: 'TP2',   val: tp2,   set: setTp2   },
                { label: 'TP3',   val: tp3,   set: setTp3   },
              ].map(({ label, val, set }) => (
                <label key={label} className="block">
                  <span className="text-[11px] text-slate-400">{label}</span>
                  <input
                    type="number"
                    value={val || ''}
                    onChange={e => set(Number(e.target.value))}
                    placeholder={`$${fmtPrice(bundle?.xau_price ?? 3000)}`}
                    className="mt-0.5 w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-sky-500"
                  />
                </label>
              ))}
            </div>
            <div className="flex gap-2">
              {(['LONG', 'SHORT'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setSide(s)}
                  className={cn(
                    'flex-1 rounded-xl py-2 text-sm font-bold transition-all touch-action',
                    side === s && s === 'LONG'  ? 'bg-green-600 text-white' :
                    side === s && s === 'SHORT' ? 'bg-red-600 text-white'   :
                    'bg-slate-700/50 text-slate-300',
                  )}
                >
                  {s === 'LONG' ? '🟢 BELI' : '🔴 JUAL'}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Calc button */}
      <button
        onClick={handleCalc}
        disabled={loading}
        className="w-full py-3.5 bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white font-bold rounded-2xl transition-all touch-action disabled:opacity-50"
      >
        {loading ? 'Menghitung...' : '⚡ Hitung Ukuran Posisi'}
      </button>

      {err && <p className="text-red-400 text-sm text-center">{err}</p>}

      {/* Results */}
      {plan && (
        <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50 space-y-3 animate-fade-in">
          <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Hasil</p>

          <div className="grid grid-cols-2 gap-2">
            <MetricCard label="Ukuran Lot"    value={`${plan.lot_size.toFixed(2)} lot`} sub={`${plan.units_oz.toFixed(0)} oz`} />
            <MetricCard label="Risk (SL hit)" value={fmtUSD(plan.risk_amount_usd)} sub={`${(plan.risk_pct * 100).toFixed(2)}% modal`} red />
            <MetricCard label="Leverage Pakai" value={`${plan.leverage_used.toFixed(1)}×`} />
            <MetricCard label="Pip Value"     value={`$${plan.pip_value_usd.toFixed(2)}/pip`} />
          </div>

          <div className="grid grid-cols-3 gap-2">
            <MetricCard label="TP1" value={fmtUSD(plan.expected_payoff_usd.tp1)} green sub={`R ${(plan.expected_payoff_usd.tp1 / (plan.risk_amount_usd || 1)).toFixed(1)}×`} />
            <MetricCard label="TP2" value={fmtUSD(plan.expected_payoff_usd.tp2)} green sub={`R ${(plan.expected_payoff_usd.tp2 / (plan.risk_amount_usd || 1)).toFixed(1)}×`} />
            <MetricCard label="TP3" value={fmtUSD(plan.expected_payoff_usd.tp3)} green sub={`R ${(plan.expected_payoff_usd.tp3 / (plan.risk_amount_usd || 1)).toFixed(1)}×`} />
          </div>

          {plan.warnings.length > 0 && (
            <div className="bg-amber-950/40 border border-amber-700/40 rounded-xl px-3 py-2">
              {plan.warnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-300">⚠️ {w}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </main>
  )
}

function MetricCard({ label, value, sub, red, green }: {
  label: string; value: string; sub?: string; red?: boolean; green?: boolean
}) {
  return (
    <div className="bg-slate-700/30 rounded-xl px-3 py-2.5">
      <p className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</p>
      <p className={cn(
        'text-sm font-bold tabular-nums mt-0.5',
        red ? 'text-red-400' : green ? 'text-green-400' : 'text-slate-100',
      )}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}
