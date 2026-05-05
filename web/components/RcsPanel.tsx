import Link from 'next/link'
import { Sparkles, ChevronRight, TrendingUp, TrendingDown, Pause } from 'lucide-react'
import type { RCSReference } from '@/lib/types'

/**
 * RCS reference panel — composite indicator dari kombinasi semua existing
 * indicators. Bukan signal utama, tapi cross-reference untuk 12-agent debate.
 *
 * Renders:
 *  - Header dengan Sparkles icon (signature RCS look)
 *  - Big RCS score dengan progress bar diverging dari 0
 *  - Direction badge (LONG/SHORT/WAIT)
 *  - Top 3 drivers (small text)
 *  - Click → /more/rcs-monitor
 */
export default function RcsPanel({ rcs }: { rcs: RCSReference | null }) {
  if (!rcs) {
    return (
      <div className="bg-violet-950/20 border border-violet-900/40 rounded-2xl p-3.5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/40 flex items-center justify-center shrink-0">
            <Sparkles size={15} className="text-violet-300" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-bold text-violet-100">RCS — Composite</p>
            <p className="text-[11px] text-violet-200/60">Belum ada data — daemon belum push cycle pertama dengan RCS.</p>
          </div>
        </div>
      </div>
    )
  }

  const score    = rcs.rcs_score
  const isLong   = rcs.direction === 'LONG'
  const isShort  = rcs.direction === 'SHORT'
  const isWait   = rcs.direction === 'WAIT'

  // Progress bar: score [-1, +1] → percentage from -100% to +100%
  const barPct = Math.abs(score) * 100

  const dirColor =
    isLong  ? 'text-emerald-300' :
    isShort ? 'text-rose-300'    : 'text-slate-400'
  const dirBg =
    isLong  ? 'bg-emerald-500' :
    isShort ? 'bg-rose-500'    : 'bg-slate-500'
  const dirIcon = isLong  ? <TrendingUp size={13} /> :
                  isShort ? <TrendingDown size={13} /> :
                            <Pause size={13} />

  return (
    <Link
      href="/more/rcs-monitor"
      className="block bg-violet-950/30 border border-violet-800/50 rounded-2xl p-3.5 hover:bg-violet-950/40 transition-colors active:scale-[0.99] touch-action"
    >
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/40 flex items-center justify-center shrink-0">
          <Sparkles size={15} className="text-violet-300" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-bold text-violet-100">RCS — Composite</p>
            <span className="text-[9px] text-violet-300/60 uppercase tracking-wider font-mono">v0.1</span>
          </div>
          <p className="text-[10px] text-violet-200/60 mt-0.5">
            Indikator pamungkas — gabungan semua signal sebagai referensi.
          </p>
        </div>
        <ChevronRight size={16} className="text-violet-400/50 shrink-0" />
      </div>

      <div className="mt-3 pt-3 border-t border-violet-800/40">
        {/* Direction + score */}
        <div className="flex items-center justify-between mb-2">
          <div className={`flex items-center gap-1.5 font-bold text-base ${dirColor}`}>
            {dirIcon}
            <span>{rcs.direction}</span>
            <span className="text-violet-300/60 font-mono text-xs ml-1">{rcs.confidence_pct}%</span>
          </div>
          <span className={`font-mono text-sm tabular-nums ${
            score > 0 ? 'text-emerald-300' : score < 0 ? 'text-rose-300' : 'text-slate-400'
          }`}>
            {score >= 0 ? '+' : ''}{score.toFixed(3)}
          </span>
        </div>

        {/* Diverging bar from 0 */}
        <div className="relative h-1.5 bg-slate-800/60 rounded-full overflow-hidden">
          <div className="absolute inset-y-0 left-1/2 w-px bg-slate-700/80" />
          <div
            className={`absolute inset-y-0 ${dirBg} transition-all`}
            style={{
              width: `${barPct / 2}%`,
              left: score >= 0 ? '50%' : `${50 - barPct / 2}%`,
            }}
          />
        </div>

        {/* Top drivers */}
        {rcs.top_drivers.length > 0 && (
          <div className="mt-2.5 space-y-1">
            {rcs.top_drivers.slice(0, 3).map((d, i) => (
              <p key={i} className="text-[10px] text-violet-200/70 leading-snug truncate">
                <span className="text-violet-400/60 mr-1">·</span>{d}
              </p>
            ))}
          </div>
        )}
      </div>
    </Link>
  )
}
