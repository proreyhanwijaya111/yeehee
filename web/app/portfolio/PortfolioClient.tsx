'use client'
import { useState, useMemo, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, Briefcase, Activity, Target, Zap, Waves,
  CheckCircle2, Hourglass, type LucideIcon, Clock, RotateCcw, Loader2, X,
} from 'lucide-react'
import {
  type ActiveTrade, type PortfolioStats, type TradeStatus,
} from '@/lib/server-api'
import { fmtPrice, cn } from '@/lib/utils'

type StyleFilter = 'all' | 'scalper' | 'intraday' | 'swing'
type RangeFilter = 'recent' | '7d' | '30d' | 'all'

const RANGE_LABELS: Record<RangeFilter, string> = {
  recent: '5 terakhir',
  '7d':   '7 hari',
  '30d':  '30 hari',
  all:    'Semua',
}

const RANGE_DAYS: Record<RangeFilter, number | null> = {
  recent: null,
  '7d':   7,
  '30d':  30,
  all:    null,
}

interface Props {
  openTrades:   ActiveTrade[]
  closedTrades: ActiveTrade[]
  stats:        PortfolioStats | null
  xauPrice:     number | null   // current spot for live trades chart
}

// Default risk per trade when trade.risk_pct is null (legacy pre-migration 004
// rows). Profile "moderat" cap = 1.0% of equity. Used only as fallback.
const DEFAULT_RISK_PCT = 0.01

// Display assumption: starting capital $1,000. All percentages applied additively
// to this base for the "modal awal → sekarang" display in StatsCard.
const INITIAL_CAPITAL_USD = 1000

const fmtUSD = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** Convert pnl_r (R-unit) to portfolio % using each trade's actual risk_pct.
 *  e.g. 2R win at 1% risk = 2.00% portfolio gain.
 *  Simple sum (not compounded) for clarity — paper test 30 days, % accurate enough.
 */
function pctFromR(r: number | null | undefined, riskPct: number | null | undefined): number {
  if (r === null || r === undefined) return 0
  const rp = riskPct ?? DEFAULT_RISK_PCT
  return r * rp * 100
}

const fmtPctSigned = (p: number, decimals = 2) =>
  `${p >= 0 ? '+' : ''}${p.toFixed(decimals)}%`

const STYLE_ICON: Record<string, LucideIcon> = {
  scalper:  Zap,
  intraday: Target,
  swing:    Waves,
}

const STATUS_LABEL: Record<TradeStatus, string> = {
  OPEN:    'OPEN',
  TP1:     'TP1 hit',
  TP2:     'TP2 hit',
  TP3:     'Full TP3',
  SL:      'SL hit',
  EXPIRED: 'Expired',
  MANUAL:  'Manual close',
}

const STATUS_TONE: Record<TradeStatus, 'open' | 'win' | 'loss' | 'neutral'> = {
  OPEN: 'open', TP1: 'win', TP2: 'win', TP3: 'win',
  SL: 'loss', EXPIRED: 'neutral', MANUAL: 'neutral',
}

