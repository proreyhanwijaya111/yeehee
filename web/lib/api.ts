/**
 * Frontend data layer.
 *
 * Architecture (post-pivot):
 * - Frontend reads signals/calendar/heartbeat directly from Supabase (no FastAPI).
 * - Daemon at user's home PC writes signal_bundles + signals + heartbeat to Supabase.
 * - Math operations (calcPosition) run client-side - pure functions, no backend.
 * - Backtest/chart still optional (not implemented yet without backend).
 */
import { supabase } from './supabase'
import type {
  SignalBundle, PositionPlan, PositionRequest,
  BacktestResult, CalendarEvent, ChartBar,
  TradeAction, SignalStrength,
} from './types'

// ── Signal bundles (latest from Supabase) ───────────────────────────────────────

export async function getSignals(_key: string, _refresh = false): Promise<SignalBundle> {
  if (!supabase) {
    throw new Error('Supabase belum dikonfigurasi. Set NEXT_PUBLIC_SUPABASE_URL + ANON_KEY di Vercel env.')
  }
  const { data, error } = await supabase
    .from('signal_bundles')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle()

  if (error) throw new Error(`Supabase error: ${error.message}`)
  if (!data) {
    throw new Error('Belum ada signal di database. Pastikan daemon di PC rumah jalan dan sudah push minimal 1 cycle.')
  }

  return mapBundleRowToSignalBundle(data)
}

// ── Calendar (read upcoming_events from latest bundle) ──────────────────────────

export async function getCalendar(): Promise<CalendarEvent[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('signal_bundles')
    .select('upcoming_events, blackout_event')
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle()
  if (error || !data) return []

  const upcoming = (data.upcoming_events ?? []) as Array<{
    title?: string; when_utc?: string; currency?: string; impact?: string;
    forecast?: string | null; previous?: string | null;
  }>
  return upcoming.map(e => ({
    when_utc: String(e.when_utc ?? ''),
    currency: String(e.currency ?? ''),
    impact:   String(e.impact ?? 'LOW').toUpperCase(),
    title:    String(e.title ?? '(no title)'),
    forecast: e.forecast ?? null,
    previous: e.previous ?? null,
  }))
}

// ── Position calculator (pure client-side TypeScript port from risk/sizing.py) ─

const RISK_PROFILES: Record<string, { risk: number; max_daily: number; label: string }> = {
  konservatif: { risk: 0.005, max_daily: 0.02, label: 'Konservatif' },
  moderat:     { risk: 0.010, max_daily: 0.04, label: 'Moderat' },
  agresif:     { risk: 0.020, max_daily: 0.06, label: 'Agresif' },
  bebas:       { risk: 0.050, max_daily: 0.20, label: 'Bebas' },
}

const CONTRACT_SIZE_OZ = 100  // 1 standard lot = 100 oz

