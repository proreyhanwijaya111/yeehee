'use client'
import { useState } from 'react'
import useSWR from 'swr'
import {
  Shield, Droplet, Flame, AlertTriangle, Target, Zap, Waves, Pencil,
  ArrowUpRight, ArrowDownRight, AlertCircle, Sparkles, Loader2,
  type LucideIcon,
} from 'lucide-react'
import { getSignals, calcPosition } from '@/lib/api'
import type { PositionPlan, RiskProfile } from '@/lib/types'
import { fmtUSD, fmtPrice, cn } from '@/lib/utils'

type SigSrc = 'intraday' | 'scalper' | 'swing' | 'manual'

const PROFILES = [
  { id: 'konservatif' as RiskProfile, icon: Shield,         label: 'Konservatif', sub: '0.5% risk · max 2% loss harian' },
  { id: 'moderat'     as RiskProfile, icon: Droplet,        label: 'Moderat',     sub: '1% risk · max 4% loss harian' },
  { id: 'agresif'     as RiskProfile, icon: Flame,          label: 'Agresif',     sub: '2% risk · max 6% loss harian' },
  { id: 'bebas'       as RiskProfile, icon: AlertTriangle,  label: 'Bebas',       sub: '5% risk · max 20% loss (BAHAYA)' },
]

const STYLES: { id: SigSrc; icon: LucideIcon; label: string }[] = [
  { id: 'intraday', icon: Target, label: 'Intraday' },
  { id: 'scalper',  icon: Zap,    label: 'Scalper'  },
  { id: 'swing',    icon: Waves,  label: 'Swing'    },
  { id: 'manual',   icon: Pencil, label: 'Manual'   },
]

