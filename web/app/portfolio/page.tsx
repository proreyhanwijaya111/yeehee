// Portfolio page — Server Component fetches active_trades + portfolio_stats
// from Supabase, hands to PortfolioClient for rendering.
//
// Why RSC: data-heavy, SEO-irrelevant but fast first paint matters.
// Revalidate every 30s (matches daemon heartbeat cadence).
import PortfolioClient from './PortfolioClient'
import {
  getActiveTrades, getPortfolioStats, getLatestSignalBundle,
  getEaHeartbeat, getEaConfig, getRealEaTrades,
} from '@/lib/server-api'

export const runtime = 'edge'

// 2026-05-07 self-host: 60s ISR. Balanced fresh-vs-Supabase-budget.
// Manual refresh + on-focus revalidation triggers fresh fetches on demand.
export const revalidate = 60

export default async function PortfolioPage() {
  let openTrades: Awaited<ReturnType<typeof getActiveTrades>> = []
  let closedTrades: Awaited<ReturnType<typeof getActiveTrades>> = []
  let realOpen: Awaited<ReturnType<typeof getActiveTrades>> = []
  let realClosed: Awaited<ReturnType<typeof getActiveTrades>> = []
  let stats: Awaited<ReturnType<typeof getPortfolioStats>> = null
  let xauPrice: number | null = null
  let eaHeartbeat: Awaited<ReturnType<typeof getEaHeartbeat>> = null
  let eaConfig: Awaited<ReturnType<typeof getEaConfig>> = null
  try {
    // Fetch BOTH paper (active_trades) AND real (rcs_executions)
    // Default UI shows real per user audit 2026-05-07 -- /portfolio MUST
    // reflect actual broker, paper hidden behind toggle for forward-test view.
    const [paperOpen, paperAll, s, bundle, hb, cfg, realAll] = await Promise.all([
      getActiveTrades({ status: 'OPEN', limit: 50 }),
      getActiveTrades({ status: 'all', limit: 50 }),
      getPortfolioStats(),
      getLatestSignalBundle(),
      getEaHeartbeat(),
      getEaConfig(),
      getRealEaTrades({ limit: 100 }),
    ])
    openTrades = paperOpen
    closedTrades = paperAll.filter(t => t.status !== 'OPEN')
    realOpen   = realAll.filter(t => t.status === 'OPEN')
    realClosed = realAll.filter(t => t.status !== 'OPEN')
    stats = s
    xauPrice = bundle?.xau_price ?? null
    eaHeartbeat = hb
    eaConfig = cfg
  } catch {
    // Silent — PortfolioClient renders empty state
  }
  return (
    <PortfolioClient
      openTrades={openTrades}
      closedTrades={closedTrades}
      realOpen={realOpen}
      realClosed={realClosed}
      stats={stats}
      xauPrice={xauPrice}
      eaHeartbeat={eaHeartbeat}
      eaConfig={eaConfig}
    />
  )
}
