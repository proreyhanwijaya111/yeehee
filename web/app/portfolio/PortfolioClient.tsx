'use client'
import { useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, Briefcase, Activity, Target, Zap, Waves,
  CheckCircle2, Hourglass, type LucideIcon, Clock, RotateCcw, Loader2,
} from 'lucide-react'
import {
  type ActiveTrade, type PortfolioStats, type TradeStatus,
} from '@/lib/server-api'
import { fmtPrice, cn } from '@/lib/utils'

type StyleFilter = 'all' | 'scalper' | 'intraday' | 'swing'

interface Props {
  openTrades:   ActiveTrade[]
  closedTrades: ActiveTrade[]
  stats:        PortfolioStats | null
  xauPrice:     number | null   // current spot for live trades chart
}

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
  const [resetting, setResetting] = useState<null | 'open' | 'all'>(null)
  const router = useRouter()

  const handleReset = async (scope: 'open' | 'all') => {
    const msg = scope === 'all'
      ? 'Hapus SEMUA trade history (open + closed)? Gak bisa di-undo.'
      : 'Tutup semua trade yang masih OPEN sebagai MANUAL close (pnl=0)?'
    if (!confirm(msg)) return
    setResetting(scope)
    try {
      const r = await fetch('/api/portfolio/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok || !j.ok) {
        alert(`Reset gagal: ${j.error || r.statusText}`)
      } else {
        router.refresh()
      }
    } catch (e) {
      alert(`Reset error: ${String(e)}`)
    } finally {
      setResetting(null)
    }
  }

  // Filter both lists by style
  const filteredOpen   = filter === 'all' ? openTrades   : openTrades.filter(t => t.style === filter)
  const filteredClosed = filter === 'all' ? closedTrades : closedTrades.filter(t => t.style === filter)

  // Per-style breakdown stats
  const breakdown = useMemo(() => {
    const result: Record<string, { wins: number; losses: number; total_r: number; n: number; avg_duration_ms: number }> = {
      scalper:  { wins: 0, losses: 0, total_r: 0, n: 0, avg_duration_ms: 0 },
      intraday: { wins: 0, losses: 0, total_r: 0, n: 0, avg_duration_ms: 0 },
      swing:    { wins: 0, losses: 0, total_r: 0, n: 0, avg_duration_ms: 0 },
    }
    for (const t of closedTrades) {
      const b = result[t.style]
      if (!b) continue
      b.n++
      const r = t.pnl_r ?? 0
      b.total_r += r
      if (r > 0) b.wins++
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
        <ResetMenu onReset={handleReset} busy={resetting} />
      </header>

      <div className="space-y-5">
        {stats && stats.closed_count > 0 ? <StatsCard stats={stats} /> : <EmptyStats />}

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

        {filteredOpen.length > 0 ? (
          <Group title={`Active trades (${filteredOpen.length})`}>
            {filteredOpen.map(t => <TradeRow key={t.id} trade={t} live xauPrice={xauPrice} />)}
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

        {filteredClosed.length > 0 && (
          <Group title={`History (${filteredClosed.length})`}>
            {filteredClosed.slice(0, 50).map(t => <TradeRow key={t.id} trade={t} />)}
          </Group>
        )}
      </div>
    </main>
  )
}

// Per-style breakdown table
function BreakdownCard({ breakdown }: { breakdown: Record<string, { wins: number; losses: number; total_r: number; n: number; avg_duration_ms: number }> }) {
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
          const totalR = b.total_r
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
                    <span className={totalR >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      {totalR >= 0 ? '+' : ''}{totalR.toFixed(2)} R
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

function StatsCard({ stats }: { stats: PortfolioStats }) {
  const closed = stats.closed_count
  const winrate = stats.win_rate * 100
  const totalR = stats.total_pnl_r
  const reliability =
    closed >= 30 ? { label: 'reliable', color: 'text-emerald-400' } :
    closed >= 10 ? { label: 'developing', color: 'text-amber-400' } :
                   { label: 'too few',     color: 'text-rose-400' }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5 px-2">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          Performance (real outcome)
        </p>
        <p className="text-[10px] text-slate-500">
          <span className="font-mono">{closed}</span> trade · <span className={reliability.color}>{reliability.label}</span>
        </p>
      </div>
      <div className="bg-gradient-to-br from-slate-800/60 to-slate-900/60 rounded-2xl border border-slate-800 overflow-hidden">
        {/* Hero KPI: total return — biggest, dominant */}
        <div className="px-4 py-4 border-b border-slate-800/80">
          <p className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Total return</p>
          <p className={cn(
            'text-3xl font-black tabular-nums leading-none mt-1',
            totalR > 0 ? 'text-emerald-300' : totalR < 0 ? 'text-rose-300' : 'text-slate-400',
          )}>
            {totalR >= 0 ? '+' : ''}{totalR.toFixed(2)} R
          </p>
          <p className="text-[11px] text-slate-500 mt-1">
            avg {stats.avg_pnl_r >= 0 ? '+' : ''}{stats.avg_pnl_r.toFixed(2)} R/trade · win rate {winrate.toFixed(1)}%
          </p>
        </div>
        {/* Sub stats grid */}
        <div className="grid grid-cols-3 gap-px bg-slate-800/60">
          <Cell label="Wins"  value={`${stats.wins}`}   tone="ok"   sub={`avg +${stats.avg_win_r.toFixed(2)} R`} />
          <Cell label="Losses" value={`${stats.losses}`} tone="bad" sub={`avg ${stats.avg_loss_r.toFixed(2)} R`} />
          <Cell label="Open"   value={`${stats.open_count}`} tone="neutral"
                sub={stats.expired > 0 ? `${stats.expired} expired` : 'tracking'} />
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

function TradeRow({ trade, live, xauPrice }: { trade: ActiveTrade; live?: boolean; xauPrice?: number | null }) {
  const Icon = STYLE_ICON[trade.style] ?? Target
  const tone = STATUS_TONE[trade.status]
  const sideColor = trade.side === 'LONG' ? 'text-emerald-300' : 'text-rose-300'
  const sideArrow = trade.side === 'LONG' ? '↗' : '↘'
  const statusColor =
    tone === 'win'  ? 'bg-emerald-700/30 text-emerald-200 border-emerald-700/40' :
    tone === 'loss' ? 'bg-rose-700/30 text-rose-200 border-rose-700/40' :
    tone === 'open' ? 'bg-sky-700/30 text-sky-200 border-sky-700/40' :
                      'bg-slate-700/30 text-slate-300 border-slate-700/40'
  const pnlR = trade.pnl_r ?? 0

  // Duration: how long trade was/has been open
  const opened = new Date(trade.opened_at).getTime()
  const closed = trade.closed_at ? new Date(trade.closed_at).getTime() : Date.now()
  const durationMs = closed - opened

  return (
    <div className="px-3.5 py-3">
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
              pnlR >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
              {pnlR >= 0 ? '+' : ''}{pnlR.toFixed(2)} R
            </p>
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

      {/* Duration row — explicit, readable */}
      <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-500">
        <Clock size={10} className="shrink-0" />
        <span className="font-mono">
          {live
            ? <>open {formatDuration(durationMs)} · expires in {timeAgoFuture(trade.expiry_at)}</>
            : <>held {formatDuration(durationMs)} · {timeAgo(trade.opened_at)} → {timeAgo(trade.closed_at ?? '')}</>
          }
        </span>
      </div>

      {/* Price-level chart — gives instant context: where is price now relative
          to entry/SL/TPs? Live trades show current spot dot, closed trades show
          exit price. Renders as a horizontal axis with markers and labeled zones. */}
      <PriceLevelChart trade={trade} live={live} xauPrice={xauPrice ?? null} />
    </div>
  )
}

/** Horizontal price-level visualisation per trade.
 *  - LONG: SL (left, red) → Entry → Now → TP1 → TP2 (right, green)
 *  - SHORT: mirrored — TP2 left, SL right
 *  Marker positions interpolate linearly between min/max levels.
 *  For closed trades, the "Now" dot is replaced by exit_price.
 */
function PriceLevelChart({
  trade, live, xauPrice,
}: {
  trade: ActiveTrade; live?: boolean; xauPrice: number | null
}) {
  const entry = Number(trade.entry)
  const sl    = Number(trade.sl)
  const tp1   = trade.tp1 ? Number(trade.tp1) : null
  const tp2   = trade.tp2 ? Number(trade.tp2) : null
  if (!isFinite(entry) || !isFinite(sl)) return null

  // "Now" — live spot for OPEN trades, exit_price for closed trades.
  const now = live
    ? (xauPrice ?? (trade.high_after_open !== null ? Number(trade.high_after_open) : entry))
    : (trade.exit_price !== null ? Number(trade.exit_price) : entry)

  const isLong = trade.side === 'LONG'
  // Build axis: lowest = SL (LONG) or TP2 (SHORT); highest opposite.
  const allLevels = [sl, entry, now, ...(tp1 ? [tp1] : []), ...(tp2 ? [tp2] : [])]
  const min = Math.min(...allLevels)
  const max = Math.max(...allLevels)
  const range = max - min || 1
  const pct = (v: number) => ((v - min) / range) * 100

  // Color the bar: red zone (loss side of entry) → green zone (profit side).
  // For LONG: red below entry, green above. For SHORT: opposite.
  const entryPct = pct(entry)
  const slPct    = pct(sl)
  const nowPct   = pct(now)
  const tp1Pct   = tp1 ? pct(tp1) : null
  const tp2Pct   = tp2 ? pct(tp2) : null

  // PnL relative to original SL distance for status label
  const slDist = Math.abs(entry - sl)
  const r = slDist > 0
    ? (isLong ? (now - entry) / slDist : (entry - now) / slDist)
    : 0
  const rClass = r > 0 ? 'text-emerald-300' : r < 0 ? 'text-rose-300' : 'text-slate-400'

  return (
    <div className="mt-2.5">
      {/* Bar */}
      <div className="relative h-7 bg-slate-900/40 rounded border border-slate-800">
        {/* Profit zone shading (entry → TPs side) */}
        <div
          className={cn(
            'absolute top-0 bottom-0 rounded',
            isLong ? 'bg-emerald-500/10' : 'bg-emerald-500/10',
          )}
          style={
            isLong
              ? { left: `${entryPct}%`, right: 0 }
              : { right: `${100 - entryPct}%`, left: 0 }
          }
        />
        {/* Loss zone shading (entry → SL side) */}
        <div
          className={cn('absolute top-0 bottom-0 rounded bg-rose-500/10')}
          style={
            isLong
              ? { left: 0, right: `${100 - entryPct}%` }
              : { left: `${entryPct}%`, right: 0 }
          }
        />

        {/* SL marker */}
        <Marker pct={slPct} color="bg-rose-500"  label="SL"  fmtV={fmtPrice(sl)} />
        {/* Entry marker */}
        <Marker pct={entryPct} color="bg-slate-300" label="Entry" fmtV={fmtPrice(entry)} thicker />
        {/* TP markers */}
        {tp1Pct !== null && tp1 && <Marker pct={tp1Pct} color="bg-emerald-500" label="TP1" fmtV={fmtPrice(tp1)} />}
        {tp2Pct !== null && tp2 && <Marker pct={tp2Pct} color="bg-emerald-400" label="TP2" fmtV={fmtPrice(tp2)} />}

        {/* Current price / exit dot */}
        <div
          className={cn(
            'absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full ring-2 ring-slate-950 z-10',
            live ? (r > 0 ? 'bg-emerald-300' : r < 0 ? 'bg-rose-300' : 'bg-amber-300')
                 : (r > 0 ? 'bg-emerald-400' : 'bg-rose-400'),
          )}
          style={{ left: `${nowPct}%` }}
          title={live ? `Now ${fmtPrice(now)}` : `Exit ${fmtPrice(now)}`}
        />
      </div>

      {/* Status row beneath bar */}
      <div className="mt-1 flex items-center justify-between text-[9px] text-slate-500 font-mono px-0.5">
        <span>{isLong ? `SL ${fmtPrice(sl)}` : `TP2 ${tp2 ? fmtPrice(tp2) : '-'}`}</span>
        <span className={rClass}>
          {live ? 'Now' : 'Exit'} {fmtPrice(now)} ({r >= 0 ? '+' : ''}{r.toFixed(2)} R)
        </span>
        <span>{isLong ? `TP2 ${tp2 ? fmtPrice(tp2) : '-'}` : `SL ${fmtPrice(sl)}`}</span>
      </div>
    </div>
  )
}

function Marker({
  pct, color, label, fmtV, thicker,
}: {
  pct: number; color: string; label: string; fmtV: string; thicker?: boolean
}) {
  return (
    <div
      className="absolute top-0 bottom-0 -translate-x-1/2 group"
      style={{ left: `${pct}%` }}
      title={`${label} ${fmtV}`}
    >
      <div className={cn('h-full', color, thicker ? 'w-[2px]' : 'w-px')} />
    </div>
  )
}

function ResetMenu({ onReset, busy }: { onReset: (scope: 'open' | 'all') => void; busy: null | 'open' | 'all' }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="p-1.5 hover:bg-slate-800 rounded-lg text-slate-400"
        aria-label="Reset portfolio"
        disabled={busy !== null}
      >
        {busy ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 w-56 bg-slate-900 border border-slate-700 rounded-xl shadow-xl z-50 overflow-hidden">
            <button
              onClick={() => { setOpen(false); onReset('open') }}
              className="w-full text-left px-3 py-2.5 text-[11px] text-slate-200 hover:bg-slate-800 border-b border-slate-800"
              disabled={busy !== null}
            >
              <div className="font-semibold">Tutup semua OPEN</div>
              <div className="text-[10px] text-slate-500 leading-tight">Mark MANUAL close, pnl=0</div>
            </button>
            <button
              onClick={() => { setOpen(false); onReset('all') }}
              className="w-full text-left px-3 py-2.5 text-[11px] text-rose-200 hover:bg-rose-900/30"
              disabled={busy !== null}
            >
              <div className="font-semibold">Hapus SEMUA history</div>
              <div className="text-[10px] text-slate-500 leading-tight">Clean slate. Tidak bisa undo.</div>
            </button>
          </div>
        </>
      )}
    </div>
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
