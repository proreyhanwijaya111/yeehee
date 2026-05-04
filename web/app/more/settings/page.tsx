'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Cpu, Brain, Server, Send, Sliders, ChevronRight, Activity, AlertCircle } from 'lucide-react'
import {
  getAppSettings,
  getDaemonHeartbeat,
  getProviderKeys,
  getAgentConfigs,
  isDaemonOnline,
  PROVIDER_LABELS,
  AGENT_LABELS,
  type AppSettings,
  type DaemonHeartbeat,
  type ProviderKey,
  type AgentConfig,
  type AgentName,
} from '@/lib/settings'

export default function SettingsHubPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [heartbeat, setHeartbeat] = useState<DaemonHeartbeat | null>(null)
  const [providers, setProviders] = useState<ProviderKey[]>([])
  const [agents, setAgents] = useState<AgentConfig[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getAppSettings(),
      getDaemonHeartbeat(),
      getProviderKeys(),
      getAgentConfigs(),
    ]).then(([s, hb, p, a]) => {
      setSettings(s)
      setHeartbeat(hb)
      setProviders(p)
      setAgents(a)
      setLoading(false)
    })
  }, [])

  const online = isDaemonOnline(heartbeat)
  const enabledProviders = providers.filter(p => p.enabled && p.api_key).length
  const enabledAgents = agents.filter(a => a.enabled).length || 9

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <header>
        <h1 className="text-lg font-black text-slate-100">⚙️ Pengaturan</h1>
        <p className="text-xs text-slate-400 mt-0.5">Konfigurasi end-to-end sistem yeehee.</p>
      </header>

      {/* Daemon status */}
      <div className={`rounded-2xl border p-4 ${
        online
          ? 'bg-emerald-950/40 border-emerald-700/40'
          : 'bg-amber-950/40 border-amber-700/40'
      }`}>
        <div className="flex items-start gap-3">
          <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${
            online ? 'bg-emerald-600/30' : 'bg-amber-600/30'
          }`}>
            {online ? <Activity size={18} className="text-emerald-300" /> : <AlertCircle size={18} className="text-amber-300" />}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-slate-100">
              Daemon {online ? 'ONLINE' : 'OFFLINE'}
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">
              {heartbeat?.hostname && <>Host: <span className="font-mono">{heartbeat.hostname}</span>{' · '}</>}
              {heartbeat?.last_signal_at
                ? `Signal terakhir: ${new Date(heartbeat.last_signal_at).toLocaleTimeString('id-ID')}`
                : 'Belum ada signal'}
            </p>
            {!online && (
              <Link
                href="/more/settings/daemon"
                className="inline-block mt-2 text-[11px] font-semibold text-sky-400 underline"
              >
                → Setup daemon di PC rumah
              </Link>
            )}
          </div>
        </div>
      </div>

      {loading ? (
        <SkeletonGrid />
      ) : (
        <>
          {/* Settings cards */}
          <div className="grid grid-cols-1 gap-3">
            <SettingCard
              href="/more/settings/llm"
              icon={<Brain size={18} />}
              title="LLM Provider"
              subtitle={
                enabledProviders > 0
                  ? `${enabledProviders} provider aktif · default: ${PROVIDER_LABELS[settings?.default_llm_provider ?? '']} · ${settings?.default_llm_model}`
                  : '⚠️ Belum ada API key di-set'
              }
              warning={enabledProviders === 0}
            />
            <SettingCard
              href="/more/settings/agents"
              icon={<Cpu size={18} />}
              title="9 AI Agent"
              subtitle={
                settings?.use_llm_agents
                  ? `${enabledAgents} agent aktif · ${settings?.use_per_agent_models ? 'per-agent LLM' : 'global LLM'}`
                  : 'LLM agents disabled — pakai rule engine saja'
              }
            />
            <SettingCard
              href="/more/settings/daemon"
              icon={<Server size={18} />}
              title="Daemon Generator"
              subtitle="Generate script Python untuk PC rumah lo (signal worker)"
            />
            <SettingCard
              href="/more/settings/general"
              icon={<Sliders size={18} />}
              title="Umum"
              subtitle={`Refresh ${settings?.refresh_interval_minutes}min · ${settings?.timezone} · focus: ${settings?.timeframe_focus}`}
            />
            <SettingCard
              href="/more/settings/telegram"
              icon={<Send size={18} />}
              title="Telegram Bot"
              subtitle="Setup notifikasi push ke HP"
            />
          </div>
        </>
      )}
    </main>
  )
}

function SettingCard({
  href, icon, title, subtitle, warning,
}: {
  href: string
  icon: React.ReactNode
  title: string
  subtitle: string
  warning?: boolean
}) {
  return (
    <Link
      href={href}
      className="bg-slate-800/60 hover:bg-slate-800 border border-slate-700/50 rounded-2xl p-4 flex items-center gap-3 transition-all touch-action active:scale-[0.98]"
    >
      <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${
        warning ? 'bg-amber-600/30 text-amber-300' : 'bg-sky-600/30 text-sky-300'
      }`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-100">{title}</p>
        <p className="text-[11px] text-slate-400 mt-0.5 truncate">{subtitle}</p>
      </div>
      <ChevronRight size={16} className="text-slate-500 shrink-0" />
    </Link>
  )
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 gap-3">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="bg-slate-800/40 rounded-2xl h-16 animate-pulse" />
      ))}
    </div>
  )
}
