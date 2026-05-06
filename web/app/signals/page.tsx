// Server Component — fetch signal_bundle + RCS + open trades in parallel.
import SignalsClient from './SignalsClient'
import { getLatestSignalBundle, getLatestRcsSignal, getActiveTrades } from '@/lib/server-api'

export const revalidate = 60

export default async function SignalsPage() {
  let initialBundle = null
  let serverError: string | null = null
  // Parallel fetch: bundle + RCS + open trades for EXECUTED badge.
  const [bundleResult, rcs, openTrades] = await Promise.all([
    getLatestSignalBundle().catch((e) => {
      serverError = e instanceof Error ? e.message : 'Failed to load'
      return null
    }),
    getLatestRcsSignal('M15').catch(() => null),
    getActiveTrades({ status: 'OPEN', limit: 10 }).catch(() => []),
  ])
  initialBundle = bundleResult
  // RCS priority: bundle.rcs (migration 012) > rcs_signals fallback.
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
  return <SignalsClient initialBundle={initialBundle} serverError={serverError} openTrades={openTrades} />
}
