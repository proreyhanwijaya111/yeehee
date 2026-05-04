'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2 } from 'lucide-react'
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
  { id: 'all',       label: 'Semua', sub: 'Scalping + Intraday + Swing' },
  { id: 'scalping',  label: 'Scalping', sub: '5m – 60m timeframe' },
  { id: 'intraday',  label: 'Intraday', sub: '1h – 4h timeframe' },
  { id: 'swing',     label: 'Swing',    sub: '4h – 1w timeframe' },
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
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <header className="flex items-center gap-2">
        <Link href="/more/settings" className="p-1.5 hover:bg-slate-800 rounded-lg">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div>
          <h1 className="text-lg font-black text-slate-100">Pengaturan Umum</h1>
          <p className="text-[11px] text-slate-400">Refresh interval, timezone, fokus timeframe.</p>
        </div>
      </header>

      <section className="bg-slate-800/60 border border-slate-700/50 rounded-2xl p-4 space-y-4">
        <div>
          <label className="text-[11px] text-slate-400 font-semibold mb-1 block">
            Refresh signal: <span className="text-slate-200">{s.refresh_interval_minutes} menit</span>
          </label>
          <input
            type="range"
            min={1}
            max={60}
            value={s.refresh_interval_minutes}
            onChange={e => update({ refresh_interval_minutes: Number(e.target.value) })}
            className="w-full accent-sky-500"
          />
          <div className="flex justify-between text-[10px] text-slate-500 mt-1">
            <span>1m (intensif)</span><span>15m (normal)</span><span>60m (hemat API)</span>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">
            Tiap refresh = 9× LLM call. Hitung quota provider lo.
          </p>
        </div>

        <div>
          <label className="text-[11px] text-slate-400 font-semibold mb-1 block">Timezone</label>
          <select
            value={s.timezone}
            onChange={e => update({ timezone: e.target.value })}
            className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
          >
            {TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
          </select>
        </div>

        <div>
          <label className="text-[11px] text-slate-400 font-semibold mb-2 block">Fokus Timeframe</label>
          <div className="grid grid-cols-2 gap-2">
            {TIMEFRAME_FOCUS.map(t => (
              <button
                key={t.id}
                onClick={() => update({ timeframe_focus: t.id as AppSettings['timeframe_focus'] })}
                className={`text-left px-3 py-2.5 rounded-xl border transition-all ${
                  s.timeframe_focus === t.id
                    ? 'bg-sky-700/40 border-sky-600 text-sky-100'
                    : 'bg-slate-900/40 border-slate-700 text-slate-400'
                }`}
              >
                <p className="text-xs font-bold">{t.label}</p>
                <p className="text-[10px] mt-0.5 opacity-80">{t.sub}</p>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-slate-800/60 border border-slate-700/50 rounded-2xl p-4 space-y-3">
        <p className="text-xs font-bold text-slate-300 uppercase tracking-wider">Switches</p>
        <ToggleRow
          label="News Blackout aktif"
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
          label="Mira worker pada daemon"
          sub="Daemon juga proses queue Mira chatbot. Matikan kalau ingin daemon fokus signal saja."
          checked={s.enable_mira_worker}
          onChange={v => update({ enable_mira_worker: v })}
        />
      </section>
    </main>
  )
}

function ToggleRow({ label, sub, checked, onChange }: {
  label: string; sub: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-100">{label}</p>
        <p className="text-[11px] text-slate-500 leading-relaxed">{sub}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        type="button"
        className={`w-10 h-6 rounded-full transition-colors relative shrink-0 ${
          checked ? 'bg-emerald-600' : 'bg-slate-600'
        }`}
      >
        <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0.5'
        }`} />
      </button>
    </label>
  )
}
