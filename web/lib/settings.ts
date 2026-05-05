/**
 * Settings data layer — talks directly to Supabase.
 *
 * All functions are no-op safe: if Supabase isn't configured, they return
 * sensible defaults / null instead of throwing.
 */
import { supabase } from './supabase'

export type AppSettings = {
  user_id: string
  refresh_interval_minutes: number
  default_llm_provider: string
  default_llm_model: string
  use_per_agent_models: boolean
  use_llm_agents: boolean
  timezone: string
  daemon_active: boolean
  daemon_last_seen: string | null
  enable_news_blackout: boolean
  enable_mira_worker: boolean
  timeframe_focus: 'all' | 'scalping' | 'intraday' | 'swing'
}

export type ProviderKey = {
  provider: string
  api_key: string | null
  base_url: string | null
  enabled: boolean
  last_validated_at: string | null
  last_error: string | null
}

export type AgentConfig = {
  agent_name: string
  enabled: boolean
  llm_provider: string | null
  llm_model: string | null
  temperature: number
  max_tokens: number
  weight: number
  timeframes: string[]
  custom_prompt: string | null
}

export type DaemonHeartbeat = {
  hostname: string | null
  ip_address: string | null
  version: string | null
  worker_id: string | null
  trigger_reason: string | null
  last_signal_at: string | null
  last_mira_job_at: string | null
  cpu_percent: number | null
  ram_percent: number | null
  error: string | null
  updated_at: string
}

/** Multi-PC ready: one row per worker (migration 007). */
export type DaemonWorkerStatus = {
  user_id: string
  worker_id: string
  hostname: string | null
  ip_address: string | null
  version: string | null
  last_signal_at: string | null
  last_heartbeat_at: string
  heartbeat_age_seconds: number
  status: 'fresh' | 'recent' | 'stale'
  error: string | null
  cpu_percent: number | null
  ram_percent: number | null
  trigger_reason: string | null
}

export const PROVIDER_LABELS: Record<string, string> = {
  openrouter: 'OpenRouter',
  anthropic:  'Anthropic Claude',
  openai:     'OpenAI',
  groq:       'Groq Cloud',
  gemini:     'Google Gemini',
  ollama:     'Ollama (local)',
  lmstudio:   'LM Studio (local)',
}

export const PROVIDER_LIST = ['openrouter', 'anthropic', 'openai', 'groq', 'gemini', 'ollama', 'lmstudio']

export const AGENT_NAMES = [
  'htf_bias',
  'session_phase',
  'ltf_technical',
  'liquidity_smc',
  'order_flow',
  'pattern_recognition',
  'volume_profile',
  'news_proximity',
  'volatility',
  'backtest_memory',
  'devils_advocate',
  'synthesizer',
] as const
export type AgentName = typeof AGENT_NAMES[number]

export const AGENT_LABELS: Record<AgentName, string> = {
  htf_bias:            'HTF Bias',
  session_phase:       'Session Phase',
  ltf_technical:       'LTF Technical',
  liquidity_smc:       'Liquidity / SMC',
  order_flow:          'Order Flow',
  pattern_recognition: 'Pattern Recognition',
  volume_profile:      'Volume Profile',
  news_proximity:      'News Proximity',
  volatility:          'Volatility',
  backtest_memory:     'Backtest Memory',
  devils_advocate:     "Devil's Advocate",
  synthesizer:         'Synthesizer',
}

export const AGENT_DESCRIPTIONS: Record<AgentName, string> = {
  htf_bias:            'Multi-EMA hierarchy + ADX filter, sets directional bias.',
  session_phase:       'Asia/London/NY behavior, favourable for trigger?',
  ltf_technical:       'M5/M15 indicators + candle patterns, 3+ confluence.',
  liquidity_smc:       'Sweeps, FVG, Order Block, Breaker, Mitigation Block.',
  order_flow:          'COT positioning, volume spikes, stop hunts, absorption.',
  pattern_recognition: 'Classical chart patterns: H&S, triangles, flags, double top.',
  volume_profile:      'POC / VAH / VAL — value area mean revert + breakout.',
  news_proximity:      'Block trade if high-impact news imminent (NFP/CPI/FOMC).',
  volatility:          'ATR percentile + regime classifier, block if extreme.',
  backtest_memory:     'Query past similar setups, give prior probability.',
  devils_advocate:     'Argue against consensus, identify 8 critical risks, veto.',
  synthesizer:         'Final PM decision: weighted vote, hard vetoes, strength.',
}

const USER_ID = 'default'  // single-user for now

// ─── App Settings ─────────────────────────────────────────────────────────────

const DEFAULT_SETTINGS: AppSettings = {
  user_id: USER_ID,
  refresh_interval_minutes: 5,
  default_llm_provider: 'openrouter',
  default_llm_model:    'openai/gpt-oss-20b:free',
  use_per_agent_models: false,
  use_llm_agents:       true,
  timezone:             'Asia/Jakarta',
  daemon_active:        true,
  daemon_last_seen:     null,
  enable_news_blackout: true,
  enable_mira_worker:   true,
  timeframe_focus:      'all',
}

export async function getAppSettings(): Promise<AppSettings> {
  if (!supabase) return DEFAULT_SETTINGS
  const { data, error } = await supabase
    .from('app_settings')
    .select('*')
    .eq('user_id', USER_ID)
    .maybeSingle()
  if (error || !data) return DEFAULT_SETTINGS
  return { ...DEFAULT_SETTINGS, ...data }
}