export default function PortfolioClient({ openTrades, closedTrades, stats, xauPrice }: Props) {
  const [filter, setFilter] = useState<StyleFilter>('all')
  const [range,  setRange]  = useState<RangeFilter>('recent')
  const router = useRouter()

  // Filter both lists by style
  const filteredOpen      = filter === 'all' ? openTrades   : openTrades.filter(t => t.style === filter)
  const filteredClosedAll = filter === 'all' ? closedTrades : closedTrades.filter(t => t.style === filter)

  // Apply range filter to closed trades. Recent = last 5, others time-based.
  const filteredClosed = useMemo(() => {
    if (range === 'recent') {
      return filteredClosedAll.slice(0, 5)
    }
    const days = RANGE_DAYS[range]
    if (days === null) return filteredClosedAll  // 'all'
    const cutoff = Date.now() - days * 86400_000
    return filteredClosedAll.filter(t => {
      const ts = t.closed_at ? new Date(t.closed_at).getTime() : 0
      return ts >= cutoff
    })
  }, [filteredClosedAll, range])

  // Per-style breakdown stats (pct-based) — pct uses trade.risk_pct per trade
  const breakdown = useMemo(() => {
    const result: Record<string, { wins: number; losses: number; total_pct: number; n: number; avg_duration_ms: number }> = {
      scalper:  { wins: 0, losses: 0, total_pct: 0, n: 0, avg_duration_ms: 0 },
      intraday: { wins: 0, losses: 0, total_pct: 0, n: 0, avg_duration_ms: 0 },
      swing:    { wins: 0, losses: 0, total_pct: 0, n: 0, avg_duration_ms: 0 },
    }
    for (const t of closedTrades) {
      const b = result[t.style]
      if (!b) continue
      b.n++
      const pct = pctFromR(t.pnl_r, t.risk_pct)
      b.total_pct += pct
      if (pct > 0) b.wins++
      else b.losses++
      if (t.opened_at && t.closed_at) {
        b.avg_duration_ms += new Date(t.closed_at).getTime() - new Date(t.opened_at).getTime()
      }
    }
    for (const k of Object.keys(result)) {
      if (result[k].n > 0) result[k].avg_duration_ms /= result[k].n
    }
    return result
  }, [closedTrades])

  // Aggregate portfolio % stats (replaces server-side R-based stats).
  const pctStats = useMemo(() => {
    let total = 0, wins = 0, losses = 0, n = 0, sumWin = 0, sumLoss = 0
    for (const t of closedTrades) {
      const pct = pctFromR(t.pnl_r, t.risk_pct)
      total += pct
      n++
      if (pct > 0) { wins++; sumWin += pct }
      else if (pct < 0) { losses++; sumLoss += pct }
    }
    return {
      total_pct:  total,
      avg_pct:    n > 0 ? total / n : 0,
      avg_win:    wins > 0 ? sumWin / wins : 0,
      avg_loss:   losses > 0 ? sumLoss / losses : 0,
      win_rate:   n > 0 ? wins / n : 0,
      n_closed:   n,
      n_wins:     wins,
      n_losses:   losses,
    }
  }, [closedTrades])

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-emerald-700/30 border border-emerald-600/30 flex items-center justify-center">
          <Briefcase size={16} className="text-emerald-300" />
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-black text-slate-100 leading-tight">Portfolio</h1>
          <p className="text-[11px] text-slate-500">Active trades + history · win rate real dari outcome.</p>
        </div>
        <RefreshButton onRefresh={() => router.refresh()} />
      </header>

      <div className="space-y-5">
        {pctStats.n_closed > 0 ? (
          <StatsCard pctStats={pctStats} openCount={stats?.open_count ?? openTrades.length} expired={stats?.expired ?? 0} />
        ) : <EmptyStats />}

        {/* Per-style breakdown */}
        {closedTrades.length > 0 && <BreakdownCard breakdown={breakdown} />}

        {/* Style filter pills */}
        <div>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
            Filter kategori
          </p>
          <div className="grid grid-cols-4 gap-px bg-slate-800/80 rounded-xl overflow-hidden p-px">
            {(['all', 'scalper', 'intraday', 'swing'] as StyleFilter[]).map(s => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                className={cn(
                  'py-2 px-2 text-[11px] font-semibold transition-colors rounded-[10px] capitalize',
                  filter === s ? 'bg-sky-900/40 text-sky-100' : 'bg-slate-900/40 text-slate-400',
                )}
              >
                {s === 'all' ? 'Semua' : s}
              </button>
            ))}
          </div>
        </div>

        {/* Live XAU spot price — gives quick context for active trades below */}
        {xauPrice !== null && (
          <div className="bg-gradient-to-br from-amber-900/20 to-amber-950/30 border border-amber-700/30 rounded-xl px-3.5 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              <p className="text-[10px] text-amber-400/80 uppercase tracking-widest font-semibold">XAU Live</p>
            </div>
            <p className="text-base font-black text-amber-100 tabular-nums">${fmtPrice(xauPrice)}</p>
          </div>
        )}

        {filteredOpen.length > 0 ? (
          <Group title={`Active trades (${filteredOpen.length})`}>
            {filteredOpen.map(t => (
              <TradeRow key={t.id} trade={t} live xauPrice={xauPrice} onRefresh={() => router.refresh()} />
            ))}
          </Group>
        ) : (
          <Group title="Active trades">
            <div className="px-3.5 py-6 text-center">
              <Hourglass size={24} className="text-slate-500 mx-auto mb-2" />
              <p className="text-xs text-slate-400 font-medium">
                {filter === 'all' ? 'Belum ada active trade' : `Belum ada active trade ${filter}`}
              </p>
              <p className="text-[10px] text-slate-500 leading-relaxed mt-1 max-w-xs mx-auto">
                Daemon auto-open saat signal LONG/SHORT confidence ≥ 0.5.
              </p>
            </div>
          </Group>
        )}

        {/* History range filter — recent 5 / 7d / 30d / all */}
        {filteredClosedAll.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1.5 px-2">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
                History ({filteredClosed.length}/{filteredClosedAll.length})
              </p>
              <select
                value={range}
                onChange={e => setRange(e.target.value as RangeFilter)}
                className="text-[10px] bg-slate-800 border border-slate-700 text-slate-200 rounded px-1.5 py-0.5"
              >
                {(Object.keys(RANGE_LABELS) as RangeFilter[]).map(r => (
                  <option key={r} value={r}>{RANGE_LABELS[r]}</option>
                ))}
              </select>
            </div>
            <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
              {filteredClosed.map(t => <TradeRow key={t.id} trade={t} xauPrice={xauPrice} />)}
            </div>
          </div>
        )}
      </div>
    </main>
  )
}

