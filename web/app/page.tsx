// Server Component — fetches signal_bundle + portfolio + RCS in parallel.
// SWR hydrates from initialBundle (no "Memuat..." flash).
import HomeClient from './HomeClient'
import {
  getLatestSignalBundle, getActiveTrades, getPortfolioStats, getLatestRcsSignal,
  getRealEaTrades,
} from '@/lib/server-api'

export const runtime = 'edge'

// 2026-05-07: bumped 60s -> 180s. Vercel free tier cap exceeded.
export const revalidate = 180

export default async function HomePage() {
  let initialBundle = null
  let serverError: string | null = null
  // 2026-05-07: PortfolioGlance switch to REAL broker trades by default
  // (rcs_executions). active_trades dipakai sebagai fallback only kalau
  // belum ada real trade yet. User audit: Beranda HARUS reflect actual
  // broker, bukan paper sim.
  const [bundleResult, realTrades, paperOpen, paperAll, stats, rcs] = await Promise.all([
    getLatestSignalBundle().catch((e) => {
      serverError = e instanceof Error ? e.message : 'Failed to load initial signal'
      return null
    }),
    getRealEaTrades({ limit: 100 }).catch(() => []),
    getActiveTrades({ status: 'OPEN', limit: 10 }).catch(() => []),
    getActiveTrades({ status: 'all', limit: 100 }).catch(() => []),
    getPortfolioStats().catch(() => null),
    getLatestRcsSignal('M15').catch(() => null),
  ])
  // Prefer real trades. If empty (no EA executions yet), fallback to paper.
  const realClosed = realTrades.filter(t => t.status !== 'OPEN')
  const realOpen   = realTrades.filter(t => t.status === 'OPEN')
  const closedTrades = realClosed.length > 0 ? realClosed : paperAll.filter(t => t.status !== 'OPEN')
  const openTrades   = realClosed.length > 0 ? realOpen   : paperOpen
  initialBundle = bundleResult
  // RCS priority: 1) baked into signal_bundles row (migration 012), 2) fallback
  // to latest rcs_signals row. If bundle already has rcs, keep it.
  if (initialBundle && !initialBundle.rcs && rcs) {
    initialBundle.rcs = {
      rcs_score:      rcs.rcs_score,
      direction:      rcs.direction,
      confidence_pct: rcs.confidence_pct,
      components:     Object.entries(rcs.feature_snapshot ?? {}).map(([name, v]) => ({
        name: name as 'trend' | 'momentum' | 'structure' | 'intermarket' | 'volatility' | 'session',
        score:  Number(v.score),
        weight: Number(v.weight),
        detail: String(v.detail ?? ''),
      })),
      top_drivers:    (rcs.shap_top_5 ?? []).map(d => `${d.name}: ${d.detail} (${d.contribution >= 0 ? '+' : ''}${d.contribution.toFixed(2)})`),
      regime:         '',
      session:        '',
    }
  }
  return (
    <HomeClient
      initialBundle={initialBundle}
      serverError={serverError}
      openTrades={openTrades}
      closedTrades={closedTrades}
      portfolioStats={stats}
    />
  )
}