export default function CalculatorPage() {
  const { data: bundle } = useSWR('signals', () => getSignals('signals'))

  // String state untuk numeric input — type="number" + value={number} bikin
  // bug "leading zero" di Chrome (02000 ga bisa dihapus). Pakai string + parse.
  const [equity,    setEquity]   = useState('10000')
  const [leverage,  setLeverage] = useState('100')
  const [profile,   setProfile]  = useState<RiskProfile>('moderat')
  const [sigSrc,    setSigSrc]   = useState<SigSrc>('intraday')
  const [entry,     setEntry]    = useState('')
  const [sl,        setSl]       = useState('')
  const [tp1,       setTp1]      = useState('')
  const [tp2,       setTp2]      = useState('')
  const [tp3,       setTp3]      = useState('')

  const equityNum   = Number(equity)   || 0
  const leverageNum = Number(leverage) || 1
  const entryNum    = Number(entry)    || 0
  const slNum       = Number(sl)       || 0
  const tp1Num      = Number(tp1)      || 0
  const tp2Num      = Number(tp2)      || 0
  const tp3Num      = Number(tp3)      || 0
  const [side,      setSide]     = useState<'LONG' | 'SHORT'>('LONG')
  const [plan,      setPlan]     = useState<PositionPlan | null>(null)
  const [loading,   setLoading]  = useState(false)
  const [err,       setErr]      = useState('')

  const sigMap = {
    intraday: bundle?.intraday_signal,
    scalper:  bundle?.scalper_signal,
    swing:    bundle?.swing_signal,
  }
  const selectedSig = sigSrc !== 'manual' ? sigMap[sigSrc] : null

  const resolvedEntry = sigSrc !== 'manual' && selectedSig ? selectedSig.entry : entryNum
  const resolvedSl    = sigSrc !== 'manual' && selectedSig ? selectedSig.sl    : slNum
  const resolvedTp1   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp1   : tp1Num
  const resolvedTp2   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp2   : tp2Num
  const resolvedTp3   = sigSrc !== 'manual' && selectedSig ? selectedSig.tp3   : tp3Num
  const resolvedSide  = sigSrc !== 'manual' && selectedSig && selectedSig.side !== 'FLAT'
    ? selectedSig.side as 'LONG' | 'SHORT'
    : side

  const handleCalc = async () => {
    setLoading(true)
    setErr('')
    try {
      const result = await calcPosition({
        equity_usd: equityNum,
        entry:  resolvedEntry || bundle?.xau_price || 3000,
        sl:     resolvedSl    || (bundle?.xau_price ?? 3000) - 10,
        tp1:    resolvedTp1   || (bundle?.xau_price ?? 3000) + 15,
        tp2:    resolvedTp2   || (bundle?.xau_price ?? 3000) + 30,
        tp3:    resolvedTp3   || (bundle?.xau_price ?? 3000) + 50,
        side:   resolvedSide,
        profile,
        broker_max_leverage: leverageNum,
        custom_risk_pct: null,
      })
      setPlan(result)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Gagal kalkulasi')
    } finally {
      setLoading(false)
    }
  }

  // Strip leading zeros + non-digit chars (allow empty state for clear)
  const cleanNum = (v: string) => v.replace(/[^\d.]/g, '').replace(/^0+(?=\d)/, '')

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="mb-4">
        <h1 className="text-lg font-black text-slate-100">Kalkulator Posisi</h1>
        <p className="text-[11px] text-slate-500 mt-0.5">Hitung lot size berbasis risk per trade.</p>
      </header>

      <div className="space-y-5">
        {/* Profil risiko */}
        <Group title="Profil risiko">
          {PROFILES.map(p => {
            const Icon = p.icon
            const active = profile === p.id
            return (
              <button
                key={p.id}
                onClick={() => setProfile(p.id)}
                className={cn(
                  'w-full flex items-center gap-3 px-3.5 py-3 transition-colors touch-action text-left',
                  active ? 'bg-sky-900/30' : 'hover:bg-slate-800/40 active:bg-slate-800/70',
                )}
              >
                <div className={cn(
                  'w-8 h-8 rounded-lg border flex items-center justify-center shrink-0',
                  active
                    ? 'bg-sky-700/40 border-sky-600 text-sky-200'
                    : 'bg-slate-800/80 border-slate-700/50 text-slate-300',
                )}>
                  <Icon size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className={cn(
                    'text-sm font-medium leading-tight',
                    active ? 'text-sky-100' : 'text-slate-100',
                  )}>
                    {p.label}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">{p.sub}</p>
                </div>
                {active && <span className="w-2 h-2 rounded-full bg-sky-400 shrink-0" />}
              </button>
            )
          })}
        </Group>

        {/* Akun */}
        <Group title="Akun">
          <Field label="Modal (USD)">
            <input
              type="text"
              inputMode="numeric"
              value={equity}
              onChange={e => setEquity(cleanNum(e.target.value))}
              placeholder="10000"
              className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500 tabular-nums"
            />
          </Field>
          <Field label="Leverage broker">
            <input
              type="text"
              inputMode="numeric"
              value={leverage}
              onChange={e => setLeverage(cleanNum(e.target.value))}
              placeholder="100"
              className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500 tabular-nums"
            />
          </Field>
        </Group>

        {/* Source */}
        <Group title="Sumber level">
          <div className="grid grid-cols-2 gap-px bg-slate-800/80">
            {STYLES.map(s => {
              const Icon = s.icon
              const active = sigSrc === s.id
              return (
                <button
                  key={s.id}
                  onClick={() => setSigSrc(s.id)}
                  className={cn(
                    'flex items-center gap-2 px-3.5 py-3 transition-colors touch-action',
                    active
                      ? 'bg-sky-900/30 text-sky-100'
                      : 'bg-slate-800/40 text-slate-300 hover:bg-slate-800/60',
                  )}
                >
                  <Icon size={14} className={active ? 'text-sky-400' : 'text-slate-500'} />
                  <span className="text-sm font-medium">{s.label}</span>
                  {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-sky-400" />}
                </button>
              )
            })}
          </div>

          {sigSrc !== 'manual' && selectedSig && (
            <div className={cn(
              'px-3.5 py-2.5 text-[11px] border-t border-slate-800/80',
              selectedSig.side === 'FLAT' ? 'text-slate-500' : 'text-emerald-300',
            )}>
              {selectedSig.side === 'FLAT'
                ? 'Sinyal sedang FLAT — pakai harga terakhir'
                : (
                  <span className="font-mono">
                    {selectedSig.side} @ ${fmtPrice(selectedSig.entry)} · SL ${fmtPrice(selectedSig.sl)} · TP1 ${fmtPrice(selectedSig.tp1)}
                  </span>
                )}
            </div>
          )}

          {sigSrc === 'manual' && (
            <div className="px-3.5 py-3 space-y-3 border-t border-slate-800/80">
              <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                {[
                  { label: 'Entry', val: entry, set: setEntry },
                  { label: 'SL',    val: sl,    set: setSl    },
                  { label: 'TP1',   val: tp1,   set: setTp1   },
                  { label: 'TP2',   val: tp2,   set: setTp2   },
                  { label: 'TP3',   val: tp3,   set: setTp3   },
                ].map(({ label, val, set }) => (
                  <label key={label} className="block">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={val}
                      onChange={e => set(cleanNum(e.target.value))}
                      placeholder={fmtPrice(bundle?.xau_price ?? 3000)}
                      className="mt-0.5 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-sky-500 tabular-nums"
                    />
                  </label>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                {(['LONG', 'SHORT'] as const).map(s => (
                  <button
                    key={s}
                    onClick={() => setSide(s)}
                    className={cn(
                      'flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors',
                      side === s && s === 'LONG'  ? 'bg-emerald-700/50 text-emerald-100 border border-emerald-600/60' :
                      side === s && s === 'SHORT' ? 'bg-rose-700/50 text-rose-100 border border-rose-600/60' :
                      'bg-slate-800/60 text-slate-400 border border-slate-700/60',
                    )}
                  >
                    {s === 'LONG' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                    {s === 'LONG' ? 'BELI' : 'JUAL'}
                  </button>
                ))}
              </div>
            </div>
          )}
        </Group>

        {/* Compute */}
        <button
          onClick={handleCalc}
          disabled={loading}
          className={cn(
            'w-full py-3 rounded-xl text-sm font-semibold transition-all touch-action',
            'bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white shadow-sm',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'flex items-center justify-center gap-2',
          )}
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          {loading ? 'Menghitung…' : 'Hitung ukuran posisi'}
        </button>

        {err && (
          <div className="bg-rose-950/40 border border-rose-800/40 rounded-lg px-3 py-2 flex items-start gap-2">
            <AlertCircle size={14} className="text-rose-400 shrink-0 mt-0.5" />
            <p className="text-xs text-rose-300">{err}</p>
          </div>
        )}

        {/* Results */}
        {plan && <Result plan={plan} />}
      </div>
    </main>
  )
}

// ─── Building blocks ──────────────────────────────────────────────────────────

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
      <span className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function Result({ plan }: { plan: PositionPlan }) {
  return (
    <Group title="Hasil">
      <div className="px-3.5 py-3 grid grid-cols-2 gap-x-3 gap-y-3">
        <Metric label="Lot size"   value={`${plan.lot_size.toFixed(2)} lot`} sub={`${plan.units_oz.toFixed(0)} oz`} />
        <Metric label="Risk (SL)"  value={fmtUSD(plan.risk_amount_usd)}      sub={`${(plan.risk_pct * 100).toFixed(2)}% modal`} tone="warn" />
        <Metric label="Leverage"   value={`${plan.leverage_used.toFixed(1)}×`} />
        <Metric label="Pip value"  value={`$${plan.pip_value_usd.toFixed(2)}/pip`} />
      </div>

      <div className="px-3.5 py-3 grid grid-cols-3 gap-x-3 border-t border-slate-800/80">
        {(['tp1', 'tp2', 'tp3'] as const).map(k => (
          <Metric
            key={k}
            label={k.toUpperCase()}
            tone="ok"
            value={fmtUSD(plan.expected_payoff_usd[k])}
            sub={`R ${(plan.expected_payoff_usd[k] / (plan.risk_amount_usd || 1)).toFixed(1)}×`}
          />
        ))}
      </div>

      {plan.warnings.length > 0 && (
        <div className="px-3.5 py-2.5 border-t border-slate-800/80 bg-amber-950/20">
          {plan.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px] text-amber-300">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}
    </Group>
  )
}

function Metric({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'ok' | 'warn'
}) {
  const valueColor =
    tone === 'ok'   ? 'text-emerald-300' :
    tone === 'warn' ? 'text-amber-300'   : 'text-slate-100'
  return (
    <div>
      <p className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={cn('text-sm font-semibold tabular-nums mt-0.5', valueColor)}>{value}</p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}
