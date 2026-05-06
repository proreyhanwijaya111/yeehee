'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, Loader2, RotateCcw, Cpu } from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  getAgentConfigs, updateAgentConfig,
  getProviderKeys,
  PROVIDER_LIST, PROVIDER_LABELS,
  AGENT_NAMES, AGENT_LABELS, AGENT_DESCRIPTIONS,
  type AppSettings, type AgentConfig, type ProviderKey, type AgentName,
} from '@/lib/settings'
import { fetchModelsForProvider, type LLMModel } from '@/lib/llm-models'

const TIMEFRAMES = ['scalping', 'intraday', 'swing'] as const

const TIERS = [
  { tier: '1 - Bias',     agents: ['htf_bias', 'session_phase'] },
  { tier: '2 - Trigger',  agents: ['ltf_technical', 'liquidity_smc', 'order_flow', 'pattern_recognition', 'volume_profile'] },
  { tier: '3 - Risk',     agents: ['news_proximity', 'volatility', 'backtest_memory'] },
  { tier: '4 - Meta',     agents: ['devils_advocate'] },
  { tier: 'Final',        agents: ['synthesizer'] },
]

export default function AgentsSettingsPage() {
  const [settings,  setSettings]  = useState<AppSettings | null>(null)
  const [configs,   setConfigs]   = useState<Map<string, AgentConfig>>(new Map())
  const [providers, setProviders] = useState<Map<string, ProviderKey>>(new Map())
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    Promise.all([getAppSettings(), getAgentConfigs(), getProviderKeys()]).then(([s, a, p]) => {
      setSettings(s)
      const c = new Map<string, AgentConfig>()
      a.forEach(x => c.set(x.agent_name, x))
      AGENT_NAMES.forEach(n => {
        if (!c.has(n)) {
          c.set(n, {
            agent_name: n,
            enabled: true,
            llm_provider: null,
            llm_model: null,
            temperature: 0.4,
            max_tokens: 800,
            weight: 1.0,
            timeframes: ['scalping', 'intraday', 'swing'],
            custom_prompt: null,
          })
        }
      })
      setConfigs(c)
      const m = new Map<string, ProviderKey>()
      p.forEach(k => m.set(k.provider, k))
      setProviders(m)
      setLoading(false)
    })
  }, [])

  if (loading || !settings) return <FullPageLoader />

  const updateLocal = async (name: string, patch: Partial<AgentConfig>) => {
    const next = new Map(configs)
    const cur = next.get(name)!
    next.set(name, { ...cur, ...patch })
    setConfigs(next)
    await updateAgentConfig(name, patch)
  }

  const resetAll = async () => {
    if (!confirm('Reset semua agent ke default?')) return
    for (const n of AGENT_NAMES) {
      await updateAgentConfig(n, {
        enabled: true, llm_provider: null, llm_model: null,
        temperature: 0.4, max_tokens: 800, weight: 1.0,
        timeframes: ['scalping', 'intraday', 'swing'], custom_prompt: null,
      })
    }
    location.reload()
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-sky-700/30 border border-sky-600/30 flex items-center justify-center">
          <Cpu size={16} className="text-sky-300" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-black text-slate-100 leading-tight">9 AI Agent</h1>
          <p className="text-[11px] text-slate-500">Tier pipeline: bias → trigger → risk → meta → synth.</p>
        </div>
        <button onClick={resetAll} className="p-1.5 text-slate-500 hover:text-slate-300" title="Reset ke default">
          <RotateCcw size={14} />
        </button>
      </header>

      <div className="space-y-5">
        {/* Tutorial intro */}
        <div className="bg-sky-950/30 border border-sky-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
          <p className="text-sky-100 font-semibold mb-1.5">Apa ini buat?</p>
          <p className="text-sky-200/80 mb-2">
            Halaman ini buat <span className="font-bold">tweak advanced</span>. Default-nya udah optimal — kebanyakan user ga perlu ubah apa-apa di sini.
          </p>
          <p className="text-sky-200/70">
            Sistem yeehee pakai 12 expert AI agent (HTF Bias, LTF Technical, SMC, Order Flow, dll) yang debate sebelum kasih final signal. Halaman ini buat:
          </p>
          <ul className="list-disc pl-4 mt-1 space-y-0.5 text-sky-200/70">
            <li>Disable agent tertentu (e.g. matiin Pattern Recognition)</li>
            <li>Override per-agent: pakai model LLM beda untuk agent specific (e.g. Devil's Advocate pakai Claude, sisanya pakai Llama)</li>
            <li>Adjust temperature / max_tokens per agent</li>
          </ul>
          <p className="text-amber-300/80 mt-2">
            ⚠️ Kalau lo bingung mau ubah apa, biarin default. Default udah tested dan kerja baik.
          </p>
        </div>

        {/* Engine mode (NEW — local 12-agent vs LLM 12-agent) */}
        <Group title="Engine mode">
          <div className="px-3.5 py-3 space-y-3 text-[11px] text-slate-300">
            <p className="text-slate-400 leading-relaxed">
              Pilih cara 12 agent dijalanin. Default = <span className="text-emerald-400 font-semibold">Local</span> (gratis, cepat, deterministic, 100% offline AI).
            </p>
            <RadioRow
              checked={settings.use_local_agents !== false}
              label="Local rule-based (recommended)"
              sub="12 agent jalan murni di PC rumah. Pattern Expert dari spec_v2 (15 candlestick + stats backtest 16 thn). Cycle ~3-5 detik konsisten. Free."
              onChange={async () => {
                setSettings({ ...settings, use_local_agents: true })
                await updateAppSettings({ use_local_agents: true })
              }}
            />
            <RadioRow
              checked={settings.use_local_agents === false}
              label="LLM 12-agent (legacy)"
              sub="12 agent via API call (OpenRouter/Groq/dll). Cycle 10-200s, butuh internet + API key. Pakai cuma kalo lo specifically butuh AI reasoning narrative."
              onChange={async () => {
                setSettings({ ...settings, use_local_agents: false })
                await updateAppSettings({ use_local_agents: false })
              }}
            />
          </div>

          <div className="border-t border-slate-800/80 px-3.5 py-3 space-y-3 text-[11px] text-slate-300">
            <p className="text-slate-400 font-semibold">
              Devil&rsquo;s Advocate engine (sub-toggle)
            </p>
            <p className="text-slate-500 leading-relaxed">
              DA = agent yg argue against consensus + identify hidden risks. Bisa pake LLM untuk semantic reasoning yg lebih dalam (gak available di local rule).
            </p>
            <RadioRow
              checked={settings.da_engine !== 'llm'}
              label="Local rule-based (default)"
              sub="7 catastrophic risk patterns deterministic: news blackout, RSI extreme, BB rejection, ATR percentile, counter-HTF-trend, agent disagreement, Asia session."
              onChange={async () => {
                setSettings({ ...settings, da_engine: 'local' })
                await updateAppSettings({ da_engine: 'local' })
              }}
            />
            <RadioRow
              checked={settings.da_engine === 'llm'}
              label="LLM (premium semantic)"
              sub="Pakai default LLM provider+model dari Pengaturan LLM. Auto-fallback ke local kalau LLM gagal/timeout. Cost ~$0.01-0.03/cycle dengan Sonnet 4.6 + caching."
              onChange={async () => {
                setSettings({ ...settings, da_engine: 'llm' })
                await updateAppSettings({ da_engine: 'llm' })
              }}
            />
            {settings.da_engine === 'llm' && (
              <div className="bg-amber-950/30 border border-amber-800/40 rounded-lg px-3 py-2 text-[10px] leading-relaxed text-amber-200/90">
                <p className="font-semibold mb-1">⚠ DA pakai LLM</p>
                <p>Provider: <span className="font-mono text-amber-100">{settings.da_llm_provider || settings.default_llm_provider || '(default)'}</span></p>
                <p>Model: <span className="font-mono text-amber-100">{settings.da_llm_model || settings.default_llm_model || '(default)'}</span></p>
                <p className="mt-1 text-amber-200/70">Atur per-agent override di list bawah jika mau pake provider/model beda.</p>
              </div>
            )}
          </div>
        </Group>

        {/* Audit page link */}
        <Link
          href="/more/settings/agents/audit"
          className="block bg-slate-800/40 hover:bg-slate-800/60 border border-slate-800 rounded-2xl px-3.5 py-3 text-[11px] text-slate-300 transition-colors"
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold text-slate-100">Audit log per cycle</p>
              <p className="text-slate-500 mt-0.5">Lihat verdict tiap agent + fallback log + engine stats 24h</p>
            </div>
            <span className="text-slate-600">→</span>
          </div>
        </Link>

        {/* Legacy LLM master switch (only shown when local mode OFF) */}
        {settings.use_local_agents === false && (
          <Group title="Legacy LLM agent toggle">
            <ToggleRow
              label="Pakai LLM agent"
              sub="Aktif: 12 LLM agent + weighted voting. Mati: fall back ke rule engine 4-agent simplified."
              checked={settings.use_llm_agents}
              onChange={async v => {
                setSettings({ ...settings, use_llm_agents: v })
                await updateAppSettings({ use_llm_agents: v })
              }}
            />
          </Group>
        )}

        {/* Pipeline diagram */}
        <Group title="Pipeline aktif">
          <div className="px-3.5 py-3 space-y-1.5">
            {TIERS.map(t => (
              <div key={t.tier} className="flex items-center gap-2 text-[10px]">
                <span className="text-slate-500 w-16 shrink-0 font-mono uppercase tracking-wider">{t.tier}</span>
                <div className="flex flex-wrap gap-1">
                  {t.agents.map(a => {
                    const c = configs.get(a)
                    return (
                      <span
                        key={a}
                        className={`px-1.5 py-0.5 rounded font-mono ${
                          c?.enabled
                            ? 'bg-sky-900/40 text-sky-200 border border-sky-800/50'
                            : 'bg-slate-800/60 text-slate-600 line-through'
                        }`}
                      >
                        {AGENT_LABELS[a as AgentName]}
                      </span>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </Group>

        {/* Per-agent cards */}
        <Group title="Konfigurasi per agent">
          {AGENT_NAMES.map(name => (
            <AgentRow
              key={name}
              name={name}
              config={configs.get(name)!}
              globalProvider={settings.default_llm_provider}
              globalModel={settings.default_llm_model}
              usePerAgent={settings.use_per_agent_models}
              providers={providers}
              onUpdate={patch => updateLocal(name, patch)}
            />
          ))}
        </Group>
      </div>
    </main>
  )
}

function AgentRow({
  name, config, globalProvider, globalModel, usePerAgent, providers, onUpdate,
}: {
  name: AgentName
  config: AgentConfig
  globalProvider: string
  globalModel: string
  usePerAgent: boolean
  providers: Map<string, ProviderKey>
  onUpdate: (patch: Partial<AgentConfig>) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [models, setModels] = useState<LLMModel[]>([])
  const [modelLoading, setModelLoading] = useState(false)

  const effectiveProvider = config.llm_provider ?? globalProvider

  useEffect(() => {
    if (!expanded || !usePerAgent) return
    const k = providers.get(effectiveProvider)
    setModelLoading(true)
    fetchModelsForProvider(effectiveProvider, k?.api_key ?? undefined, k?.base_url ?? undefined)
      .then(setModels).catch(() => setModels([]))
      .finally(() => setModelLoading(false))
  }, [expanded, effectiveProvider, usePerAgent, providers])

  return (
    <div className="overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3.5 py-3 hover:bg-slate-800/40 active:bg-slate-800/70 transition-colors"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${config.enabled ? 'bg-emerald-500' : 'bg-slate-600'}`} />
        <div className="flex-1 min-w-0 text-left">
          <p className="text-sm font-medium text-slate-100 leading-tight">{AGENT_LABELS[name]}</p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">{AGENT_DESCRIPTIONS[name]}</p>
        </div>
        {usePerAgent && config.llm_model && (
          <span className="text-[9px] text-sky-400 font-mono shrink-0 max-w-[100px] truncate">
            {config.llm_model.replace(':free', '')}
          </span>
        )}
        <ChevronDown size={14} className={`text-slate-500 transition-transform shrink-0 ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="px-3.5 pb-3.5 pt-1 space-y-3 border-t border-slate-800/80">
          {/* Enable */}
          <label className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-300">Aktif</span>
            <Toggle checked={config.enabled} onChange={v => onUpdate({ enabled: v })} />
          </label>

          {/* Per-agent LLM */}
          {usePerAgent && (
            <>
              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Provider override</label>
                <select
                  value={config.llm_provider ?? ''}
                  onChange={e => onUpdate({ llm_provider: e.target.value || null })}
                  className="mt-1 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-sky-500"
                >
                  <option value="">(default: {PROVIDER_LABELS[globalProvider]})</option>
                  {PROVIDER_LIST.map(p => <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>)}
                </select>
              </div>

              <div>
                <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold flex items-center justify-between">
                  Model override
                  {modelLoading && <Loader2 size={10} className="animate-spin" />}
                </label>
                <select
                  value={config.llm_model ?? ''}
                  onChange={e => onUpdate({ llm_model: e.target.value || null })}
                  className="mt-1 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
                >
                  <option value="">(default: {globalModel})</option>
                  {models.filter(m => m.free).slice(0, 50).map(m => (
                    <option key={m.id} value={m.id}>{m.id}{m.free ? ' · free' : ''}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {/* Sliders */}
          <div className="grid grid-cols-2 gap-3">
            <Slider
              label="Temperature"
              value={config.temperature}
              min={0} max={1} step={0.05}
              format={v => v.toFixed(2)}
              onChange={v => onUpdate({ temperature: v })}
            />
            <Slider
              label="Weight"
              value={config.weight}
              min={0} max={3} step={0.1}
              format={v => v.toFixed(2)}
              onChange={v => onUpdate({ weight: v })}
            />
          </div>

          <Slider
            label="Max tokens"
            value={config.max_tokens}
            min={100} max={2000} step={50}
            format={v => v.toString()}
            onChange={v => onUpdate({ max_tokens: v })}
          />

          {/* Timeframes */}
          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold mb-1 block">
              Timeframes aktif
            </label>
            <div className="grid grid-cols-3 gap-1.5">
              {TIMEFRAMES.map(t => {
                const selected = config.timeframes.includes(t)
                return (
                  <button
                    key={t}
                    onClick={() => onUpdate({
                      timeframes: selected
                        ? config.timeframes.filter(x => x !== t)
                        : [...config.timeframes, t],
                    })}
                    className={`py-1.5 rounded-lg text-[10px] font-semibold transition-colors ${
                      selected
                        ? 'bg-sky-700/40 text-sky-200 border border-sky-700/60'
                        : 'bg-slate-800/60 text-slate-500 border border-slate-700/60'
                    }`}
                  >
                    {t}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Custom prompt */}
          <details className="text-[11px]">
            <summary className="text-slate-500 cursor-pointer hover:text-slate-300 select-none">
              Custom prompt (advanced)
            </summary>
            <textarea
              value={config.custom_prompt ?? ''}
              onChange={e => onUpdate({ custom_prompt: e.target.value || null })}
              placeholder="(default system prompt)"
              rows={4}
              className="mt-2 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
            />
          </details>
        </div>
      )}
    </div>
  )
}

// ─── Building blocks ──────────────────────────────────────────────────────────

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">{title}</p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
        {children}
      </div>
    </section>
  )
}

function Slider({ label, value, min, max, step, format, onChange }: {
  label: string
  value: number
  min: number; max: number; step: number
  format: (v: number) => string
  onChange: (v: number) => void
}) {
  return (
    <div>
      <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold flex items-center justify-between">
        <span>{label}</span>
        <span className="text-slate-300 font-mono">{format(value)}</span>
      </label>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full mt-1 accent-sky-500"
      />
    </div>
  )
}

function ToggleRow({ label, sub, checked, onChange }: {
  label: string; sub: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 px-3.5 py-3 cursor-pointer hover:bg-slate-800/40">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 leading-tight">{label}</p>
        <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">{sub}</p>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </label>
  )
}

function RadioRow({ label, sub, checked, onChange }: {
  label: string; sub: string; checked: boolean; onChange: () => void
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={`w-full text-left rounded-xl border px-3 py-2.5 transition-colors ${
        checked
          ? 'bg-emerald-950/30 border-emerald-700/50'
          : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
      }`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 shrink-0 ${
          checked ? 'border-emerald-400 bg-emerald-500' : 'border-slate-600'
        }`}>
          {checked && <span className="block w-1.5 h-1.5 m-auto mt-[3px] bg-white rounded-full" />}
        </span>
        <div className="flex-1 min-w-0">
          <p className={`text-[11px] font-semibold ${checked ? 'text-emerald-200' : 'text-slate-200'}`}>
            {label}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{sub}</p>
        </div>
      </div>
    </button>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      type="button"
      className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${
        checked ? 'bg-emerald-600' : 'bg-slate-700'
      }`}
    >
      <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
        checked ? 'translate-x-4' : 'translate-x-0.5'
      }`} />
    </button>
  )
}

function FullPageLoader() {
  return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )
}