export async function calcPosition(req: PositionRequest): Promise<PositionPlan> {
  const warnings: string[] = []

  let profile = req.profile
  if (!RISK_PROFILES[profile]) {
    warnings.push(`unknown profile ${profile} -> fallback moderat`)
    profile = 'moderat'
  }
  const cfg = RISK_PROFILES[profile]
  const risk_pct = req.custom_risk_pct ?? cfg.risk

  if (req.equity_usd <= 0) {
    warnings.push('equity harus > 0')
    return emptyPlan(profile, warnings)
  }
  if (req.entry <= 0 || req.sl <= 0) {
    warnings.push('entry / SL ga valid')
    return emptyPlan(profile, warnings)
  }

  const sl_dist = Math.abs(req.entry - req.sl)
  if (sl_dist === 0) {
    warnings.push('entry == sl, ga bisa size posisi')
    return emptyPlan(profile, warnings)
  }

  const risk_amount = req.equity_usd * risk_pct

  // P&L per oz = sl_dist USD/oz
  // units = risk_amount / sl_dist
  let units_oz = risk_amount / sl_dist

  // Convert to lots (round to micro lot 0.01)
  let lot_size = units_oz / CONTRACT_SIZE_OZ
  lot_size = Math.round(lot_size * 100) / 100
  units_oz = lot_size * CONTRACT_SIZE_OZ

  let notional = units_oz * req.entry
  let leverage = req.equity_usd > 0 ? notional / req.equity_usd : 0

  if (leverage > req.broker_max_leverage) {
    warnings.push(`required leverage ${leverage.toFixed(1)}x > broker max ${req.broker_max_leverage}x — reduce risk atau tambah modal`)
    // Cap to broker max
    const lot_cap = (req.equity_usd * req.broker_max_leverage) / (req.entry * CONTRACT_SIZE_OZ)
    lot_size = Math.round(lot_cap * 100) / 100
    units_oz = lot_size * CONTRACT_SIZE_OZ
    notional = units_oz * req.entry
    leverage = req.equity_usd > 0 ? notional / req.equity_usd : 0
  }

  const margin = notional / Math.max(req.broker_max_leverage, 1)
  const pip_value = units_oz * 0.01

  const payoff = {
    tp1: units_oz * Math.abs(req.tp1 - req.entry),
    tp2: units_oz * Math.abs(req.tp2 - req.entry),
    tp3: units_oz * Math.abs(req.tp3 - req.entry),
  }

  if (risk_pct > 0.05) {
    warnings.push(`risk ${(risk_pct * 100).toFixed(1)}% per trade SANGAT TINGGI - cuma sustainable kalau win rate >70%`)
  }

  return {
    lot_size,
    units_oz,
    risk_amount_usd:    Math.round(risk_amount * 100) / 100,
    risk_pct:           Math.round(risk_pct * 10000) / 10000,
    leverage_used:      Math.round(leverage * 100) / 100,
    pip_value_usd:      Math.round(pip_value * 10000) / 10000,
    notional_value_usd: Math.round(notional * 100) / 100,
    margin_required_usd: Math.round(margin * 100) / 100,
    expected_payoff_usd: {
      tp1: Math.round(payoff.tp1 * 100) / 100,
      tp2: Math.round(payoff.tp2 * 100) / 100,
      tp3: Math.round(payoff.tp3 * 100) / 100,
    },
    profile,
    warnings,
  }
}

function emptyPlan(profile: string, warnings: string[]): PositionPlan {
  return {
    lot_size: 0, units_oz: 0,
    risk_amount_usd: 0, risk_pct: 0,
    leverage_used: 0, pip_value_usd: 0,
    notional_value_usd: 0, margin_required_usd: 0,
    expected_payoff_usd: { tp1: 0, tp2: 0, tp3: 0 },
    profile, warnings,
  }
}

export async function getRiskProfiles() {
  return RISK_PROFILES
}

// ── Backtest (Vercel Edge API: /api/backtest, Monte Carlo TS port) ─────────────

export interface MCBacktestRequest {
  starting_equity: number
  risk_per_trade:  number    // 0..1
  n_runs:          number
  n_trades?:       number    // default 100
  win_rate?:       number    // default 0.5
  avg_win_r?:      number    // default 1.5
  avg_loss_r?:     number    // default -1
  blowup_dd_pct?:  number    // default 0.5
}

export interface MCBacktestResult {
  inputs: Required<MCBacktestRequest>
  percentiles: {
    final_equity: { p5: number; p25: number; p50: number; p75: number; p95: number }
    max_drawdown: { p5: number; p50: number; p95: number }
  }
  probabilities: {
    profit: number; drawdown_30: number; drawdown_50: number; blowup: number
  }
  expected_return_pct: number
  expectancy_r: number
  n_runs: number
  duration_ms: number
}