export async function updateAppSettings(patch: Partial<AppSettings>): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('app_settings')
    .upsert({ user_id: USER_ID, ...patch, updated_at: new Date().toISOString() }, { onConflict: 'user_id' })
  return !error
}

// ─── Provider Keys ────────────────────────────────────────────────────────────

export async function getProviderKeys(): Promise<ProviderKey[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('provider_keys')
    .select('*')
    .eq('user_id', USER_ID)
  if (error || !data) return []
  return data as ProviderKey[]
}

export async function upsertProviderKey(provider: string, api_key: string, base_url?: string): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('provider_keys')
    .upsert({
      user_id: USER_ID,
      provider,
      api_key,
      base_url: base_url ?? null,
      enabled: true,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'user_id,provider' })
  return !error
}

export async function setProviderEnabled(provider: string, enabled: boolean): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('provider_keys')
    .update({ enabled, updated_at: new Date().toISOString() })
    .eq('user_id', USER_ID)
    .eq('provider', provider)
  return !error
}

export async function deleteProviderKey(provider: string): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('provider_keys')
    .delete()
    .eq('user_id', USER_ID)
    .eq('provider', provider)
  return !error
}

export async function recordProviderValidation(provider: string, ok: boolean, error_msg?: string): Promise<void> {
  if (!supabase) return
  await supabase
    .from('provider_keys')
    .update({
      last_validated_at: new Date().toISOString(),
      last_error: ok ? null : (error_msg ?? 'unknown error'),
    })
    .eq('user_id', USER_ID)
    .eq('provider', provider)
}

// ─── Agent Configs ────────────────────────────────────────────────────────────

export async function getAgentConfigs(): Promise<AgentConfig[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('agent_configs')
    .select('*')
    .eq('user_id', USER_ID)
    .order('agent_name')
  if (error || !data) return []
  return data as AgentConfig[]
}

export async function updateAgentConfig(agent_name: string, patch: Partial<AgentConfig>): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('agent_configs')
    .upsert({
      user_id: USER_ID,
      agent_name,
      ...patch,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'user_id,agent_name' })
  return !error
}

// ─── Daemon Heartbeat ─────────────────────────────────────────────────────────

export async function getDaemonHeartbeat(): Promise<DaemonHeartbeat | null> {
  if (!supabase) return null
  // Migration 007: multi-row per worker. Pick most recently updated as "the latest"
  const { data, error } = await supabase
    .from('daemon_heartbeat')
    .select('*')
    .eq('user_id', USER_ID)
    .order('updated_at', { ascending: false })
    .limit(1)
    .maybeSingle()
  if (error || !data) return null
  return data as DaemonHeartbeat
}

export function isDaemonOnline(hb: DaemonHeartbeat | null, withinMinutes = 5): boolean {
  if (!hb || !hb.updated_at) return false
  const last = new Date(hb.updated_at).getTime()
  return Date.now() - last < withinMinutes * 60_000
}

/** Multi-PC: list all workers seen for this user_id, with their freshness label. */
export async function getDaemonWorkers(): Promise<DaemonWorkerStatus[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('daemon_workers_status')
    .select('*')
    .eq('user_id', USER_ID)
  if (error || !data) {
    // Fall back: query daemon_heartbeat directly if view doesn't exist (mig 007 not applied)
    const fb = await supabase
      .from('daemon_heartbeat')
      .select('*')
      .eq('user_id', USER_ID)
      .order('updated_at', { ascending: false })
    if (fb.error || !fb.data) return []
    return fb.data
      .filter(r => r.worker_id)
      .map(r => ({
        user_id: r.user_id,
        worker_id: r.worker_id,
        hostname: r.hostname,
        ip_address: r.ip_address,
        version: r.version,
        last_signal_at: r.last_signal_at,
        last_heartbeat_at: r.updated_at,
        heartbeat_age_seconds: Math.floor((Date.now() - new Date(r.updated_at).getTime()) / 1000),
        status: (Date.now() - new Date(r.updated_at).getTime()) < 120_000 ? 'fresh'
              : (Date.now() - new Date(r.updated_at).getTime()) < 600_000 ? 'recent'
              : 'stale',
        error: r.error,
        cpu_percent: r.cpu_percent,
        ram_percent: r.ram_percent,
        trigger_reason: r.trigger_reason,
      }))
  }
  return data as DaemonWorkerStatus[]
}

/** Read which worker is currently elected primary (migration 007). */
export async function getActiveWorkerId(): Promise<string | null> {
  if (!supabase) return null
  const { data, error } = await supabase
    .from('app_settings')
    .select('active_worker_id')
    .eq('user_id', USER_ID)
    .maybeSingle()
  if (error || !data) return null
  return data.active_worker_id ?? null
}

/** Manually set the primary worker (admin override). Returns true on success. */
export async function setActiveWorkerId(workerId: string | null): Promise<boolean> {
  if (!supabase) return false
  const { error } = await supabase
    .from('app_settings')
    .update({
      active_worker_id: workerId,
      active_claimed_at: new Date().toISOString(),
    })
    .eq('user_id', USER_ID)
  return !error
}
