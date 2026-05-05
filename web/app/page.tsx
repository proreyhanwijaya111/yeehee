// Server Component — fetches signal_bundle + portfolio + RCS in parallel.
// SWR hydrates from initialBundle (no "Memuat..." flash).
import HomeClient from './HomeClient'
import {
  getLatestSignalBundle, getActiveTrades, getPortfolioStats, getLatestRcsSignal,
} from '@/lib/server-api'

export const revalidate = 60

export default async function HomePage() {
  let initialBundle = null
  let serverError: string | null = null
  const [bundleResult, openTrades, stats, rcs] = await Promise.all([
    getLatestSignalBundle().catch((e) => {
      serverError = e instanceof Error ? e.message : 'Failed to load initial signal'
      return null
    }),
    getActiveTrades({ status: 'OPEN', limit: 10 }).catch(() => []),
    getPortfolioStats().catch(() => null),
    getLatestRcsSignal('M15').catch(() => null),
  ])
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
      portfolioStats={stats}
    />
  )
}