export async function runBacktest(params: MCBacktestRequest): Promise<MCBacktestResult> {
  const res = await fetch('/api/backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Backtest gagal HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

// Legacy alias - dipakai oleh halaman /more/backtest sebelum refactor.
export async function runBacktestLegacy(params: {
  interval: string
  starting_equity: number
  risk_per_trade: number
  mc_runs: number
}): Promise<BacktestResult> {
  // Bridge ke MC engine baru. Map field name lama -> baru.
  const mc = await runBacktest({
    starting_equity: params.starting_equity,
    risk_per_trade:  params.risk_per_trade,
    n_runs:          params.mc_runs,
  })
  // Adapt ke shape BacktestResult lama (pseudo, data utama ada di MC).
  return {
    stats: {
      n_trades:         mc.inputs.n_trades,
      win_rate:         mc.inputs.win_rate,
      expectancy_r:     mc.expectancy_r,
      total_return_pct: mc.expected_return_pct,
      max_drawdown_pct: mc.percentiles.max_drawdown.p50,
      sharpe:           0,
    },
    monte_carlo: {
      final_equity_p5:  mc.percentiles.final_equity.p5,
      final_equity_p50: mc.percentiles.final_equity.p50,
      final_equity_p95: mc.percentiles.final_equity.p95,
      max_dd_p5:        mc.percentiles.max_drawdown.p5,
      max_dd_p50:       mc.percentiles.max_drawdown.p50,
      prob_profit:      mc.probabilities.profit,
      prob_30pct_dd:    mc.probabilities.drawdown_30,
      prob_blowup:      mc.probabilities.blowup,
      starting_equity:  mc.inputs.starting_equity,
    },
    n_bars:       0,
    equity_curve: [],
    trades:       [],
  }
}

// ── Chart data (deferred — daemon could push or use external API) ──────────────

export async function getChartData(_interval: string, _bars = 200): Promise<ChartBar[]> {
  return []  // placeholder; can be implemented via Supabase price_history table later
}

// ── Cache clear (no-op now since we read directly from Supabase) ────────────────

export async function clearApiCache(): Promise<void> {
  // No client cache; SWR handles its own cache. Force re-fetch by mutating SWR key.
  return
}

// ── Mappers ─────────────────────────────────────────────────────────────────────

function mapBundleRowToSignalBundle(row: Record<string, unknown>): SignalBundle {
  const debate = (row.debate as Record<string, unknown>) ?? {}
  return {
    xau_price:        Number(row.xau_price ?? 0),
    timestamp:        String(row.created_at ?? new Date().toISOString()),
    regime:           String(row.regime ?? 'unknown'),
    session:          String(row.session ?? 'unknown'),
    in_news_blackout: Boolean(row.in_news_blackout),
    blackout_event:   (row.blackout_event as SignalBundle['blackout_event']) ?? null,
    upcoming_events:  (row.upcoming_events as SignalBundle['upcoming_events']) ?? [],
    scalper_signal:   normaliseSignal(row.scalper_signal),
    intraday_signal:  normaliseSignal(row.intraday_signal),
    swing_signal:     normaliseSignal(row.swing_signal),
    debate: {
      final_action:    (debate.final_action as TradeAction) ?? 'FLAT',
      signal_strength: (debate.signal_strength as SignalStrength) ?? 'FLAT',
      confidence:      Number(debate.confidence ?? 0),
      primary_driver:  String(debate.primary_driver ?? ''),
      agents:          Array.isArray(debate.agents) ? debate.agents as SignalBundle['debate']['agents'] : [],
      reasoning_chain: Array.isArray(debate.reasoning_chain) ? debate.reasoning_chain as string[] : [],
      risks:           Array.isArray(debate.risks) ? debate.risks as string[] : [],
    },
    intermarket: (row.intermarket as SignalBundle['intermarket']) ?? {
      score: 0, components: { dxy: 0, us10y: 0, vix: 0, spx: 0, gold_silver: 0 },
    },
    cot: (row.cot as SignalBundle['cot']) ?? { z: null, net_long: null, signal: null },
    ai_pm_used:      Boolean(row.ai_pm_used),
    final_action:    (row.final_action as TradeAction) ?? 'FLAT',
    signal_strength: (row.signal_strength as SignalStrength) ?? 'FLAT',
    confidence:      Number(row.confidence ?? 0),
  }
}

function normaliseSignal(raw: unknown): SignalBundle['scalper_signal'] {
  const r = (raw as Record<string, unknown>) ?? {}
  // Daemon stores signal under field "action" but frontend expects "side"
  const side = (r.side ?? r.action ?? 'FLAT') as TradeAction
  return {
    side,
    confidence:       Number(r.confidence ?? 0),
    confluence_count: Number(r.confluence_count ?? r.confluence ?? 0),
    entry:            Number(r.entry ?? 0),
    sl:               Number(r.sl ?? 0),
    tp1:              Number(r.tp1 ?? 0),
    tp2:              Number(r.tp2 ?? 0),
    tp3:              Number(r.tp3 ?? 0),
    rr_to_tp1:        Number(r.rr_to_tp1 ?? 0),
    rr_to_tp2:        Number(r.rr_to_tp2 ?? 0),
    regime:           String(r.regime ?? ''),
    session:          String(r.session ?? ''),
    timestamp:        String(r.timestamp ?? ''),
    reasons:          Array.isArray(r.reasons) ? r.reasons as string[] : [],
    risks:            Array.isArray(r.risks)   ? r.risks   as string[] : [],
  }
}
