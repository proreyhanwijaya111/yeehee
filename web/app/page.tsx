// Server Component — fetches signal_bundle + portfolio data, hands to
// HomeClient. SWR hydrates from initialBundle (no "Memuat..." flash).
import HomeClient from './HomeClient'
import {
  getLatestSignalBundle, getActiveTrades, getPortfolioStats,
} from '@/lib/server-api'

export const revalidate = 60

export default async function HomePage() {
  let initialBundle = null
  let serverError: string | null = null
  // Fetch portfolio data in parallel (don't block on signals if portfolio fails)
  const [bundleResult, openTrades, stats] = await Promise.all([
    getLatestSignalBundle().catch((e) => {
      serverError = e instanceof Error ? e.message : 'Failed to load initial signal'
      return null
    }),
    getActiveTrades({ status: 'OPEN', limit: 10 }).catch(() => []),
    getPortfolioStats().catch(() => null),
  ])
  initialBundle = bundleResult
  return (
    <HomeClient
      initialBundle={initialBundle}
      serverError={serverError}
      openTrades={openTrades}
      portfolioStats={stats}
    />
  )
}