// Per-style breakdown table (pct portfolio)
function BreakdownCard({ breakdown }: { breakdown: Record<string, { wins: number; losses: number; total_pct: number; n: number; avg_duration_ms: number }> }) {
  return (
    <div>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
        Per kategori
      </p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
        {(['scalper', 'intraday', 'swing'] as const).map(style => {
          const b = breakdown[style]
          const Icon = STYLE_ICON[style]
          const winrate = b.n > 0 ? (b.wins / b.n) * 100 : 0
          const totalPct = b.total_pct
          const avgDur = b.avg_duration_ms
          return (
            <div key={style} className="px-3.5 py-3 flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg bg-slate-900/50 border border-slate-700/50 flex items-center justify-center shrink-0">
                <Icon size={13} className="text-slate-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-slate-100 capitalize">{style}</p>
                  <span className="text-[10px] text-slate-500">
                    {b.n === 0 ? 'no trades' : `${b.n} trade · avg ${formatDuration(avgDur)}`}
                  </span>
                </div>
                {b.n > 0 && (
                  <div className="flex items-center gap-3 text-[10px] text-slate-500 mt-0.5 font-mono">
                    <span>{b.wins}W / {b.losses}L</span>
                    <span className={winrate >= 50 ? 'text-emerald-400' : 'text-rose-400'}>
                      {winrate.toFixed(0)}% WR
                    </span>
                    <span className={totalPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      {fmtPctSigned(totalPct)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StatsCard({ pctStats, openCount, expired }: {
  pctStats: { total_pct: number; avg_pct: number; avg_win: number; avg_loss: number; win_rate: number; n_closed: number; n_wins: number; n_losses: number }
  openCount: number
  expired: number
}) {
  const closed = pctStats.n_closed
  const winrate = pctStats.win_rate * 100
  const total = pctStats.total_pct
  const reliability =
    closed >= 30 ? { label: 'reliable', color: 'text-emerald-400' } :
    closed >= 10 ? { label: 'developing', color: 'text-amber-400' } :
                   { label: 'too few',     color: 'text-rose-400' }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5 px-2">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          Performance (% portfolio)
        </p>
        <p className="text-[10px] text-slate-500">
          <span className="font-mono">{closed}</span> trade · <span className={reliability.color}>{reliability.label}</span>
        </p>
      </div>
      <div className="bg-gradient-to-br from-slate-800/60 to-slate-900/60 rounded-2xl border border-slate-800 overflow-hidden">
        {/* Hero KPI: total return as % portfolio — biggest, dominant */}
        <div className="px-4 py-4 border-b border-slate-800/80">
          <p className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Total return</p>
          <p className={cn(
            'text-3xl font-black tabular-nums leading-none mt-1',
            total > 0 ? 'text-emerald-300' : total < 0 ? 'text-rose-300' : 'text-slate-400',
          )}>
            {fmtPctSigned(total)}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            avg {fmtPctSigned(pctStats.avg_pct)}/trade · win rate {winrate.toFixed(1)}%
          </p>
        </div>

        {/* Modal simulation panel — concrete dollar growth */}
        {(() => {
          const ending = INITIAL_CAPITAL_USD * (1 + total / 100)
          const delta  = ending - INITIAL_CAPITAL_USD
          const dColor = delta > 0 ? 'text-emerald-300' : delta < 0 ? 'text-rose-300' : 'text-slate-400'
          return (
            <div className="px-4 py-3 border-b border-slate-800/80 bg-slate-900/40">
              <p className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold mb-1.5">
                Simulasi modal awal $1,000
              </p>
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-[11px] text-slate-500 font-mono">$1,000.00</span>
                <span className="text-slate-600">→</span>
                <span className={cn('text-lg font-black tabular-nums', dColor)}>
                  {fmtUSD(ending)}
                </span>
                <span className={cn('text-[11px] font-mono tabular-nums ml-auto', dColor)}>
                  {delta >= 0 ? '+' : ''}{fmtUSD(delta).replace('$','$')}
                </span>
              </div>
              <p className="text-[10px] text-slate-500 mt-1 leading-tight">
                Asumsi {(DEFAULT_RISK_PCT * 100).toFixed(1)}% risk per trade · simple additive (gak compound).
                Kalo pake $5,000 modal hasil = {fmtUSD(5000 * (1 + total / 100))} · $10,000 = {fmtUSD(10000 * (1 + total / 100))}.
              </p>
            </div>
          )
        })()}

        {/* Sub stats grid */}
        <div className="grid grid-cols-3 gap-px bg-slate-800/60">
          <Cell label="Wins"  value={`${pctStats.n_wins}`}   tone="ok"
                sub={`avg ${fmtPctSigned(pctStats.avg_win)}`} />
          <Cell label="Losses" value={`${pctStats.n_losses}`} tone="bad"
                sub={`avg ${fmtPctSigned(pctStats.avg_loss)}`} />
          <Cell label="Open"   value={`${openCount}`} tone="neutral"
                sub={expired > 0 ? `${expired} expired` : 'tracking'} />
        </div>
      </div>
    </div>
  )
}

function EmptyStats() {
  return (
    <div className="bg-slate-800/40 border border-slate-800 rounded-2xl px-4 py-5 text-center">
      <Activity size={28} className="text-slate-500 mx-auto mb-2" />
      <p className="text-sm font-semibold text-slate-300 mb-1">Belum ada history</p>
      <p className="text-[11px] text-slate-500 leading-relaxed max-w-xs mx-auto">
        Win rate akan muncul setelah trade pertama tertutup (TP/SL hit).
        Daemon perlu beberapa hari untuk akumulasi 30+ trades buat stats valid.
      </p>
    </div>
  )
}

function TradeRow({ trade, live, xauPrice, onRefresh }: {
  trade: ActiveTrade; live?: boolean; xauPrice?: number | null; onRefresh?: () => void
}) {
  // Default-expanded for OPEN trades (user wants live tracking visible),
  // collapsed for closed trades (history scan-friendly, tap to expand chart).
  const [expanded, setExpanded] = useState(Boolean(live))
  const [closing, setClosing]   = useState(false)

  const handleManualClose = async (e: React.MouseEvent) => {
    e.stopPropagation()  // don't toggle expand
    if (!confirm(`Tutup manual trade ${trade.style.toUpperCase()} ${trade.side}?\n\nHarga keluar = spot terkini. Akan tercatat MANUAL CLOSE.`)) return
    setClosing(true)
    try {
      const r = await fetch('/api/portfolio/close', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ trade_id: trade.id }),
      })
      const j = await r.json()
      if (!r.ok || !j.ok) {
        alert(`Gagal close: ${j.error || r.statusText}`)
      } else {
        if (onRefresh) onRefresh()
      }
    } catch (err) {
      alert(`Error: ${String(err)}`)
    } finally {
      setClosing(false)
    }
  }
  const Icon = STYLE_ICON[trade.style] ?? Target
  const tone = STATUS_TONE[trade.status]
  const sideColor = trade.side === 'LONG' ? 'text-emerald-300' : 'text-rose-300'
  const sideArrow = trade.side === 'LONG' ? '↗' : '↘'
  const statusColor =
    tone === 'win'  ? 'bg-emerald-700/30 text-emerald-200 border-emerald-700/40' :
    tone === 'loss' ? 'bg-rose-700/30 text-rose-200 border-rose-700/40' :
    tone === 'open' ? 'bg-sky-700/30 text-sky-200 border-sky-700/40' :
                      'bg-slate-700/30 text-slate-300 border-slate-700/40'
  const pnlPct = pctFromR(trade.pnl_r, trade.risk_pct)

  // Duration: how long trade was/has been open
  const opened = new Date(trade.opened_at).getTime()
  const closed = trade.closed_at ? new Date(trade.closed_at).getTime() : Date.now()
  const durationMs = closed - opened

  return (
    <div
      className={cn('px-3.5 py-3', !live && 'cursor-pointer hover:bg-slate-800/30 transition-colors')}
      onClick={live ? undefined : () => setExpanded(v => !v)}
    >
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-slate-900/50 border border-slate-700/50 flex items-center justify-center shrink-0">
          <Icon size={13} className="text-slate-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={cn('text-sm font-bold', sideColor)}>
              {sideArrow} {trade.side}
            </span>
            <span className="text-[9px] uppercase tracking-wide font-semibold text-slate-400 bg-slate-800/60 px-1.5 py-0.5 rounded">
              {trade.style}
            </span>
            {trade.confidence !== null && (
              <span className="text-[10px] text-slate-500 font-mono">
                conf {(trade.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 font-mono tabular-nums mt-0.5">
            {fmtPrice(trade.entry)} → SL {fmtPrice(trade.sl)} / TP1 {trade.tp1 ? fmtPrice(trade.tp1) : '–'}
          </p>
        </div>
        <div className="text-right shrink-0">
          <span className={cn('text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border',
            statusColor)}>
            {STATUS_LABEL[trade.status]}
          </span>
          {!live && trade.pnl_r !== null && (
            <p className={cn('text-xs font-mono font-bold tabular-nums mt-1',
              pnlPct >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
              {fmtPctSigned(pnlPct)}
            </p>
          )}
          {live && (
            <button
              onClick={handleManualClose}
              disabled={closing}
              className="mt-1 px-2 py-0.5 rounded bg-rose-900/30 hover:bg-rose-900/60 border border-rose-800/50 text-rose-200 text-[9px] font-bold uppercase tracking-wide flex items-center gap-1 disabled:opacity-50"
              title="Tutup manual trade ini"
            >
              {closing ? <Loader2 size={9} className="animate-spin" /> : <X size={9} />}
              {closing ? 'tutup...' : 'tutup'}
            </button>
          )}
        </div>
      </div>

      {live && trade.high_after_open !== null && trade.low_after_open !== null && (
        <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-500 font-mono">
          <span>H: {fmtPrice(trade.high_after_open)}</span>
          <span>L: {fmtPrice(trade.low_after_open)}</span>
          <span className="ml-auto">
            {trade.hit_tp1 && <span className="text-emerald-400">TP1 ✓ </span>}
            {trade.hit_tp2 && <span className="text-emerald-400">TP2 ✓</span>}
          </span>
        </div>
      )}

      {/* Duration row — explicit timestamps + relative */}
      <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-500">
        <Clock size={10} className="shrink-0" />
        <span className="font-mono">
          {live
            ? <>OP {formatTimeWIB(trade.opened_at)} <span className="text-slate-600">·</span> {formatDuration(durationMs)} jalan <span className="text-slate-600">·</span> exp {formatTimeWIB(trade.expiry_at)}</>
            : <>OP {formatTimeWIB(trade.opened_at)} <span className="text-slate-600">→</span> CL {formatTimeWIB(trade.closed_at ?? '')} <span className="text-slate-600">·</span> {formatDuration(durationMs)}</>
          }
        </span>
      </div>

      {/* Time-series chart — only when expanded. Live trades default expanded;
          closed trades default collapsed (tap row to expand). */}
      {expanded && (
        <TradeChart trade={trade} live={live} xauPrice={xauPrice ?? null} />
      )}
      {!live && !expanded && (
        <p className="mt-1 text-[9px] text-slate-600 text-center">tap untuk lihat chart</p>
      )}
    </div>
  )
}

interface Bar { t: number; o: number | null; h: number | null; l: number | null; c: number | null }

/** Picks Yahoo interval based on trade duration:
 *    < 6h    → 5m
 *    < 24h   → 15m
 *    < 7d    → 1h
 *    >= 7d   → 1d
 */
function pickInterval(durationMs: number): string {
  if (durationMs < 6 * 3600_000)   return '5m'
  if (durationMs < 24 * 3600_000)  return '15m'
  if (durationMs < 7 * 86400_000)  return '1h'
  return '1d'
}

/**
 * Time-series chart per trade. Fetches XAU/USD bars between opened_at and
 * closed_at (or now for OPEN trades) from /api/chart/xau (Yahoo proxy).
 * Draws SVG line + horizontal markers for entry/SL/TP1/TP2 + entry/exit dots.
 *
 * Live trades: re-fetch every 60s while card visible. Closed trades: fetch once.
 */
function TradeChart({
  trade, live, xauPrice,
}: {
  trade: ActiveTrade; live?: boolean; xauPrice: number | null
}) {
  const entry = Number(trade.entry)
  const sl    = Number(trade.sl)
  const tp1   = trade.tp1 ? Number(trade.tp1) : null
  const tp2   = trade.tp2 ? Number(trade.tp2) : null
  if (!isFinite(entry) || !isFinite(sl)) return null

  const fromIso = trade.opened_at
  const toIso   = live ? new Date().toISOString() : (trade.closed_at ?? new Date().toISOString())
  const durationMs = new Date(toIso).getTime() - new Date(fromIso).getTime()
  const interval = pickInterval(durationMs)

  const [bars, setBars]       = useState<Bar[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    let abort = false
    const load = async () => {
      try {
        const u = `/api/chart/xau?from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}&interval=${interval}`
        const r = await fetch(u, { cache: 'no-store' })
        const j = await r.json()
        if (abort) return
        if (j.ok && Array.isArray(j.bars)) {
          setBars(j.bars)
          setError(null)
        } else {
          setError(j.error || 'no data')
        }
      } catch (e) {
        if (!abort) setError(String(e))
      } finally {
        if (!abort) setLoading(false)
      }
    }
    load()
    // Live trades: re-poll every 60s
    const iv = live ? setInterval(load, 60_000) : null
    return () => { abort = true; if (iv) clearInterval(iv) }
  }, [fromIso, toIso, interval, live])

  // SVG dimensions
  const W = 320, H = 80, PAD_X = 4, PAD_Y = 6

  // Build full price extent: levels + bar highs/lows + current spot
  const closes = bars.map(b => b.c).filter((v): v is number => typeof v === 'number')
  const highs  = bars.map(b => b.h).filter((v): v is number => typeof v === 'number')
  const lows   = bars.map(b => b.l).filter((v): v is number => typeof v === 'number')
  const last   = closes.length > 0 ? closes[closes.length - 1] : null
  const nowVal = live ? (xauPrice ?? last ?? entry) : (trade.exit_price !== null ? Number(trade.exit_price) : (last ?? entry))

  const allP: number[] = [entry, sl, ...(tp1 ? [tp1] : []), ...(tp2 ? [tp2] : []), nowVal, ...highs, ...lows]
  const pMin = Math.min(...allP)
  const pMax = Math.max(...allP)
  const pRange = pMax - pMin || 1

  const yOf = (price: number) => PAD_Y + (1 - (price - pMin) / pRange) * (H - 2 * PAD_Y)

  // Time extent: pad with same +/- 30min as the API does so markers align
  const t0 = new Date(fromIso).getTime() - 30 * 60_000
  const t1 = new Date(toIso).getTime()   + 30 * 60_000
  const tRange = t1 - t0 || 1
  const xOf = (t: number) => PAD_X + ((t - t0) / tRange) * (W - 2 * PAD_X)

  // Build polyline path
  const path = bars.length > 1
    ? bars.map((b, i) => `${i === 0 ? 'M' : 'L'} ${xOf(b.t).toFixed(1)} ${yOf((b.c as number) ?? entry).toFixed(1)}`).join(' ')
    : ''

  const isLong = trade.side === 'LONG'
  const slDist = Math.abs(entry - sl)
  const rNow = slDist > 0
    ? (isLong ? (nowVal - entry) / slDist : (entry - nowVal) / slDist)
    : 0
  // Convert R-now to portfolio % using trade's actual risk_pct (fallback 1%)
  const pctNow = pctFromR(rNow, trade.risk_pct)
  const rClass = pctNow > 0 ? 'text-emerald-300' : pctNow < 0 ? 'text-rose-300' : 'text-slate-400'

  // Marker x positions
  const xEntry = xOf(new Date(fromIso).getTime())
  const xExit  = xOf(new Date(toIso).getTime())
  const xNow   = live ? xOf(Date.now()) : xExit

  return (
    <div className="mt-2.5">
      {loading && bars.length === 0 ? (
        <div className="h-20 flex items-center justify-center text-[10px] text-slate-500">
          loading chart...
        </div>
      ) : error && bars.length === 0 ? (
        <div className="h-20 flex items-center justify-center text-[10px] text-rose-400">
          chart unavailable: {error.slice(0, 40)}
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20" preserveAspectRatio="none">
          {/* Profit / loss zones — green above entry for LONG, below for SHORT */}
          <rect
            x={0} width={W}
            y={isLong ? PAD_Y : yOf(entry)}
            height={isLong ? Math.max(0, yOf(entry) - PAD_Y) : Math.max(0, H - PAD_Y - yOf(entry))}
            fill="rgba(16,185,129,0.07)"
          />
          <rect
            x={0} width={W}
            y={isLong ? yOf(entry) : PAD_Y}
            height={isLong ? Math.max(0, H - PAD_Y - yOf(entry)) : Math.max(0, yOf(entry) - PAD_Y)}
            fill="rgba(244,63,94,0.06)"
          />

          {/* Horizontal level lines */}
          <Line y={yOf(sl)}    color="rgba(244,63,94,0.7)"   width={W} dash />
          <Line y={yOf(entry)} color="rgba(226,232,240,0.6)" width={W} />
          {tp1 !== null && <Line y={yOf(tp1)} color="rgba(16,185,129,0.6)" width={W} dash />}
          {tp2 !== null && <Line y={yOf(tp2)} color="rgba(34,197,94,0.5)"  width={W} dash />}

          {/* Vertical time markers: entry, exit (closed only) */}
          <line x1={xEntry} x2={xEntry} y1={PAD_Y} y2={H - PAD_Y}
                stroke="rgba(148,163,184,0.4)" strokeDasharray="2,2" strokeWidth={0.7} />
          {!live && (
            <line x1={xExit} x2={xExit} y1={PAD_Y} y2={H - PAD_Y}
                  stroke="rgba(148,163,184,0.4)" strokeDasharray="2,2" strokeWidth={0.7} />
          )}

          {/* Price line */}
          {path && <path d={path} fill="none" stroke="rgba(56,189,248,0.95)" strokeWidth={1.2} strokeLinejoin="round" />}

          {/* Entry dot */}
          <circle cx={xEntry} cy={yOf(entry)} r={3}
                  fill={isLong ? '#22c55e' : '#f43f5e'}
                  stroke="#020617" strokeWidth={1.2} />

          {/* Now / Exit dot */}
          <circle cx={xNow} cy={yOf(nowVal)} r={3.5}
                  fill={rNow > 0 ? '#34d399' : rNow < 0 ? '#fb7185' : '#fbbf24'}
                  stroke="#020617" strokeWidth={1.4} />

          {/* Level labels (right edge) */}
          <PriceLabel y={yOf(sl)}    text={`SL ${fmtPrice(sl)}`}    color="#fb7185" />
          <PriceLabel y={yOf(entry)} text={`E ${fmtPrice(entry)}`}  color="#cbd5e1" />
          {tp1 !== null && <PriceLabel y={yOf(tp1)} text={`TP1 ${fmtPrice(tp1)}`} color="#34d399" />}
          {tp2 !== null && <PriceLabel y={yOf(tp2)} text={`TP2 ${fmtPrice(tp2)}`} color="#22c55e" />}
        </svg>
      )}

      {/* Footer status: real spot + portfolio % */}
      <div className="mt-1 flex items-center justify-between text-[10px] font-mono">
        <span className="text-slate-500">
          XAU <span className="text-slate-300">{fmtPrice(nowVal)}</span>
        </span>
        <span className={cn(rClass, 'font-bold')}>
          {live ? 'Now' : 'Exit'} {fmtPctSigned(pctNow)}
        </span>
        <span className="text-slate-500">
          {bars.length > 0 ? `${bars.length} bar ${interval}` : '—'}
        </span>
      </div>
    </div>
  )
}

function Line({ y, color, width, dash }: { y: number; color: string; width: number; dash?: boolean }) {
  return (
    <line x1={0} x2={width} y1={y} y2={y}
          stroke={color} strokeWidth={1}
          strokeDasharray={dash ? '3,3' : undefined} />
  )
}

function PriceLabel({ y, text, color }: { y: number; text: string; color: string }) {
  return (
    <text x={4} y={y - 2} fill={color} fontSize={8} fontFamily="monospace" opacity={0.85}>
      {text}
    </text>
  )
}

function RefreshButton({ onRefresh }: { onRefresh: () => void }) {
  const [spinning, setSpinning] = useState(false)
  const handle = () => {
    setSpinning(true)
    onRefresh()
    setTimeout(() => setSpinning(false), 800)
  }
  return (
    <button
      onClick={handle}
      className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-400"
      aria-label="Refresh data"
      title="Refresh data"
    >
      <RotateCcw size={16} className={spinning ? 'animate-spin' : ''} />
    </button>
  )
}

// Format duration in human-readable form: "2h 15m" or "3d 5h" or "45m"
function formatDuration(ms: number): string {
  if (ms < 0 || !Number.isFinite(ms)) return '–'
  const sec = Math.floor(ms / 1000)
  const m = Math.floor(sec / 60)
  if (m < 1) return `${sec}s`
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const remM = m % 60
  if (h < 24) return remM > 0 ? `${h}h ${remM}m` : `${h}h`
  const d = Math.floor(h / 24)
  const remH = h % 24
  return remH > 0 ? `${d}d ${remH}h` : `${d}d`
}

function timeAgoFuture(iso: string): string {
  try {
    const diff = new Date(iso).getTime() - Date.now()
    if (diff < 0) return 'expired'
    return formatDuration(diff)
  } catch {
    return '–'
  }
}

/** Format ISO timestamp as "HH:MM" (today) or "DD MMM HH:MM" (other days), local TZ.
 *  Always uses colon ':' separator (id-ID locale defaults to '.', confusing).
 */
function formatTimeWIB(iso: string): string {
  if (!iso) return '–'
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return '–'
    const today = new Date()
    const sameDay = d.getDate() === today.getDate()
                 && d.getMonth() === today.getMonth()
                 && d.getFullYear() === today.getFullYear()
    const yesterday = new Date(); yesterday.setDate(today.getDate() - 1)
    const isYesterday = d.getDate() === yesterday.getDate()
                     && d.getMonth() === yesterday.getMonth()
                     && d.getFullYear() === yesterday.getFullYear()
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    const hhmm = `${hh}:${mm}`
    if (sameDay)     return hhmm
    if (isYesterday) return `kemarin ${hhmm}`
    const day = String(d.getDate()).padStart(2, '0')
    const monthNames = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des']
    const mon = monthNames[d.getMonth()]
    return `${day} ${mon} ${hhmm}`
  } catch {
    return '–'
  }
}

function Cell({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'ok' | 'bad' | 'neutral'
}) {
  const valueColor =
    tone === 'ok'   ? 'text-emerald-300' :
    tone === 'bad'  ? 'text-rose-300'    : 'text-slate-100'
  return (
    <div className="px-3.5 py-2.5 bg-slate-800/40">
      <p className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">{label}</p>
      <p className={cn('text-sm font-bold tabular-nums mt-0.5', valueColor)}>{value}</p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
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

function timeAgo(iso: string): string {
  try {
    const diff = new Date(iso).getTime() - Date.now()
    const future = diff > 0
    const m = Math.abs(Math.floor(diff / 60_000))
    if (m < 1) return future ? 'soon' : 'just now'
    if (m < 60) return future ? `in ${m}m` : `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24) return future ? `in ${h}h` : `${h}h ago`
    const d = Math.floor(h / 24)
    return future ? `in ${d}d` : `${d}d ago`
  } catch {
    return iso.slice(0, 16)
  }
}
