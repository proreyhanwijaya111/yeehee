import Link from 'next/link'
import {
  Briefcase, ChevronRight, TrendingUp, TrendingDown, Activity, Hourglass,
} from 'lucide-react'
import type { PortfolioStats, ActiveTrade } from '@/lib/server-api'

interface Props {
  stats:        PortfolioStats | null
  openTrades:   ActiveTrade[]
  closedTrades?: ActiveTrade[]
}

// Same default as PortfolioClient — keeps Beranda + /portfolio in sync.
const DEFAULT_RISK_PCT = 0.01

function pctFromR(r: number | null | undefined, riskPct: number | null | undefined): number {
  if (r === null || r === undefined) return 0
  const rp = riskPct ?? DEFAULT_RISK_PCT
  return r * rp * 100
}

/**
 * Compact portfolio summary widget for home page.
 * Server-rendered (no 'use client') — data baked into HTML.
 *
 * Shows:
 * - Open positions count (and # of LONGs vs SHORTs if any)
 * - Win rate from closed trades
 * - Total R accumulated
 *
 * Click → /portfolio.
 */
export default function PortfolioGlance({ stats, openTrades, closedTrades = [] }: Props) {
  const openCount = openTrades.length
  const longs   = openTrades.filter(t => t.side === 'LONG').length
  const shorts  = openTrades.filter(t => t.side === 'SHORT').length

  // Compute fully client-side from closedTrades — matches /portfolio page logic
  // exactly (which also computes pctStats from closedTrades). Eliminates
  // mismatch caused by server view's win_rate using wrong denominator.
  let n = 0, wins = 0, losses = 0, totalPct = 0
  for (const t of closedTrades) {
    n++
    const pct = pctFromR(t.pnl_r, t.risk_pct)
    totalPct += pct
    if (pct > 0)      wins++
    else if (pct < 0) losses++
    // pct == 0 (BEP/manual) excluded from both
  }
  // Fallback to server stats only if no closedTrades passed
  const closed = n > 0 ? n : (stats?.closed_count ?? 0)
  const winrateBase = wins + losses
  const winrate = winrateBase > 0 ? (wins / winrateBase) * 100
                  : (stats?.win_rate ?? 0) * 100
  const totalReturnPct = n > 0 ? totalPct
                       : (stats?.total_pnl_r ?? 0) * DEFAULT_RISK_PCT * 100

  return (
    <Link
      href="/portfolio"
      className="block bg-emerald-950/30 border border-emerald-800/40 rounded-2xl p-3.5 hover:bg-emerald-950/40 transition-colors active:scale-[0.99] touch-action"
    >
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-emerald-700/30 border border-emerald-600/30 flex items-center justify-center shrink-0">
          <Briefcase size={17} className="text-emerald-300" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-bold text-emerald-100">Portfolio</p>
            <span className="text-[10px] text-emerald-400/60 uppercase tracking-wider">live</span>
          </div>
          <p className="text-[10px] text-emerald-200/60 mt-0.5">
            {openCount === 0
              ? closed === 0 ? 'Belum ada trade — daemon akan auto-open saat signal valid' : `${closed} trade tertutup`
              : `${openCount} active${longs > 0 || shorts > 0 ? ` (${longs}↗ ${shorts}↘)` : ''} · ${closed} tertutup`}
          </p>
        </div>
        <ChevronRight size={16} className="text-emerald-400/50 shrink-0" />
      </div>

      {(closed > 0 || openCount > 0) && (
        <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-emerald-800/40">
          <Stat label="Active" value={`${openCount}`} icon={openCount > 0 ? <Activity size={11} /> : <Hourglass size={11} />} />
          <Stat label="Win rate"
                value={closed > 0 ? `${winrate.toFixed(0)}%` : '–'}
                icon={winrate >= 50 ? <TrendingUp size={11} /> : winrate > 0 ? <TrendingDown size={11} /> : null}
                tone={closed === 0 ? 'neutral' : winrate >= 50 ? 'ok' : 'bad'} />
          <Stat label="Return"
                value={closed > 0 ? `${totalReturnPct >= 0 ? '+' : ''}${totalReturnPct.toFixed(2)}%` : '–'}
                icon={totalReturnPct >= 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                tone={closed === 0 ? 'neutral' : totalReturnPct >= 0 ? 'ok' : 'bad'} />
        </div>
      )}
    </Link>
  )
}

function Stat({ label, value, icon, tone }: {
  label: string; value: string; icon?: React.ReactNode; tone?: 'ok' | 'bad' | 'neutral'
}) {
  const valueColor =
    tone === 'ok'  ? 'text-emerald-300' :
    tone === 'bad' ? 'text-rose-300'    : 'text-emerald-100'
  return (
    <div>
      <p className="text-[9px] text-emerald-400/60 uppercase tracking-wide font-semibold flex items-center gap-1">
        {icon}{label}
      </p>
      <p className={`text-sm font-bold tabular-nums mt-0.5 ${valueColor}`}>{value}</p>
    </div>
  )
}
