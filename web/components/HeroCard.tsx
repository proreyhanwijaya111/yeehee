'use client'
import { useEffect, useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import type { SignalBundle } from '@/lib/types'
import {
  ACTION_LABEL, STRENGTH_LABEL, STRENGTH_DESC,
  humanizeRegime, humanizeSession, explainFlat, fmtPrice, fmtPct, fmtR,
  cn,
} from '@/lib/utils'

// Signal TTL: same as SignalCard (180s). After this, non-executed LONG/SHORT
// signals enter EXPIRED state until the next bundle is published.
const SIGNAL_TTL_S = 180

interface Props {
  bundle: SignalBundle
  /** True if any of scalper/intraday/swing has an OPEN trade for this bundle's
   *  signal. When true, HeroCard stays prominent (EXECUTED) past the 180s TTL. */
  isExecuted?: boolean
}

function ageSec(iso: string): number {
  try {
    return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  } catch { return 0 }
}

function ageMinutes(iso: string): number {
  return Math.floor(ageSec(iso) / 60)
}

export default function HeroCard({ bundle, isExecuted = false }: Props) {
  const { final_action: action, signal_strength: strength, confidence } = bundle
  const strDesc = STRENGTH_DESC[strength]

  // Tick every 1s for live age countdown / expiry transition
  const [age, setAge] = useState(() => bundle.timestamp ? ageSec(bundle.timestamp) : 0)
  useEffect(() => {
    if (!bundle.timestamp) return
    const t = setInterval(() => setAge(ageSec(bundle.timestamp)), 1000)
    return () => clearInterval(t)
  }, [bundle.timestamp])

  // Lifecycle states (matches SignalCard semantics):
  // - FLAT: always shown as TUNGGU resting state, no expiry.
  // - LONG/SHORT, age <= 180s: ACTIVE — full color, countdown bar.
  // - LONG/SHORT, age > 180s, !executed: EXPIRED — muted, "menunggu cycle berikutnya".
  // - LONG/SHORT, isExecuted: EXECUTED — keeps action color + emerald badge.
  const isFlat   = action === 'FLAT'
  const isExpired = !isFlat && !isExecuted && age >= SIGNAL_TTL_S
  const remaining = Math.max(0, SIGNAL_TTL_S - age)

  // Best non-flat signal for level display
  const bestSig = [bundle.intraday_signal, bundle.swing_signal, bundle.scalper_signal]
    .find(s => s?.side !== 'FLAT') ?? bundle.intraday_signal

  const regimeInfo  = humanizeRegime(bundle.regime)
  const sessionInfo = humanizeSession(bundle.session)

  // EXPIRED state mutes the entire card to slate (matches SignalCard EXPIRED).
  const bgGradient =
    isExpired           ? 'from-slate-900 via-slate-800/80 to-slate-800/60' :
    action === 'LONG'   ? 'from-green-800 via-green-700 to-green-600' :
    action === 'SHORT'  ? 'from-red-800 via-red-700 to-red-600' :
                          'from-slate-800 via-slate-700 to-slate-700'

  const borderColor =
    isExpired           ? 'border-slate-700/40' :
    action === 'LONG'   ? 'border-green-500/30' :
    action === 'SHORT'  ? 'border-red-500/30' :
                          'border-slate-600/30'

  return (
    <div className={cn(
      'bg-gradient-to-br rounded-3xl p-5 border card-shadow-lg hero-live',
      bgGradient, borderColor,
    )}>
      <div className="flex justify-between items-start gap-3">
        {/* Left: action */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className={cn(
              'text-4xl font-black tracking-tight leading-none',
              isExpired && 'opacity-60',
            )}>
              {isExpired ? 'EXPIRED' : ACTION_LABEL[action]}
            </p>
            {isExecuted && !isFlat && (
              <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border bg-emerald-700/30 text-emerald-200 border-emerald-700/40 flex items-center gap-1">
                <CheckCircle2 size={10} /> EXECUTED
              </span>
            )}
          </div>
          <p className={cn('mt-1.5 text-sm font-semibold', isExpired ? 'opacity-50' : 'opacity-90')}>
            {isExpired ? 'Menunggu cycle berikutnya' : STRENGTH_LABEL[strength]}
          </p>
          {!isExpired && (
            <p className="mt-0.5 text-xs opacity-70">
              {strDesc}
            </p>
          )}

          {/* Confidence bar OR countdown — only shown when ACTIVE (or always for FLAT) */}
          {!isExpired && (!isFlat && bundle.timestamp ? (
            <div className="mt-3">
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-black/25 rounded-full h-1.5 overflow-hidden">
                  <div
                    className={cn(
                      'h-1.5 rounded-full transition-all duration-1000 ease-linear',
                      remaining < 60 ? 'bg-amber-300/80' : 'bg-white/80',
                    )}
                    style={{ width: `${(remaining / SIGNAL_TTL_S) * 100}%` }}
                  />
                </div>
                <span className="text-xs font-bold opacity-90 tabular-nums whitespace-nowrap">
                  {fmtPct(confidence)} yakin
                </span>
              </div>
              {!isExecuted && (
                <p className="text-[10px] opacity-60 mt-1">
                  sinyal valid {remaining}s lagi
                </p>
              )}
            </div>
          ) : (
            <div className="mt-3 flex items-center gap-2">
              <div className="flex-1 bg-black/20 rounded-full h-1.5">
                <div
                  className="h-1.5 rounded-full bg-white/80 transition-all duration-700"
                  style={{ width: `${(confidence * 100).toFixed(0)}%` }}
                />
              </div>
              <span className="text-xs font-bold opacity-90 tabular-nums whitespace-nowrap">
                {fmtPct(confidence)} yakin
              </span>
            </div>
          ))}

          {/* Context tags */}
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <span className="text-[11px] bg-black/20 px-2 py-0.5 rounded-full opacity-80">
              {regimeInfo.label}
            </span>
            <span className="text-[11px] bg-black/20 px-2 py-0.5 rounded-full opacity-80">
              {sessionInfo.label}
            </span>
          </div>

          {/* FLAT explanation */}
          {action === 'FLAT' && (
            <p className="mt-3 text-xs opacity-70 bg-black/15 rounded-xl px-3 py-2 leading-relaxed">
              {explainFlat(bundle.intraday_signal?.reasons ?? [])}
            </p>
          )}
        </div>

        {/* Right: price */}
        <div className="text-right shrink-0">
          <p className="text-[11px] opacity-60 font-medium uppercase tracking-wider">XAU/USD</p>
          <p className="text-2xl font-black tabular-nums leading-tight">
            ${fmtPrice(bundle.xau_price)}
          </p>
          <p className="text-[10px] opacity-50 mt-0.5">
            {bundle.xau_price_source === 'twelvedata' ? 'spot · Twelve Data'
              : bundle.xau_price_source === 'yfinance_fallback' ? 'yfinance · check broker'
              : 'per troy oz'}
          </p>
          {bundle.timestamp && (
            <p className="text-[9px] opacity-40 mt-0.5">
              signal {ageMinutes(bundle.timestamp)}m lalu
            </p>
          )}
        </div>
      </div>

      {/* Entry levels (jika ada sinyal aktif & belum expired) */}
      {!isExpired && action !== 'FLAT' && bestSig && bestSig.side !== 'FLAT' && (
        <div className="mt-4 grid grid-cols-4 gap-2 bg-black/15 rounded-2xl p-3">
          {[
            { label: 'Entry',  value: fmtPrice(bestSig.entry) },
            { label: 'SL',     value: fmtPrice(bestSig.sl) },
            { label: 'TP1',    value: fmtPrice(bestSig.tp1) },
            { label: 'R:R',    value: fmtR(bestSig.rr_to_tp1) },
          ].map(({ label, value }) => (
            <div key={label} className="text-center">
              <p className="text-[10px] opacity-60 uppercase tracking-wide">{label}</p>
              <p className="text-xs font-bold tabular-nums mt-0.5">{value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
