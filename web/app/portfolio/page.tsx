// Portfolio page — Server Component fetches active_trades + portfolio_stats
// from Supabase, hands to PortfolioClient for rendering.
//
// Why RSC: data-heavy, SEO-irrelevant but fast first paint matters.
// Revalidate every 30s (matches daemon heartbeat cadence).
import PortfolioClient from './PortfolioClient'
import { getActiveTrades, getPortfolioStats, getLatestSignalBundle, getEaHeartbeat, getEaConfig } from '@/lib/server-api'

export const revalidate = 30

export default async function PortfolioPage() {
  let openTrades: Awaited<ReturnType<typeof getActiveTrades>> = []
  let closedTrades: Awaited<ReturnType<typeof getActiveTrades>> = []
  let stats: Awaited<ReturnType<typeof getPortfolioStats>> = null
  let xauPrice: number | null = null
  let eaHeartbeat: Awaited<ReturnType<typeof getEaHeartbeat>> = null
  let eaConfig: Awaited<ReturnType<typeof getEaConfig>> = null
  try {
    const [open_, closed_, s, bundle, hb, cfg] = await Promise.all([
      getActiveTrades({ status: 'OPEN', limit: 50 }),
      getActiveTrades({ status: 'all', limit: 50 }),  // includes open, will filter on client
      getPortfolioStats(),
      getLatestSignalBundle(),
      getEaHeartbeat(),
      getEaConfig(),
    ])
    openTrades = open_
    closedTrades = closed_.filter(t => t.status !== 'OPEN')
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
      stats={stats}
      xauPrice={xauPrice}
      eaHeartbeat={eaHeartbeat}
      eaConfig={eaConfig}
    />
  )
}
