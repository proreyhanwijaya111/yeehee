'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Eye, EyeOff, Check, X, RefreshCw, Trash2, ChevronDown, Loader2,
  Search, Brain,
} from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  getProviderKeys, upsertProviderKey, setProviderEnabled, deleteProviderKey, recordProviderValidation,
  PROVIDER_LIST, PROVIDER_LABELS,
  type AppSettings, type ProviderKey,
} from '@/lib/settings'
import { fetchModelsForProvider, testProviderKey, type LLMModel } from '@/lib/llm-models'

const PROVIDER_HINT: Record<string, string> = {
  openrouter: 'Daftar gratis di openrouter.ai/keys (mulai sk-or-v1-...). Akses 100+ model termasuk free tier.',
  anthropic:  'console.anthropic.com (mulai sk-ant-...).',
  openai:     'platform.openai.com/api-keys (mulai sk-...).',
  groq:       'console.groq.com/keys — free tier super cepat (LPU).',
  gemini:     'aistudio.google.com/app/apikey — free tier 15 req/min.',
  ollama:     'Run "ollama serve" di local. Default base URL: http://localhost:11434',
  lmstudio:   'Run LM Studio server. Default base URL: http://localhost:1234',
}

export default function LLMSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [keys,     setKeys]     = useState<Map<string, ProviderKey>>(new Map())
  const [loading,  setLoading]  = useState(true)
  const [models,   setModels]   = useState<LLMModel[]>([])
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
      .then(setModels).catch(() => setModels([]))
      .finally(() => setModelLoading(false))
  }, [settings, keys])

  if (loading || !settings) return <FullPageLoader />

  const filteredModels = models.filter(m => {
    if (showOnlyFree && !m.free) return false
    if (search && !m.id.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-violet-700/30 border border-violet-600/30 flex items-center justify-center">
          <Brain size={16} className="text-violet-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">LLM Provider</h1>
          <p className="text-[11px] text-slate-500">API key & default model untuk AI agent.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Tutorial intro */}
        <div className="bg-violet-950/30 border border-violet-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
          <p className="text-violet-100 font-semibold mb-1.5">Apa ini buat?</p>
          <p className="text-violet-200/80 mb-2">
            Sistem yeehee pakai AI (LLM) sebagai 12 expert agent yang debate sebelum kasih signal. Lo perlu kasih akses ke salah satu provider LLM (gratis tier 200 req/hari cukup).
          </p>
          <details className="mt-2">
            <summary className="cursor-pointer text-violet-200 font-semibold text-[11px]">📖 Cara setup OpenRouter (recommended, gratis)</summary>
            <ol className="mt-2 list-decimal pl-4 text-[10px] text-violet-200/70 space-y-1 leading-relaxed">
              <li>Buka <a href="https://openrouter.ai/keys" target="_blank" rel="noopener" className="text-sky-300 underline">openrouter.ai/keys</a> → login pake Google</li>
              <li>Klik <span className="font-bold">Create Key</span> → kasih nama bebas (e.g. yeehee)</li>
              <li>Copy key yang muncul (format <span className="font-mono">sk-or-v1-...</span>)</li>
              <li>Balik ke halaman ini → pilih <span className="font-bold">OpenRouter</span> di Default Provider di bawah</li>
              <li>Scroll ke section <span className="font-bold">Provider keys</span> → expand <span className="font-bold">OpenRouter</span> → paste key → klik Save</li>
              <li>Klik <span className="font-bold">Test connection</span> — harus muncul ✓ tanda key valid</li>
              <li>Pilih model di dropdown Model di atas (filter "free" untuk gratis tier)</li>
            </ol>
          </details>
          <details className="mt-1">
            <summary className="cursor-pointer text-violet-200 font-semibold text-[11px]">📖 Provider lain (Anthropic / OpenAI / Groq / Gemini / Ollama / LM Studio)</summary>
            <p className="mt-2 text-[10px] text-violet-200/70 leading-relaxed">
              Pilih provider di dropdown di bawah → liat hint untuk URL daftar. Anthropic & OpenAI berbayar, Groq & Gemini punya free tier kuat. Ollama & LM Studio buat run model lokal di PC lo (no API key needed).
            </p>
          </details>
        </div>

        {/* Default LLM */}
        <Group title="Default LLM">
          <div className="px-3.5 py-3 space-y-3">
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Provider</label>
              <select
                value={settings.default_llm_provider}
                onChange={async e => {
                  const v = e.target.value
                  setSettings({ ...settings, default_llm_provider: v })
                  await updateAppSettings({ default_llm_provider: v })
                }}
                className="mt-1 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
              >
                {PROVIDER_LIST.map(p => (
                  <option key={p} value={p}>
                    {PROVIDER_LABELS[p]}{keys.get(p)?.api_key ? '  ●' : ''}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Model</label>
                <div className="flex items-center gap-2 text-[10px]">
                  <button
                    onClick={() => setShowOnlyFree(!showOnlyFree)}
                    className={`px-2 py-0.5 rounded font-semibold transition-colors ${
                      showOnlyFree ? 'bg-emerald-700/40 text-emerald-300' : 'bg-slate-700/40 text-slate-500'
                    }`}
                  >
                    free only
                  </button>
                  {modelLoading && <Loader2 size={11} className="animate-spin text-slate-500" />}
                  <span className="text-slate-500 tabular-nums">{filteredModels.length}</span>
                </div>
              </div>
              <div className="relative">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="filter... contoh: llama, gemma, gpt-oss"
                  className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg pl-7 pr-3 py-1.5 text-xs text-slate-100 mb-1.5 focus:outline-none focus:border-sky-500"
                />
              </div>
              <select
                value={settings.default_llm_model}
                onChange={async e => {
                  const v = e.target.value
                  setSettings({ ...settings, default_llm_model: v })
                  await updateAppSettings({ default_llm_model: v })
                }}
                size={Math.min(7, Math.max(3, filteredModels.length))}
                className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-1.5 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
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
              <p className="text-[10px] text-slate-500 mt-1.5 truncate">
                Selected: <span className="font-mono text-slate-300">{settings.default_llm_model}</span>
              </p>
            </div>
          </div>

          <ToggleRow
            label="Per-agent LLM (advanced)"
            sub="Tiap agent bisa pakai model berbeda. Atur di halaman Agent."
            checked={settings.use_per_agent_models}
            onChange={async v => {
              setSettings({ ...settings, use_per_agent_models: v })
              await updateAppSettings({ use_per_agent_models: v })
            }}
          />
        </Group>

        {/* Providers */}
        <Group title="Provider API keys">
          {PROVIDER_LIST.map(p => (
            <ProviderRow
              key={p}
              provider={p}
              entry={keys.get(p)}
              onUpsert={async (apiKey, baseUrl) => {
                await upsertProviderKey(p, apiKey, baseUrl)
                refreshKeys()
              }}
              onToggleEnabled={async enabled => {
                await setProviderEnabled(p, enabled)
                refreshKeys()
              }}
              onDelete={async () => {
                if (!confirm(`Hapus API key untuk ${PROVIDER_LABELS[p]}?`)) return
                await deleteProviderKey(p)
                refreshKeys()
              }}
              onValidated={async (ok, msg) => {
                await recordProviderValidation(p, ok, msg)
              }}
            />
          ))}
        </Group>
      </div>
    </main>
  )

  async function refreshKeys() {
    const fresh = await getProviderKeys()
    const m = new Map<string, ProviderKey>()
    fresh.forEach(k => m.set(k.provider, k))
    setKeys(m)
  }
}

// ─── ProviderRow ──────────────────────────────────────────────────────────────

function ProviderRow({
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
  const [baseUrl, setBaseUrl] = useState(
    entry?.base_url ?? (provider === 'ollama' ? 'http://localhost:11434/v1' : provider === 'lmstudio' ? 'http://localhost:1234/v1' : ''),
  )
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    setApiKey(entry?.api_key ?? '')
    if (entry?.base_url) setBaseUrl(entry.base_url)
  }, [entry])

  const hasKey = !!entry?.api_key
  const enabled = entry?.enabled ?? true

  const status: 'ok' | 'warn' | 'off' | 'local' =
    isLocal ? 'local' :
    hasKey && enabled ? 'ok' :
    hasKey ? 'warn' : 'off'

  const dotColor =
    status === 'ok'    ? 'bg-emerald-500' :
    status === 'warn'  ? 'bg-amber-500'   :
    status === 'local' ? 'bg-sky-500'     : 'bg-slate-600'

  return (
    <div className="overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3.5 py-3 hover:bg-slate-800/40 active:bg-slate-800/70 transition-colors"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
        <div className="flex-1 min-w-0 text-left">
          <p className="text-sm font-medium text-slate-100 leading-tight">{PROVIDER_LABELS[provider]}</p>
          <p className="text-[10px] text-slate-500 truncate">
            {hasKey ? `••••${entry.api_key?.slice(-4)}` : isLocal ? 'localhost' : 'belum di-set'}
          </p>
        </div>
        <ChevronDown size={14} className={`text-slate-500 transition-transform shrink-0 ${expanded ? 'rotate-180' : ''}`} />
      </button>

      {expanded && (
        <div className="px-3.5 pb-3.5 pt-1 space-y-3 border-t border-slate-800/80">
          <p className="text-[10px] text-slate-500 leading-relaxed">{PROVIDER_HINT[provider]}</p>

          {!isLocal && (
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">API Key</label>
              <div className="flex gap-1.5 mt-1">
                <input
                  type={show ? 'text' : 'password'}
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  placeholder={provider === 'openrouter' ? 'sk-or-v1-...' : provider === 'anthropic' ? 'sk-ant-...' : 'sk-...'}
                  className="flex-1 bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
                />
                <button
                  onClick={() => setShow(!show)}
                  className="p-2 bg-slate-800/60 border border-slate-700/60 rounded-lg hover:bg-slate-800 text-slate-400"
                  type="button"
                  aria-label="Show/hide"
                >
                  {show ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
              </div>
            </div>
          )}

          {isLocal && (
            <div>
              <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">Base URL</label>
              <input
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                placeholder="http://localhost:11434/v1"
                className="mt-1 w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
              />
            </div>
          )}

          <div className="flex gap-1.5 flex-wrap">
            <button
              onClick={async () => { setSaving(true); await onUpsert(apiKey, baseUrl); setSaving(false) }}
              disabled={saving || (!isLocal && !apiKey)}
              className="flex-1 py-1.5 bg-sky-600/80 hover:bg-sky-500 disabled:opacity-40 text-white text-xs font-semibold rounded-lg transition-colors"
            >
              {saving ? '…' : 'Simpan'}
            </button>
            <button
              onClick={async () => {
                setTesting(true); setTestResult(null)
                const r = await testProviderKey(provider, apiKey, baseUrl)
                setTestResult({ ok: r.ok, msg: r.message })
                await onValidated(r.ok, r.message)
                setTesting(false)
              }}
              disabled={testing || (!isLocal && !apiKey)}
              className="flex-1 py-1.5 bg-slate-800/80 hover:bg-slate-700 disabled:opacity-40 text-slate-200 text-xs font-semibold rounded-lg transition-colors flex items-center justify-center gap-1"
            >
              {testing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              Test
            </button>
            {hasKey && (
              <>
                <button
                  onClick={() => onToggleEnabled(!enabled)}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                    enabled ? 'bg-emerald-800/40 text-emerald-300' : 'bg-slate-800/60 text-slate-500'
                  }`}
                >
                  {enabled ? 'on' : 'off'}
                </button>
                <button
                  onClick={onDelete}
                  className="p-1.5 bg-rose-900/30 hover:bg-rose-900/50 text-rose-300 rounded-lg"
                  aria-label="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </>
            )}
          </div>

          {testResult && (
            <div className={`flex items-start gap-2 px-2.5 py-2 rounded-lg text-[11px] ${
              testResult.ok ? 'bg-emerald-950/30 text-emerald-300' : 'bg-rose-950/30 text-rose-300'
            }`}>
              {testResult.ok ? <Check size={13} className="shrink-0 mt-0.5" /> : <X size={13} className="shrink-0 mt-0.5" />}
              <span>{testResult.msg}</span>
            </div>
          )}
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

function ToggleRow({ label, sub, checked, onChange }: {
  label: string; sub: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 px-3.5 py-3 cursor-pointer hover:bg-slate-800/40">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 leading-tight">{label}</p>
        <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">{sub}</p>
      </div>
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
    </label>
  )
}

function FullPageLoader() {
  return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )
}
