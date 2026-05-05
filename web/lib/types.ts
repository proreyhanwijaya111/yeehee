// ── yeehee — TypeScript Types ─────────────────────────────────────────────────

export type TradeAction    = 'LONG' | 'SHORT' | 'FLAT'
export type SignalStrength = 'STRONG' | 'NEWS_STRONG' | 'NORMAL' | 'WEAK' | 'FLAT'
export type TradingStyle   = 'scalper' | 'intraday' | 'swing'
export type RiskProfile    = 'konservatif' | 'moderat' | 'agresif' | 'bebas'

export interface Signal {
  side:             TradeAction
  confidence:       number        // 0..1
  confluence_count: number
  entry:            number
  sl:               number
  tp1:              number
  tp2:              number
  tp3:              number
  rr_to_tp1:        number
  rr_to_tp2:        number
  regime:           string
  session:          string
  timestamp:        string
  reasons:          string[]
  risks:            string[]
}

export interface AgentVerdict {
  name:       string
  verdict:    TradeAction
  confidence: number
  reasoning:  string[]
}

export interface Debate {
  final_action:    TradeAction
  signal_strength: SignalStrength
  confidence:      number
  primary_driver:  string
  agents:          AgentVerdict[]
  reasoning_chain: string[]
  risks:           string[]
}

// Each intermarket component punya note + score (-1..+1) + value (raw market price)
// Daemon push pakai struktur ini dari features/intermarket.py
export interface IntermarketComponent {
  note?:  string
  score?: number
  value?: number
}

export interface IntermarketComponents {
  dxy?:         IntermarketComponent
  us10y?:       IntermarketComponent
  vix?:         IntermarketComponent
  spx?:         IntermarketComponent
  gold_silver?: IntermarketComponent
}

export interface Intermarket {
  score:      number   // -1..+1 weighted bias
  note?:      string
  components: IntermarketComponents
}

export interface COT {
  z:        number | null
  note?:    string
  signal?:  string | number | null   // daemon kadang push number (0/1/-1) kadang string
  net_long?: number | null
}

export interface CalendarEvent {
  when_utc:  string
  currency:  string
  impact:    string   // HIGH / MEDIUM / LOW
  title:     string
  forecast:  string | null
  previous:  string | null
}

export interface NewsEvent {
  when_utc:  string
  currency:  string
  title:     string
}

export interface SignalBundle {
  xau_price:        number
  timestamp:        string
  regime:           string
  session:          string
  in_news_blackout: boolean
  blackout_event:   NewsEvent | null
  upcoming_events:  NewsEvent[]
  scalper_signal:   Signal
  intraday_signal:  Signal
  swing_signal:     Signal
  debate:           Debate
  intermarket:      Intermarket
  cot:              COT
  ai_pm_used:       boolean
  final_action:     TradeAction
  signal_strength:  SignalStrength
  confidence:       number
  /** Opsi B: why this cycle ran. 'scheduled' | 'price_spike_up_X.XXpct' | 'ema9_21_bullish_cross' | 'atr_explosion_X.Xx' | 'volume_spike_X.Xx' | 'blackout_exit' | 'manual' */
  trigger_reason?:  string
}

export interface PositionPlan {
  lot_size:            number
  units_oz:            number
  risk_amount_usd:     number
  risk_pct:            number
  leverage_used:       number
  pip_value_usd:       number
  notional_value_usd:  number
  margin_required_usd: number
  expected_payoff_usd: { tp1: number; tp2: number; tp3: number }
  profile:             string
  warnings:            string[]
}

export interface PositionRequest {
  equity_usd:           number
  entry:                number
  sl:                   number
  tp1:                  number
  tp2:                  number
  tp3:                  number
  side:                 TradeAction
  profile:              RiskProfile
  broker_max_leverage:  number
  custom_risk_pct:      number | null
}

export interface BacktestStats {
  n_trades:           number
  win_rate:           number
  expectancy_r:       number
  total_return_pct:   number
  max_drawdown_pct:   number
  sharpe:             number
}

export interface MCResult {
  final_equity_p5:   number
  final_equity_p50:  number
  final_equity_p95:  number
  max_dd_p5:         number
  max_dd_p50:        number
  prob_profit:       number
  prob_30pct_dd:     number
  prob_blowup:       number
  starting_equity:   number
}

export interface BacktestResult {
  stats:        BacktestStats
  monte_carlo:  MCResult
  n_bars:       number
  equity_curve: number[]
  trades:       Array<{
    entry_price: number
    exit_price:  number
    pnl_r:       number
    pnl_usd:     number
    side:        string
  }>
}

export interface ChartBar {
  time:   number  // unix timestamp
  open:   number
  high:   number
  low:    number
  close:  number
  volume: number
  ema21:  number | null
  ema50:  number | null
  ema200: number | null
  rsi14:  number | null
  adx:    number | null
  regime: string
}
