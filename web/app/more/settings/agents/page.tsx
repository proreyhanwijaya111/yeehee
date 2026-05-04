'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, Loader2, RotateCcw } from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  getAgentConfigs, updateAgentConfig,
  getProviderKeys,
  PROVIDER_LIST, PROVIDER_LABELS,
  AGENT_NAMES, AGENT_LABELS, AGENT_DESCRIPTIONS,
  type AppSettings, type AgentConfig, type ProviderKey, type AgentName,
} from '@/lib/settings'
import { fetchModelsForProvider, type LLMModel } from '@/lib/llm-models'

const TIMEFRAME_OPTIONS = ['scalping', 'intraday', 'swing'] as const

export default function AgentsSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [configs, setConfigs] = useState<Map<string, AgentConfig>>(new Map())
  const [providers, setProviders] = useState<Map<string, ProviderKey>>(new Map())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getAppSettings(), getAgentConfigs(), getProviderKeys()]).then(([s, a, p]) => {
      setSettings(s)
      const c = new Map<string, AgentConfig>()
      a.forEach(x => c.set(x.agent_name, x))
      // Fill missing with defaults
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
    location.reload()
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <header className="flex items-center gap-2">
        <Link href="/more/settings" className="p-1.5 hover:bg-slate-800 rounded-lg">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="flex-1">
          <h1 className="text-lg font-black text-slate-100">9 AI Agent</h1>
          <p className="text-[11px] text-slate-400">Tier pipeline: bias → trigger → risk → meta → synth.</p>
        </div>
        <button onClick={resetAll} className="p-1.5 text-slate-400 hover:text-slate-200" title="Reset all">
          <RotateCcw size={16} />
        </button>
      </header>

      {/* Master switch */}
      <section className="bg-slate-800/60 border border-slate-700/50 rounded-2xl p-4">
        <label className="flex items-center justify-between gap-3 cursor-pointer">
          <div>
            <p className="text-sm font-semibold text-slate-100">Pakai LLM Agent</p>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Aktif: 9 LLM agent + voting. Mati: rule-engine deterministik aja.
            </p>
          </div>
          <Toggle
            checked={settings.use_llm_agents}
            onChange={async v => {
              setSettings({ ...settings, use_llm_agents: v })
              await updateAppSettings({ use_llm_agents: v })
            }}
          />
        </label>
      </section>

      {/* Pipeline diagram */}
      <section className="bg-slate-900/40 rounded-2xl p-4 border border-slate-800/50">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Pipeline</p>
        <div className="space-y-2">
          {[
            { tier: 'Tier 1 — Bias', agents: ['htf_bias', 'session_phase'] },
            { tier: 'Tier 2 — Trigger', agents: ['ltf_technical', 'liquidity_smc', 'order_flow'] },
            { tier: 'Tier 3 — Risk', agents: ['news_proximity', 'volatility'] },
            { tier: 'Tier 4 — Meta', agents: ['devils_advocate'] },
            { tier: 'Final', agents: ['synthesizer'] },
          ].map(t => (
            <div key={t.tier} className="flex items-center gap-2 text-[10px]">
              <span className="text-slate-500 w-20 shrink-0 font-mono">{t.tier}</span>
              <div className="flex flex-wrap gap-1">
                {t.agents.map(a => {
                  const c = configs.get(a)
                  return (
                    <span
                      key={a}
                      className={`px-1.5 py-0.5 rounded font-mono ${
                        c?.enabled
                          ? 'bg-sky-900/50 text-sky-300 border border-sky-700/40'
                          : 'bg-slate-800 text-slate-600 line-through'
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
      </section>

      {/* Per-agent cards */}
      <section className="space-y-3">
        <p className="text-xs font-bold text-slate-300 uppercase tracking-wider">Konfigurasi per Agent</p>
        {AGENT_NAMES.map(name => (
          <AgentCard
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
      </section>
    </main>
  )
}

function AgentCard({
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
  const effectiveModel = config.llm_model ?? globalModel

  useEffect(() => {
    if (!expanded || !usePerAgent) return
    const k = providers.get(effectiveProvider)
    setModelLoading(true)
    fetchModelsForProvider(effectiveProvider, k?.api_key ?? undefined, k?.base_url ?? undefined)
      .then(setModels)
      .catch(() => setModels([]))
      .finally(() => setModelLoading(false))
  }, [expanded, effectiveProvider, usePerAgent, providers])

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-2xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/80 transition-colors"
      >
        <div className={`w-2 h-2 rounded-full ${config.enabled ? 'bg-emerald-500' : 'bg-slate-600'}`} />
        <div className="flex-1 min-w-0 text-left">
          <p className="text-sm font-semibold text-slate-100">{AGENT_LABELS[name]}</p>
          <p className="text-[10px] text-slate-500 truncate">{AGENT_DESCRIPTIONS[name]}</p>
        </div>
        {usePerAgent && config.llm_model && (
          <span className="text-[9px] text-sky-400 font-mono">{config.llm_model.slice(0, 18)}…</span>
        )}
        <ChevronDown size={16} className={`text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-slate-700/40">
          {/* Enable toggle */}
          <label className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-300">Aktif</span>
            <Toggle checked={config.enabled} onChange={v => onUpdate({ enabled: v })} />
          </label>

          {/* Per-agent LLM (only if usePerAgent) */}
          {usePerAgent && (
            <>
              <div>
                <label className="text-[11px] text-slate-400 font-semibold mb-1 block">Provider</label>
                <select
                  value={config.llm_provider ?? ''}
                  onChange={e => onUpdate({ llm_provider: e.target.value || null })}
                  className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-sky-500"
                >
                  <option value="">(default: {PROVIDER_LABELS[globalProvider]})</option>
                  {PROVIDER_LIST.map(p => (
                    <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[11px] text-slate-400 font-semibold mb-1 flex items-center justify-between">
                  Model
                  {modelLoading && <Loader2 size={10} className="animate-spin" />}
                </label>
                <select
                  value={config.llm_model ?? ''}
                  onChange={e => onUpdate({ llm_model: e.target.value || null })}
                  className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
                >
                  <option value="">(default: {globalModel})</option>
                  {models.filter(m => m.free).slice(0, 50).map(m => (
                    <option key={m.id} value={m.id}>{m.id}{m.free ? ' · free' : ''}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {/* Temperature & weight */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 font-semibold mb-1 block">
                Temperature: <span className="text-slate-200">{config.temperature.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={config.temperature}
                onChange={e => onUpdate({ temperature: Number(e.target.value) })}
                className="w-full accent-sky-500"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 font-semibold mb-1 block">
                Weight: <span className="text-slate-200">{config.weight.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min={0}
                max={3}
                step={0.1}
                value={config.weight}
                onChange={e => onUpdate({ weight: Number(e.target.value) })}
                className="w-full accent-sky-500"
              />
            </div>
          </div>

          {/* Max tokens */}
          <div>
            <label className="text-[11px] text-slate-400 font-semibold mb-1 block">
              Max tokens: <span className="text-slate-200">{config.max_tokens}</span>
            </label>
            <input
              type="range"
              min={100}
              max={2000}
              step={50}
              value={config.max_tokens}
              onChange={e => onUpdate({ max_tokens: Number(e.target.value) })}
              className="w-full accent-sky-500"
            />
          </div>

          {/* Timeframes */}
          <div>
            <label className="text-[11px] text-slate-400 font-semibold mb-1 block">Timeframes aktif</label>
            <div className="flex gap-2">
              {TIMEFRAME_OPTIONS.map(t => {
                const selected = config.timeframes.includes(t)
                return (
                  <button
                    key={t}
                    onClick={() => onUpdate({
                      timeframes: selected
                        ? config.timeframes.filter(x => x !== t)
                        : [...config.timeframes, t],
                    })}
                    className={`flex-1 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                      selected
                        ? 'bg-sky-700/60 text-sky-100 border border-sky-600'
                        : 'bg-slate-900/40 text-slate-500 border border-slate-700'
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
            <summary className="text-slate-400 cursor-pointer hover:text-slate-200">Custom prompt (advanced)</summary>
            <textarea
              value={config.custom_prompt ?? ''}
              onChange={e => onUpdate({ custom_prompt: e.target.value || null })}
              placeholder="(default system prompt)"
              rows={4}
              className="mt-2 w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
            />
          </details>
        </div>
      )}
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`w-10 h-6 rounded-full transition-colors relative shrink-0 ${
        checked ? 'bg-emerald-600' : 'bg-slate-600'
      }`}
    >
      <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
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
