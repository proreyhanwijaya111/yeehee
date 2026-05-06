'use client'
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronUp, CheckCircle2, Hourglass } from 'lucide-react'
import type { Signal, TradingStyle } from '@/lib/types'
import {
  ACTION_LABEL, STYLE_LABEL, cn, fmtPrice, fmtPct, fmtR, explainFlat,
} from '@/lib/utils'

// Signal lifecycle: each signal valid for SIGNAL_TTL_S seconds after the
// bundle was generated. After TTL, it's marked EXPIRED visually until
// the next cycle's bundle replaces it. If the daemon-side trade tracker
// already opened a trade for this style, the signal is marked EXECUTED.
const SIGNAL_TTL_S = 180   // 3 menit per user spec

interface Props {
  style:  TradingStyle
  signal: Signal
  bundleTimestamp?: string   // ISO of bundle generation; for age computation
  isExecuted?:      boolean  // true if open trade exists for this style
}

export default function SignalCard({ style, signal, bundleTimestamp, isExecuted = false }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { side, confidence, confluence_count, reasons, risks } = signal

  // Age countdown — re-render every second so user sees TTL ticking down
  const [ageSec, setAgeSec] = useState(() => computeAge(bundleTimestamp))
  useEffect(() => {
    if (!bundleTimestamp) return
    const iv = setInterval(() => setAgeSec(computeAge(bundleTimestamp)), 1000)
    return () => clearInterval(iv)
  }, [bundleTimestamp])

  const isBuy  = side === 'LONG'
  const isSell = side === 'SHORT'
  const isFlat = side === 'FLAT'
  const isExpired = !isFlat && !isExecuted && ageSec >= SIGNAL_TTL_S
  const remaining = Math.max(0, SIGNAL_TTL_S - ageSec)

  const borderColor =
    isExecuted ? 'border-emerald-500/60'
    : isExpired ? 'border-slate-600/40'
    : isBuy ? 'border-green-500' : isSell ? 'border-red-500' : 'border-slate-600'
  const bgColor =
    isExecuted ? 'bg-emerald-950/40'
    : isExpired ? 'bg-slate-800/30'
    : isBuy ? 'bg-green-950/60' : isSell ? 'bg-red-950/60' : 'bg-slate-800/60'
  const actionColor =
    isExpired ? 'text-slate-500'
    : isBuy ? 'text-green-400' : isSell ? 'text-red-400' : 'text-slate-400'
  const barColor =
    isExpired ? 'bg-slate-600'
    : isBuy ? 'bg-green-500' : isSell ? 'bg-red-500' : 'bg-slate-500'

  return (
    <div className={cn(
      'rounded-2xl border p-4 card-shadow transition-all duration-200',
      bgColor, borderColor,
    )}>
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs text-slate-400 font-medium flex items-center gap-1.5">
            {STYLE_LABEL[style]}
            {isExecuted && (
              <span className="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-wider text-emerald-300 bg-emerald-900/40 px-1 py-0.5 rounded">
                <CheckCircle2 size={9} /> EXECUTED
              </span>
            )}
            {isExpired && !isExecuted && (
              <span className="text-[9px] font-bold uppercase tracking-wider text-slate-500 bg-slate-800 px-1 py-0.5 rounded">
                EXPIRED
              </span>
            )}
          </p>
          <p className={cn('text-xl font-black mt-0.5', actionColor)}>
            {ACTION_LABEL[side]}
          </p>
        </div>
        <div className="text-right">
          {isExecuted ? (
            <Link
              href="/portfolio"
              className="text-[10px] text-emerald-300 hover:text-emerald-200 font-semibold underline underline-offset-2"
            >
              lihat portfolio →
            </Link>
          ) : (
            <>
              <p className="text-xs text-slate-400">Keyakinan</p>
              <p className={cn('text-lg font-bold tabular-nums', isExpired && 'text-slate-500')}>
                {fmtPct(confidence)}
              </p>
            </>
          )}
        </div>
      </div>

      {/* Confidence bar (replaced with TTL countdown for non-flat non-executed) */}
      {!isFlat && !isExecuted && bundleTimestamp ? (
        <div className="mt-3">
          <div className="bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
            <div
              className={cn(
                'h-1.5 rounded-full transition-all duration-1000',
                isExpired ? 'bg-slate-600' : remaining < 60 ? 'bg-amber-500' : barColor,
              )}
              style={{ width: `${(remaining / SIGNAL_TTL_S) * 100}%` }}
            />
          </div>
          <p className="text-[10px] text-slate-500 mt-1 flex items-center gap-1">
            {isExpired
              ? <>EXPIRED · tunggu cycle berikutnya</>
              : <><Hourglass size={9} /> sinyal valid {remaining}s lagi · {confluence_count} faktor</>
            }
          </p>
        </div>
      ) : (
        <>
          <div className="mt-3 bg-slate-700/50 rounded-full h-1.5">
            <div
              className={cn('h-1.5 rounded-full transition-all duration-700', barColor)}
              style={{ width: fmtPct(confidence) }}
            />
          </div>
          <p className="text-[10px] text-slate-500 mt-1">{confluence_count} faktor sepakat</p>
        </>
      )}

      {/* Levels (non-flat only) */}
      {!isFlat && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <LevelRow label="Entry"  value={fmtPrice(signal.entry)} />
          <LevelRow label="SL"     value={fmtPrice(signal.sl)}    red />
          <LevelRow label="TP1"    value={fmtPrice(signal.tp1)}   sub={`R ${fmtR(signal.rr_to_tp1)}`} green />
          <LevelRow label="TP2"    value={fmtPrice(signal.tp2)}   sub={`R ${fmtR(signal.rr_to_tp2)}`} green />
        </div>
      )}

      {/* Flat explanation */}
      {isFlat && (
        <p className="mt-3 text-xs text-slate-400 bg-slate-700/30 rounded-xl px-3 py-2 leading-relaxed">
          {explainFlat(reasons)}
        </p>
      )}

      {/* Expandable detail */}
      {(reasons.length > 0 || risks.length > 0) && (
        <>
          <button
            onClick={() => setExpanded(v => !v)}
            className="mt-3 flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 transition-colors touch-action w-full"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {expanded ? 'Sembunyikan' : `Detail (${reasons.length} alasan, ${risks.length} risiko)`}
          </button>

          {expanded && (
            <div className="mt-2 space-y-2 animate-fade-in">
              {reasons.length > 0 && (
                <div>
                  <p className="text-[11px] text-slate-400 font-semibold uppercase tracking-wide mb-1">
                    Alasan
                  </p>
                  {reasons.map((r, i) => (
                    <p key={i} className="text-xs text-slate-300 leading-relaxed">• {r}</p>
                  ))}
                </div>
              )}
              {risks.length > 0 && (
                <div>
                  <p className="text-[11px] text-amber-400 font-semibold uppercase tracking-wide mb-1">
                    ⚠️ Risiko
                  </p>
                  {risks.map((r, i) => (
                    <p key={i} className="text-xs text-amber-300/80 leading-relaxed">• {r}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function computeAge(iso?: string): number {
  if (!iso) return 0
  try {
    const t = new Date(iso).getTime()
    if (!Number.isFinite(t)) return 0
    return Math.max(0, Math.floor((Date.now() - t) / 1000))
  } catch { return 0 }
}

function LevelRow({
  label, value, sub, red, green,
}: {
  label: string; value: string; sub?: string; red?: boolean; green?: boolean
}) {
  return (
    <div className="bg-slate-700/30 rounded-xl px-3 py-2">
      <p className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</p>
      <p className={cn(
        'text-sm font-bold tabular-nums',
        red ? 'text-red-400' : green ? 'text-green-400' : 'text-slate-100',
      )}>
        ${value}
      </p>
      {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
    </div>
  )
}
