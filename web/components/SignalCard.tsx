'use client'
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { Signal, TradingStyle } from '@/lib/types'
import {
  ACTION_LABEL, STYLE_LABEL, cn, fmtPrice, fmtPct, fmtR, explainFlat,
} from '@/lib/utils'

interface Props {
  style:  TradingStyle
  signal: Signal
}

export default function SignalCard({ style, signal }: Props) {
  const [expanded, setExpanded] = useState(false)
  const { side, confidence, confluence_count, reasons, risks } = signal

  const isBuy  = side === 'LONG'
  const isSell = side === 'SHORT'
  const isFlat = side === 'FLAT'

  const borderColor = isBuy ? 'border-green-500' : isSell ? 'border-red-500' : 'border-slate-600'
  const bgColor     = isBuy ? 'bg-green-950/60'  : isSell ? 'bg-red-950/60'  : 'bg-slate-800/60'
  const actionColor = isBuy ? 'text-green-400'   : isSell ? 'text-red-400'   : 'text-slate-400'
  const barColor    = isBuy ? 'bg-green-500'      : isSell ? 'bg-red-500'     : 'bg-slate-500'

  return (
    <div className={cn(
      'rounded-2xl border p-4 card-shadow transition-all duration-200',
      bgColor, borderColor,
    )}>
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs text-slate-400 font-medium">{STYLE_LABEL[style]}</p>
          <p className={cn('text-xl font-black mt-0.5', actionColor)}>
            {ACTION_LABEL[side]}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-400">Keyakinan</p>
          <p className="text-lg font-bold tabular-nums">{fmtPct(confidence)}</p>
        </div>
      </div>

      {/* Confidence progress bar */}
      <div className="mt-3 bg-slate-700/50 rounded-full h-1.5">
        <div
          className={cn('h-1.5 rounded-full transition-all duration-700', barColor)}
          style={{ width: fmtPct(confidence) }}
        />
      </div>
      <p className="text-[10px] text-slate-500 mt-1">{confluence_count} faktor sepakat</p>

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
