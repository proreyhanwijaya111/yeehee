import type {
  SignalBundle, PositionPlan, PositionRequest,
  BacktestResult, CalendarEvent, ChartBar,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

/** SWR key = function name string */

export async function getSignals(key: string, refresh = false): Promise<SignalBundle> {
  const qs = refresh ? '?refresh=true' : ''
  return request<SignalBundle>(`/api/signals${qs}`)
}

export async function calcPosition(req: PositionRequest): Promise<PositionPlan> {
  return request<PositionPlan>('/api/position', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function getCalendar(): Promise<CalendarEvent[]> {
  return request<CalendarEvent[]>('/api/calendar')
}

export async function runBacktest(params: {
  interval: string
  starting_equity: number
  risk_per_trade: number
  mc_runs: number
}): Promise<BacktestResult> {
  return request<BacktestResult>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function getChartData(interval: string, bars = 200): Promise<ChartBar[]> {
  const data = await request<{ data: ChartBar[] }>(`/api/chart/${interval}?bars=${bars}`)
  return data.data
}

export async function getRiskProfiles(): Promise<Record<string, {
  risk_per_trade: number
  max_daily_loss: number
  label: string
}>> {
  return request('/api/risk-profiles')
}

export async function clearApiCache(): Promise<void> {
  await request('/api/cache', { method: 'DELETE' })
}
