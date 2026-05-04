'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Sliders } from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  type AppSettings,
} from '@/lib/settings'

const TIMEZONES = [
  'Asia/Jakarta',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'America/New_York',
  'UTC',
]

const TIMEFRAME_FOCUS = [
  { id: 'all',       label: 'Semua',     sub: 'Scalping + Intraday + Swing' },
  { id: 'scalping',  label: 'Scalping',  sub: '5m – 60m timeframe' },
  { id: 'intraday',  label: 'Intraday',  sub: '1h – 4h timeframe' },
  { id: 'swing',     label: 'Swing',     sub: '4h – 1w timeframe' },
] as const

export default function GeneralSettingsPage() {
  const [s, setS] = useState<AppSettings | null>(null)

  useEffect(() => { getAppSettings().then(setS) }, [])

  if (!s) return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )

  const update = async (patch: Partial<AppSettings>) => {
    setS({ ...s, ...patch })
    await updateAppSettings(patch)
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-slate-700/60 border border-slate-600/40 flex items-center justify-center">
          <Sliders size={16} className="text-slate-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Pengaturan umum</h1>
          <p className="text-[11px] text-slate-500">Refresh interval, timezone, timeframe focus.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Refresh */}
        <Group title="Refresh">
          <div className="px-3.5 py-3">
            <label className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold flex items-center justify-between">
              <span>Interval</span>
              <span className="text-slate-200 font-mono">{s.refresh_interval_minutes} menit</span>
            </label>
            <input
              type="range"
              min={1}
              max={60}
              value={s.refresh_interval_minutes}
              onChange={e => update({ refresh_interval_minutes: Number(e.target.value) })}
              className="w-full mt-1.5 accent-sky-500"
            />
            <div className="flex justify-between text-[9px] text-slate-500 mt-1 font-mono">
              <span>1m</span><span>15m</span><span>30m</span><span>60m</span>
            </div>
            <p className="text-[10px] text-slate-500 mt-2 leading-relaxed">
              Tiap refresh = 9× LLM call. Pertimbangkan quota provider lo. Free tier 50 req/hari = 5 refresh.
            </p>
          </div>
        </Group>

        {/* Timezone */}
        <Group title="Timezone">
          <div className="px-3.5 py-3">
            <select
              value={s.timezone}
              onChange={e => update({ timezone: e.target.value })}
              className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
            >
              {TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </div>
        </Group>

        {/* Timeframe focus */}
        <Group title="Fokus timeframe">
          <div className="px-3.5 py-3 grid grid-cols-2 gap-2">
            {TIMEFRAME_FOCUS.map(t => {
              const active = s.timeframe_focus === t.id
              return (
                <button
                  key={t.id}
                  onClick={() => update({ timeframe_focus: t.id as AppSettings['timeframe_focus'] })}
                  className={`text-left px-3 py-2.5 rounded-lg border transition-colors ${
                    active
                      ? 'bg-sky-700/30 border-sky-600 text-sky-100'
                      : 'bg-slate-900/40 border-slate-700/60 text-slate-400 hover:bg-slate-800/60'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold">{t.label}</p>
                    {active && <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />}
                  </div>
                  <p className="text-[10px] mt-0.5 opacity-80">{t.sub}</p>
                </button>
              )
            })}
          </div>
        </Group>

        {/* Switches */}
        <Group title="Switches">
          <ToggleRow
            label="News blackout"
            sub="Block semua signal 15 menit sebelum/sesudah berita high-impact (NFP, CPI, FOMC)."
            checked={s.enable_news_blackout}
            onChange={v => update({ enable_news_blackout: v })}
          />
          <ToggleRow
            label="Daemon aktif"
            sub="Daemon di PC rumah jalan otomatis sesuai interval. Matikan untuk maintenance."
            checked={s.daemon_active}
            onChange={v => update({ daemon_active: v })}
          />
          <ToggleRow
            label="Mira worker"
            sub="Daemon juga proses queue Mira chatbot. Matikan kalau ingin daemon fokus signal saja."
            checked={s.enable_mira_worker}
            onChange={v => update({ enable_mira_worker: v })}
          />
        </Group>
      </div>
    </main>
  )
}

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
