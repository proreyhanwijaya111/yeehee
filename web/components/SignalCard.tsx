'use client'
import { useState } from 'react'
import { ChevronDown, ChevronUp, Hourglass } from 'lucide-react'
import type { Signal, TradingStyle } from '@/lib/types'
import {
  ACTION_LABEL, STYLE_LABEL, cn, fmtPrice, fmtPct, fmtR, explainFlat,
} from '@/lib/utils'

interface Props {
  style:  TradingStyle
  signal: Signal
}

// Daemon writes reasons[0] = "Trade {style} {side} sedang OPEN ..." when it
// blocks new signal because previous trade hasn't closed yet (runner.py
// _block_if_running). Detecting this prefix lets the card render a distinct
// "TRADE RUNNING" state instead of a generic FLAT.
const TRADE_RUNNING_PREFIX = 'Trade '
const TRADE_RUNNING_MARKER = 'sedang OPEN'

function isTradeRunning(side: string, reasons: string[]): boolean {
  if (side !== 'FLAT' || reasons.length === 0) return false
  const r = reasons[0]
  return r.startsWith(TRADE_RUNNING_PREFIX) && r.includes(TRADE_RUNNING_MARKER)
}

export default function SignalCard({ style, signal }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { side, confidence, confluence_count, reasons, risks } = signal

  const isBuy  = side === 'LONG'
  const isSell = side === 'SHORT'
  const isFlat = side === 'FLAT'
  const isRunning = isTradeRunning(side, reasons)

  const borderColor = isRunning ? 'border-amber-600/60'
    : isBuy ? 'border-green-500' : isSell ? 'border-red-500' : 'border-slate-600'
  const bgColor = isRunning ? 'bg-amber-950/30'
    : isBuy ? 'bg-green-950/60' : isSell ? 'bg-red-950/60' : 'bg-slate-800/60'
  const actionColor = isRunning ? 'text-amber-300'
    : isBuy ? 'text-green-400' : isSell ? 'text-red-400' : 'text-slate-400'
  const barColor = isRunning ? 'bg-amber-500'
    : isBuy ? 'bg-green-500' : isSell ? 'bg-red-500' : 'bg-slate-500'

  return (
    <div className={cn(
      'rounded-2xl border p-4 card-shadow transition-all duration-200',
      bgColor, borderColor,
    )}>
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs text-slate-400 font-medium">{STYLE_LABEL[style]}</p>
          <p className={cn('text-xl font-black mt-0.5 flex items-center gap-1.5', actionColor)}>
            {isRunning && <Hourglass size={16} className="text-amber-400" />}
            {isRunning ? 'TRADE RUNNING' : ACTION_LABEL[side]}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-400">{isRunning ? 'Status' : 'Keyakinan'}</p>
          <p className="text-lg font-bold tabular-nums">
            {isRunning ? '—' : fmtPct(confidence)}
          </p>
        </div>
      </div>

      {/* Confidence progress bar — hidden saat trade running (gak relevan) */}
      {!isRunning && (
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

      {/* Trade running — distinct from regular FLAT */}
      {isRunning && (
        <p className="mt-3 text-xs text-amber-200/90 bg-amber-900/20 border border-amber-800/40 rounded-xl px-3 py-2 leading-relaxed">
          {reasons[0]} Lihat di <span className="font-semibold text-amber-100">Portfolio</span> buat tracking realtime.
        </p>
      )}

      {/* Flat explanation (real flat only, not trade-running) */}
      {isFlat && !isRunning && (
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
