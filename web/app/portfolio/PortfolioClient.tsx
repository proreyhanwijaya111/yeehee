'use client'
import Link from 'next/link'
import {
  ArrowLeft, Briefcase, Activity, Target, Zap, Waves,
  CheckCircle2, Hourglass, type LucideIcon,
} from 'lucide-react'
import {
  type ActiveTrade, type PortfolioStats, type TradeStatus,
} from '@/lib/server-api'
import { fmtPrice, cn } from '@/lib/utils'

interface Props {
  openTrades:   ActiveTrade[]
  closedTrades: ActiveTrade[]
  stats:        PortfolioStats | null
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

export default function PortfolioClient({ openTrades, closedTrades, stats }: Props) {
  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-emerald-700/30 border border-emerald-600/30 flex items-center justify-center">
          <Briefcase size={16} className="text-emerald-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Portfolio</h1>
          <p className="text-[11px] text-slate-500">Active trades + history · win rate real dari outcome.</p>
        </div>
      </header>

      <div className="space-y-5">
        {stats && stats.closed_count > 0 ? <StatsCard stats={stats} /> : <EmptyStats />}

        {openTrades.length > 0 ? (
          <Group title={`Active trades (${openTrades.length})`}>
            {openTrades.map(t => <TradeRow key={t.id} trade={t} live />)}
          </Group>
        ) : (
          <Group title="Active trades">
            <div className="px-3.5 py-6 text-center">
              <Hourglass size={24} className="text-slate-500 mx-auto mb-2" />
              <p className="text-xs text-slate-400 font-medium">Belum ada active trade</p>
              <p className="text-[10px] text-slate-500 leading-relaxed mt-1 max-w-xs mx-auto">
                Daemon akan auto-open trade saat signal LONG/SHORT keluar dengan confidence ≥ 0.5.
                Tunggu next cycle (5 menit).
              </p>
            </div>
          </Group>
        )}

        {closedTrades.length > 0 && (
          <Group title={`History (${closedTrades.length})`}>
            {closedTrades.slice(0, 30).map(t => <TradeRow key={t.id} trade={t} />)}
          </Group>
        )}
      </div>
    </main>
  )
}

function StatsCard({ stats }: { stats: PortfolioStats }) {
  const closed = stats.closed_count
  const winrate = stats.win_rate * 100
  const totalR = stats.total_pnl_r
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
        Performance (real outcome)
      </p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden">
        <div className="grid grid-cols-2 gap-px bg-slate-800/60">
          <Cell label="Win rate" value={`${winrate.toFixed(1)}%`}
            tone={winrate >= 60 ? 'ok' : winrate >= 40 ? 'neutral' : 'bad'}
            sub={`${stats.wins}W / ${stats.losses}L${stats.expired > 0 ? ` / ${stats.expired}E` : ''}`}
          />
          <Cell label="Total R" value={`${totalR >= 0 ? '+' : ''}${totalR.toFixed(2)} R`}
            tone={totalR > 0 ? 'ok' : 'bad'}
            sub={`avg ${stats.avg_pnl_r >= 0 ? '+' : ''}${stats.avg_pnl_r.toFixed(2)} R/trade`}
          />
          <Cell label="Avg win" value={`+${stats.avg_win_r.toFixed(2)} R`}
            tone="ok" sub={`${stats.wins} wins`} />
          <Cell label="Avg loss" value={`${stats.avg_loss_r.toFixed(2)} R`}
            tone="bad" sub={`${stats.losses} losses`} />
        </div>
        <div className="px-3.5 py-2.5 border-t border-slate-800/80 text-[10px] text-slate-500 leading-relaxed">
          Stats compute dari <span className="font-mono text-slate-300">{closed}</span> trade tertutup.
          Lebih banyak trade = stat lebih reliable. Min 30 trade untuk valid signal-of-edge.
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

function TradeRow({ trade, live }: { trade: ActiveTrade; live?: boolean }) {
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

  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-slate-900/50 border border-slate-700/50 flex items-center justify-center shrink-0">
          <Icon size={13} className="text-slate-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={cn('text-sm font-bold', sideColor)}>
              {sideArrow} {trade.side}
            </span>
            <span className="text-[10px] text-slate-500 uppercase">{trade.style}</span>
            {trade.confidence !== null && (
              <span className="text-[10px] text-slate-500 font-mono">
                {(trade.confidence * 100).toFixed(0)}%
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
          <span>High: {fmtPrice(trade.high_after_open)}</span>
          <span>Low: {fmtPrice(trade.low_after_open)}</span>
          <span className="ml-auto">
            {trade.hit_tp1 && <CheckCircle2 size={11} className="inline text-emerald-400 mr-0.5" />}
            {trade.hit_tp1 ? 'TP1 ✓' : ''}
            {trade.hit_tp2 && ' TP2 ✓'}
          </span>
        </div>
      )}

      <p className="text-[9px] text-slate-600 mt-1 font-mono">
        Opened {timeAgo(trade.opened_at)} · expires {timeAgo(trade.expiry_at)}
      </p>
    </div>
  )
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
