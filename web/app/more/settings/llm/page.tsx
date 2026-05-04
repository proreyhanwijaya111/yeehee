'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Eye, EyeOff, Check, X, RefreshCw, Trash2, ChevronDown, Loader2 } from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  getProviderKeys, upsertProviderKey, setProviderEnabled, deleteProviderKey, recordProviderValidation,
  PROVIDER_LIST, PROVIDER_LABELS,
  type AppSettings, type ProviderKey,
} from '@/lib/settings'
import { fetchModelsForProvider, testProviderKey, type LLMModel } from '@/lib/llm-models'

const PROVIDER_HINTS: Record<string, string> = {
  openrouter: 'Daftar gratis: openrouter.ai/keys (mulai sk-or-v1-...). Akses 100+ model.',
  anthropic:  'console.anthropic.com (mulai sk-ant-...).',
  openai:     'platform.openai.com/api-keys (mulai sk-...).',
  groq:       'console.groq.com/keys — free tier, super cepat (LPU).',
  gemini:     'aistudio.google.com/app/apikey — free tier 15 req/min.',
  ollama:     'Run `ollama serve` di local. Default base URL: http://localhost:11434',
  lmstudio:   'Run LM Studio server. Default base URL: http://localhost:1234',
}

export default function LLMSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [keys, setKeys] = useState<Map<string, ProviderKey>>(new Map())
  const [loading, setLoading] = useState(true)
  const [models, setModels] = useState<LLMModel[]>([])
  const [modelLoading, setModelLoading] = useState(false)
  const [showOnlyFree, setShowOnlyFree] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    Promise.all([getAppSettings(), getProviderKeys()]).then(([s, p]) => {
      setSettings(s)
      const m = new Map<string, ProviderKey>()
      p.forEach(k => m.set(k.provider, k))
      setKeys(m)
      setLoading(false)
    })
  }, [])

  // Load models for default provider when key available
  useEffect(() => {
    if (!settings) return
    const k = keys.get(settings.default_llm_provider)
    const apiKey = k?.api_key
    const baseUrl = k?.base_url ?? undefined
    if (!apiKey && !['ollama', 'lmstudio'].includes(settings.default_llm_provider)) {
      setModels([])
      return
    }
    setModelLoading(true)
    fetchModelsForProvider(settings.default_llm_provider, apiKey ?? undefined, baseUrl)
      .then(setModels)
      .catch(() => setModels([]))
      .finally(() => setModelLoading(false))
  }, [settings, keys])

  if (loading || !settings) return <FullPageLoader />

  const filteredModels = models.filter(m => {
    if (showOnlyFree && !m.free) return false
    if (search && !m.id.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <header className="flex items-center gap-2">
        <Link href="/more/settings" className="p-1.5 hover:bg-slate-800 rounded-lg">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div>
          <h1 className="text-lg font-black text-slate-100">LLM Provider</h1>
          <p className="text-[11px] text-slate-400">API key & model default untuk AI agent.</p>
        </div>
      </header>

      {/* Default provider + model picker */}
      <section className="bg-slate-800/60 border border-slate-700/50 rounded-2xl p-4 space-y-3">
        <p className="text-xs font-bold text-slate-300 uppercase tracking-wider">Default LLM</p>
        <div>
          <label className="text-[11px] text-slate-400 font-semibold mb-1 block">Provider</label>
          <select
            value={settings.default_llm_provider}
            onChange={async e => {
              const v = e.target.value
              setSettings({ ...settings, default_llm_provider: v })
              await updateAppSettings({ default_llm_provider: v })
            }}
            className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
          >
            {PROVIDER_LIST.map(p => (
              <option key={p} value={p}>
                {PROVIDER_LABELS[p]}{keys.get(p)?.api_key ? ' ✓' : ''}
              </option>
            ))}
          </select>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-[11px] text-slate-400 font-semibold">Model</label>
            <div className="flex items-center gap-2 text-[10px]">
              <button
                onClick={() => setShowOnlyFree(!showOnlyFree)}
                className={`px-2 py-0.5 rounded font-semibold ${
                  showOnlyFree ? 'bg-emerald-700/40 text-emerald-300' : 'bg-slate-700/40 text-slate-400'
                }`}
              >
                free only
              </button>
              {modelLoading && <Loader2 size={12} className="animate-spin text-slate-500" />}
              <span className="text-slate-500">{filteredModels.length} models</span>
            </div>
          </div>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="filter… contoh: llama, gemma, gpt-oss"
            className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-1.5 text-xs text-slate-100 mb-2 focus:outline-none focus:border-sky-500"
          />
          <select
            value={settings.default_llm_model}
            onChange={async e => {
              const v = e.target.value
              setSettings({ ...settings, default_llm_model: v })
              await updateAppSettings({ default_llm_model: v })
            }}
            size={Math.min(8, Math.max(3, filteredModels.length))}
            className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-sky-500"
          >
            {filteredModels.length === 0 && (
              <option value={settings.default_llm_model}>{settings.default_llm_model} (manual)</option>
            )}
            {filteredModels.slice(0, 200).map(m => (
              <option key={m.id} value={m.id}>
                {m.id}{m.free ? ' · free' : ''}{m.context_length ? ` · ${(m.context_length / 1000).toFixed(0)}k` : ''}
              </option>
            ))}
          </select>
          <p className="text-[10px] text-slate-500 mt-1">
            Selected: <span className="font-mono text-slate-300">{settings.default_llm_model}</span>
          </p>
        </div>

        <label className="flex items-start gap-2 cursor-pointer pt-2">
          <input
            type="checkbox"
            checked={settings.use_per_agent_models}
            onChange={async e => {
              const v = e.target.checked
              setSettings({ ...settings, use_per_agent_models: v })
              await updateAppSettings({ use_per_agent_models: v })
            }}
            className="mt-0.5 accent-sky-500"
          />
          <span className="text-xs">
            <span className="text-slate-200 font-semibold">Per-agent LLM (advanced)</span>
            <span className="text-slate-500 block">Tiap agent bisa pakai model berbeda. Atur di halaman Agent.</span>
          </span>
        </label>
      </section>

      {/* Provider list */}
      <section className="space-y-3">
        <p className="text-xs font-bold text-slate-300 uppercase tracking-wider">API Keys</p>
        {PROVIDER_LIST.map(p => (
          <ProviderCard
            key={p}
            provider={p}
            entry={keys.get(p)}
            onUpsert={async (apiKey, baseUrl) => {
              await upsertProviderKey(p, apiKey, baseUrl)
              const fresh = await getProviderKeys()
              const m = new Map<string, ProviderKey>()
              fresh.forEach(k => m.set(k.provider, k))
              setKeys(m)
            }}
            onToggleEnabled={async enabled => {
              await setProviderEnabled(p, enabled)
              const fresh = await getProviderKeys()
              const m = new Map<string, ProviderKey>()
              fresh.forEach(k => m.set(k.provider, k))
              setKeys(m)
            }}
            onDelete={async () => {
              if (!confirm(`Hapus API key untuk ${PROVIDER_LABELS[p]}?`)) return
              await deleteProviderKey(p)
              const fresh = await getProviderKeys()
              const m = new Map<string, ProviderKey>()
              fresh.forEach(k => m.set(k.provider, k))
              setKeys(m)
            }}
            onValidated={async (ok, msg) => {
              await recordProviderValidation(p, ok, msg)
            }}
          />
        ))}
      </section>
    </main>
  )
}

function ProviderCard({
  provider, entry, onUpsert, onToggleEnabled, onDelete, onValidated,
}: {
  provider: string
  entry: ProviderKey | undefined
  onUpsert: (apiKey: string, baseUrl?: string) => Promise<void>
  onToggleEnabled: (enabled: boolean) => Promise<void>
  onDelete: () => Promise<void>
  onValidated: (ok: boolean, msg?: string) => Promise<void>
}) {
  const isLocal = provider === 'ollama' || provider === 'lmstudio'
  const [expanded, setExpanded] = useState(false)
  const [show, setShow] = useState(false)
  const [apiKey, setApiKey] = useState(entry?.api_key ?? '')
  const [baseUrl, setBaseUrl] = useState(entry?.base_url ?? (provider === 'ollama' ? 'http://localhost:11434/v1' : provider === 'lmstudio' ? 'http://localhost:1234/v1' : ''))
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    setApiKey(entry?.api_key ?? '')
    if (entry?.base_url) setBaseUrl(entry.base_url)
  }, [entry])

  const hasKey = !!entry?.api_key
  const enabled = entry?.enabled ?? true

  const handleSave = async () => {
    setSaving(true)
    await onUpsert(apiKey, baseUrl)
    setSaving(false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    const result = await testProviderKey(provider, apiKey, baseUrl)
    setTestResult({ ok: result.ok, msg: result.message })
    await onValidated(result.ok, result.message)
    setTesting(false)
  }

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-2xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/80 transition-colors"
      >
        <div className={`w-2 h-2 rounded-full ${
          hasKey && enabled ? 'bg-emerald-500' : hasKey ? 'bg-amber-500' : isLocal ? 'bg-blue-500' : 'bg-slate-600'
        }`} />
        <div className="flex-1 min-w-0 text-left">
          <p className="text-sm font-semibold text-slate-100">{PROVIDER_LABELS[provider]}</p>
          <p className="text-[10px] text-slate-500 truncate">
            {hasKey ? `••••${entry.api_key?.slice(-4)}` : isLocal ? 'localhost' : 'no key'}
          </p>
        </div>
        <ChevronDown size={16} className={`text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-slate-700/40">
          <p className="text-[11px] text-slate-500 leading-relaxed">{PROVIDER_HINTS[provider]}</p>

          {!isLocal && (
            <div>
              <label className="text-[11px] text-slate-400 font-semibold mb-1 block">API Key</label>
              <div className="flex gap-2">
                <input
                  type={show ? 'text' : 'password'}
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  placeholder={`${provider === 'openrouter' ? 'sk-or-v1-...' : provider === 'anthropic' ? 'sk-ant-...' : 'sk-...'}`}
                  className="flex-1 bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
                />
                <button
                  onClick={() => setShow(!show)}
                  className="p-2 bg-slate-700/50 rounded-xl hover:bg-slate-700 text-slate-400"
                  type="button"
                >
                  {show ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>
          )}

          {isLocal && (
            <div>
              <label className="text-[11px] text-slate-400 font-semibold mb-1 block">Base URL</label>
              <input
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                placeholder="http://localhost:11434/v1"
                className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
              />
            </div>
          )}

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={handleSave}
              disabled={saving || (!isLocal && !apiKey)}
              className="flex-1 py-2 bg-emerald-700/80 hover:bg-emerald-600 disabled:opacity-40 text-white text-xs font-semibold rounded-xl transition-all"
            >
              {saving ? '...' : 'Simpan'}
            </button>
            <button
              onClick={handleTest}
              disabled={testing || (!isLocal && !apiKey)}
              className="flex-1 py-2 bg-sky-700/80 hover:bg-sky-600 disabled:opacity-40 text-white text-xs font-semibold rounded-xl transition-all flex items-center justify-center gap-1"
            >
              {testing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Test
            </button>
            {hasKey && (
              <>
                <button
                  onClick={() => onToggleEnabled(!enabled)}
                  className={`px-3 py-2 text-xs font-semibold rounded-xl transition-all ${
                    enabled ? 'bg-emerald-800/40 text-emerald-300' : 'bg-slate-700/40 text-slate-400'
                  }`}
                >
                  {enabled ? 'on' : 'off'}
                </button>
                <button
                  onClick={onDelete}
                  className="p-2 bg-red-900/40 hover:bg-red-900/60 text-red-300 rounded-xl"
                >
                  <Trash2 size={14} />
                </button>
              </>
            )}
          </div>

          {testResult && (
            <div className={`flex items-start gap-2 px-3 py-2 rounded-xl text-[11px] ${
              testResult.ok ? 'bg-emerald-950/50 text-emerald-300' : 'bg-red-950/50 text-red-300'
            }`}>
              {testResult.ok ? <Check size={14} className="shrink-0 mt-0.5" /> : <X size={14} className="shrink-0 mt-0.5" />}
              <span>{testResult.msg}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function FullPageLoader() {
  return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )
}
