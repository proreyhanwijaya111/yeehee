'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  ArrowLeft, Cpu, Brain, Server, Send, Sliders, ChevronRight, Bell, Briefcase,
} from 'lucide-react'
import {
  getAppSettings,
  getDaemonHeartbeat,
  getProviderKeys,
  getAgentConfigs,
  isDaemonOnline,
  PROVIDER_LABELS,
  type AppSettings,
  type DaemonHeartbeat,
  type ProviderKey,
  type AgentConfig,
} from '@/lib/settings'

export default function SettingsHubPage() {
  const [settings,  setSettings]  = useState<AppSettings | null>(null)
  const [heartbeat, setHeartbeat] = useState<DaemonHeartbeat | null>(null)
  const [providers, setProviders] = useState<ProviderKey[]>([])
  const [agents,    setAgents]    = useState<AgentConfig[]>([])
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    Promise.all([
      getAppSettings(),
      getDaemonHeartbeat(),
      getProviderKeys(),
      getAgentConfigs(),
    ]).then(([s, hb, p, a]) => {
      setSettings(s); setHeartbeat(hb); setProviders(p); setAgents(a); setLoading(false)
    })
  }, [])

  const online            = isDaemonOnline(heartbeat)
  const enabledProviders  = providers.filter(p => p.enabled && p.api_key).length
  const enabledAgents     = agents.filter(a => a.enabled).length || 9

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div>
          <h1 className="text-lg font-black text-slate-100">Pengaturan</h1>
          <p className="text-[11px] text-slate-500">Semua konfigurasi sistem.</p>
        </div>
      </header>

      {/* Daemon status — compact, single line */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl px-3.5 py-3 mb-5 flex items-center gap-3">
        <span className={`w-2 h-2 rounded-full shrink-0 ${
          online ? 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]' : 'bg-slate-500'
        }`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-slate-200">
            Daemon {online ? 'online' : 'offline'}
          </p>
          <p className="text-[10px] text-slate-500 truncate">
            {heartbeat?.hostname && <>{heartbeat.hostname} · </>}
            {heartbeat?.last_signal_at
              ? `signal ${timeAgo(heartbeat.last_signal_at)}`
              : 'belum ada signal'}
          </p>
        </div>
        <Link
          href="/more/settings/daemon"
          className="text-[10px] font-semibold text-sky-400 px-2 py-1 hover:bg-slate-800/60 rounded-md"
        >
          {online ? 'kelola' : 'setup'} →
        </Link>
      </div>

      {loading ? (
        <SkeletonGrid />
      ) : (
        <div className="space-y-5">
          {/* === Konfigurasi inti === */}
          <Group title="Konfigurasi inti">
            <Row
              href="/more/settings/llm"
              icon={<Brain size={16} />}
              label="LLM Provider"
              sub={
                enabledProviders > 0
                  ? `${enabledProviders} aktif · default: ${PROVIDER_LABELS[settings?.default_llm_provider ?? '']}`
                  : 'Belum ada API key'
              }
              status={enabledProviders > 0 ? 'ok' : 'warn'}
              meta={settings?.default_llm_model}
            />
            <Row
              href="/more/settings/agents"
              icon={<Cpu size={16} />}
              label="9 AI Agent"
              sub={
                settings?.use_llm_agents
                  ? `${enabledAgents} aktif · ${settings?.use_per_agent_models ? 'per-agent LLM' : 'global LLM'}`
                  : 'LLM agents disabled — pakai rule engine'
              }
              status={settings?.use_llm_agents ? 'ok' : 'off'}
            />
            <Row
              href="/more/settings/daemon"
              icon={<Server size={16} />}
              label="Daemon worker"
              sub="Generate install script untuk PC rumah"
              status={online ? 'ok' : 'off'}
              meta={online ? 'online' : 'offline'}
            />
          </Group>

          {/* === Umum === */}
          <Group title="Umum">
            <Row
              href="/more/settings/general"
              icon={<Sliders size={16} />}
              label="Refresh & timeframe"
              sub={`${settings?.refresh_interval_minutes}min · ${settings?.timezone} · focus: ${settings?.timeframe_focus}`}
            />
            <Row
              href="/more/settings/portfolio"
              icon={<Briefcase size={16} />}
              label="Manajemen Portfolio"
              sub="Tutup semua OPEN trade · hapus history (clean slate)"
            />
          </Group>

          {/* === Notifikasi === */}
          <Group title="Notifikasi">
            <Row
              href="/more/settings/notifications"
              icon={<Bell size={16} />}
              label="Push notifikasi HP (NEW)"
              sub="Native browser push — STRONG signal langsung muncul di HP"
              status="ok"
            />
            <Row
              href="/more/settings/telegram"
              icon={<Send size={16} />}
              label="Telegram bot"
              sub="Push notifikasi sinyal + interactive command via Telegram"
            />
          </Group>
        </div>
      )}
    </main>
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

type Status = 'ok' | 'warn' | 'off' | undefined

function Row({
  href, icon, label, sub, status, meta,
}: {
  href: string
  icon: React.ReactNode
  label: string
  sub: string
  status?: Status
  meta?: string
}) {
  const dotColor =
    status === 'ok'   ? 'bg-emerald-500' :
    status === 'warn' ? 'bg-amber-500'   :
    status === 'off'  ? 'bg-slate-600'   : 'bg-slate-700'

  return (
    <Link
      href={href}
      className="flex items-center gap-3 px-3.5 py-3 hover:bg-slate-800/40 active:bg-slate-800/70 transition-colors touch-action"
    >
      <div className="w-8 h-8 rounded-lg bg-slate-800/80 border border-slate-700/50 flex items-center justify-center shrink-0 text-slate-300">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 leading-tight flex items-center gap-1.5">
          {label}
          {status && <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />}
        </p>
        <p className="text-[11px] text-slate-500 mt-0.5 truncate">{sub}</p>
      </div>
      {meta && (
        <span className="text-[10px] text-slate-500 font-mono shrink-0 max-w-[120px] truncate">
          {meta}
        </span>
      )}
      <ChevronRight size={16} className="text-slate-600 shrink-0" />
    </Link>
  )
}

function SkeletonGrid() {
  return (
    <div className="space-y-5">
      {[1,2,3].map(i => (
        <div key={i}>
          <div className="h-3 bg-slate-800/40 rounded w-24 mb-2 animate-pulse" />
          <div className="bg-slate-800/40 rounded-2xl divide-y divide-slate-800/80">
            {[1,2].map(j => <div key={j} className="h-14 animate-pulse" />)}
          </div>
        </div>
      ))}
    </div>
  )
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'baru saja'
  if (m < 60) return `${m}m lalu`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}j lalu`
  return `${Math.floor(h / 24)}h lalu`
}
