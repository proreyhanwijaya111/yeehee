'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Zap, Shield, AlertTriangle, Loader2, Check, RotateCcw, Activity,
  TrendingUp, Lock, Move,
} from 'lucide-react'
import {
  getAppSettings, updateAppSettings,
  type AppSettings,
} from '@/lib/settings'

// Hard caps from migration 011 CHECK constraints (UI mirror — DB enforces too)
const HARD_CAPS = {
  max_trades_per_day: { min: 1,    max: 10  },
  risk_per_trade_pct: { min: 0.1,  max: 3.0 },
  daily_loss_pct:     { min: 1.0,  max: 10.0 },
  min_confidence_pct: { min: 50,   max: 95 },
  max_open_positions: { min: 1,    max: 5 },
  bep_trigger_pips:   { min: 10,   max: 500 },
  bep_lock_pips:      { min: 0,    max: 50 },
  trailing_trigger:   { min: 20,   max: 1000 },
  trailing_distance:  { min: 10,   max: 200 },
}

const DEFAULTS: Partial<AppSettings> = {
  ea_enable_execution:           false,
  ea_enable_paper:               true,
  ea_max_open_positions:         1,
  ea_max_trades_per_day:         5,
  ea_daily_loss_pct:             5.0,
  ea_min_confidence_pct:         65,
  ea_risk_per_trade_pct:         1.0,
  ea_enable_break_even:          true,
  ea_break_even_trigger_pips:    50,
  ea_break_even_lock_pips:       5,
  ea_enable_trailing:            true,
  ea_trailing_trigger_pips:      100,
  ea_trailing_distance_pips:     30,
}

export default function ExecutionSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [saving, setSaving]     = useState<string | null>(null)
  const [savedAt, setSavedAt]   = useState<string | null>(null)

  useEffect(() => { getAppSettings().then(setSettings).catch(() => {}) }, [])

  if (!settings) {
    return (
      <main className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="animate-spin text-slate-500" size={28} />
      </main>
    )
  }

  const update = async (patch: Partial<AppSettings>, label: string) => {
    setSaving(label)
    setSettings({ ...settings, ...patch })
    const ok = await updateAppSettings(patch)
    if (ok) {
      setSavedAt(label)
      setTimeout(() => setSavedAt(null), 1500)
    }
    setSaving(null)
  }

  const resetAll = async () => {
    if (!confirm('Reset semua execution config ke default? (paper mode, 1% risk, 5 trades/day)')) return
    await update(DEFAULTS, 'reset')
  }

  const liveMode = settings.ea_enable_execution && !settings.ea_enable_paper

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-amber-700/30 border border-amber-600/30 flex items-center justify-center">
          <Zap size={16} className="text-amber-300" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-black text-slate-100 leading-tight">Execution & EA</h1>
          <p className="text-[11px] text-slate-500">Auto-trade settings di MT5 via Expert Advisor.</p>
        </div>
        <button onClick={resetAll} className="p-1.5 text-slate-500 hover:text-slate-300" title="Reset ke default">
          <RotateCcw size={14} />
        </button>
      </header>

      <div className="space-y-5">
        {/* Tutorial intro */}
        <div className="bg-amber-950/30 border border-amber-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
          <p className="text-amber-100 font-semibold mb-1.5 flex items-center gap-1.5">
            <Shield size={13} /> Apa ini buat?
          </p>
          <p className="text-amber-200/80 mb-2">
            EA (Expert Advisor) di MT5 lo akan auto-execute trade waktu sistem detect signal high-conf yang lulus confluence filter. Halaman ini control semua aspek execution: max trades/hari, risk per trade, BEP, trailing stop.
          </p>
          <p className="text-amber-200/70">
            <span className="font-semibold">Settings auto-applied real-time</span> — EA polling /api/ea/config tiap 60 detik. Ga perlu restart EA setelah ubah.
          </p>
          <details className="mt-2">
            <summary className="cursor-pointer text-amber-200 font-semibold text-[11px]">📖 Cara setup MT5 EA pertama kali</summary>
            <ol className="mt-2 list-decimal pl-4 text-[10px] text-amber-200/70 space-y-1 leading-relaxed">
              <li>Install MetaTrader 5 desktop di PC rumah (download dari broker atau metatrader5.com)</li>
              <li>Login ke akun demo lo (broker username/password/server)</li>
              <li>Run FastAPI execution_api di PC rumah:
                <pre className="bg-slate-950 px-2 py-1 rounded mt-0.5 text-[9px]">{`cd ~\\yeehee-daemon
.\\.venv\\Scripts\\python.exe -m rcs.src.execution_api`}</pre>
              </li>
              <li>Whitelist URL di MT5: Tools → Options → Expert Advisors → Allow URL: <span className="font-mono">http://localhost:8001</span></li>
              <li>Buka file <span className="font-mono">~\yeehee-daemon\rcs\ea\DextradeEA.mq5</span> di MetaEditor (F4 di MT5)</li>
              <li>Tekan F7 untuk compile (cek "0 errors" di bottom)</li>
              <li>Drag <span className="font-bold">DextradeEA</span> dari Navigator ke chart XAUUSD</li>
              <li>EA akan auto-pickup config dari halaman ini setiap 60 detik</li>
              <li>Awalnya: <span className="font-bold">EnablePaperMode=true</span> (cuma log, no real orders)</li>
              <li>Setelah 1-2 minggu paper test → flip ke <span className="font-bold">EnableExecution=true, EnablePaperMode=false</span> di halaman ini</li>
            </ol>
          </details>
        </div>

        {/* Mode switch — most important */}
        <Section title="Mode Operasi" icon={<Activity size={13} />}>
          <Toggle
            label="Enable Execution (live trade)"
            sub="Off = EA cuma poll signals tapi ga execute. On = EA bisa execute order ke MT5. Default: OFF."
            checked={!!settings.ea_enable_execution}
            onChange={v => update({ ea_enable_execution: v }, 'enable_execution')}
            saving={saving === 'enable_execution'}
            saved={savedAt === 'enable_execution'}
            warning={liveMode}
          />
          <Toggle
            label="Paper Mode"
            sub="On = log saja, NO real orders. Off = real orders. Default: ON. (Saat live trade, matikan ini.)"
            checked={!!settings.ea_enable_paper}
            onChange={v => update({ ea_enable_paper: v }, 'enable_paper')}
            saving={saving === 'enable_paper'}
            saved={savedAt === 'enable_paper'}
          />

          {liveMode && (
            <div className="bg-rose-950/40 border border-rose-700/50 rounded-lg p-2.5 mt-2 flex gap-2">
              <AlertTriangle size={14} className="text-rose-400 shrink-0 mt-0.5" />
              <div className="text-[10px] text-rose-200 leading-relaxed">
                <p className="font-bold mb-0.5">LIVE MODE AKTIF</p>
                <p>EA akan execute order beneran di akun MT5 lo. Pastikan akun demo, BUKAN akun live, kalau lo lagi paper test.</p>
              </div>
            </div>
          )}
        </Section>

        {/* Daily limits */}
        <Section title="Daily Limits (anti over-trading)" icon={<Shield size={13} />}>
          <NumberRow
            label="Max trade per hari"
            sub="Hard cap berapa trade boleh open per UTC day. Default 5. Maksimum 10."
            value={settings.ea_max_trades_per_day ?? 5}
            min={HARD_CAPS.max_trades_per_day.min}
            max={HARD_CAPS.max_trades_per_day.max}
            step={1}
            onChange={v => update({ ea_max_trades_per_day: v }, 'max_per_day')}
            saving={saving === 'max_per_day'}
            saved={savedAt === 'max_per_day'}
            unit="trade"
          />
          <NumberRow
            label="Max open positions"
            sub="Berapa trade boleh OPEN bersamaan. Default 1 (most disciplined). Maksimum 5."
            value={settings.ea_max_open_positions ?? 1}
            min={HARD_CAPS.max_open_positions.min}
            max={HARD_CAPS.max_open_positions.max}
            step={1}
            onChange={v => update({ ea_max_open_positions: v }, 'max_open')}
            saving={saving === 'max_open'}
            saved={savedAt === 'max_open'}
            unit="posisi"
          />
          <NumberRow
            label="Daily loss kill switch"
            sub="EA berhenti trade kalau loss harian capai % ini dari starting balance. Default 5%."
            value={settings.ea_daily_loss_pct ?? 5.0}
            min={HARD_CAPS.daily_loss_pct.min}
            max={HARD_CAPS.daily_loss_pct.max}
            step={0.5}
            onChange={v => update({ ea_daily_loss_pct: v }, 'daily_loss')}
            saving={saving === 'daily_loss'}
            saved={savedAt === 'daily_loss'}
            unit="%"
          />
        </Section>

        {/* Risk per trade */}
        <Section title="Risk Per Trade" icon={<TrendingUp size={13} />}>
          <NumberRow
            label="Risk per trade"
            sub="% balance yang di-risk per trade (= jarak entry ke SL × lot). Default 1%, hard cap 3%. Lo set 2% sesuai preferensi."
            value={settings.ea_risk_per_trade_pct ?? 1.0}
            min={HARD_CAPS.risk_per_trade_pct.min}
            max={HARD_CAPS.risk_per_trade_pct.max}
            step={0.1}
            onChange={v => update({ ea_risk_per_trade_pct: v }, 'risk_pct')}
            saving={saving === 'risk_pct'}
            saved={savedAt === 'risk_pct'}
            unit="%"
          />
          <NumberRow
            label="Min confidence buat execute"
            sub="EA skip signal kalau confidence di bawah ini. Default 65%. Naikin = lebih selective."
            value={settings.ea_min_confidence_pct ?? 65}
            min={HARD_CAPS.min_confidence_pct.min}
            max={HARD_CAPS.min_confidence_pct.max}
            step={5}
            onChange={v => update({ ea_min_confidence_pct: v }, 'min_conf')}
            saving={saving === 'min_conf'}
            saved={savedAt === 'min_conf'}
            unit="%"
          />
        </Section>

        {/* Break-even */}
        <Section title="Break-Even SL" icon={<Lock size={13} />}>
          <Toggle
            label="Enable Break-Even"
            sub="Auto move SL ke entry+lock saat profit capai trigger. Lock-in profit, eliminate risk."
            checked={!!settings.ea_enable_break_even}
            onChange={v => update({ ea_enable_break_even: v }, 'enable_bep')}
            saving={saving === 'enable_bep'}
            saved={savedAt === 'enable_bep'}
          />
          {settings.ea_enable_break_even && (
            <>
              <NumberRow
                label="BEP trigger"
                sub="Move SL ke break-even saat profit capai jumlah pips ini. Default 50 pips ($5 untuk gold)."
                value={settings.ea_break_even_trigger_pips ?? 50}
                min={HARD_CAPS.bep_trigger_pips.min}
                max={HARD_CAPS.bep_trigger_pips.max}
                step={5}
                onChange={v => update({ ea_break_even_trigger_pips: v }, 'bep_trigger')}
                saving={saving === 'bep_trigger'}
                saved={savedAt === 'bep_trigger'}
                unit="pips"
              />
              <NumberRow
                label="BEP lock"
                sub="Berapa pips di atas entry untuk lock profit (0 = murni break-even, 5 = guarantee +5 pip)."
                value={settings.ea_break_even_lock_pips ?? 5}
                min={HARD_CAPS.bep_lock_pips.min}
                max={HARD_CAPS.bep_lock_pips.max}
                step={1}
                onChange={v => update({ ea_break_even_lock_pips: v }, 'bep_lock')}
                saving={saving === 'bep_lock'}
                saved={savedAt === 'bep_lock'}
                unit="pips"
              />
            </>
          )}
        </Section>

        {/* Trailing stop */}
        <Section title="Trailing Stop" icon={<Move size={13} />}>
          <Toggle
            label="Enable Trailing Stop"
            sub="Setelah profit capai trigger, SL ngikutin price by distance. Maximize TP potential."
            checked={!!settings.ea_enable_trailing}
            onChange={v => update({ ea_enable_trailing: v }, 'enable_trail')}
            saving={saving === 'enable_trail'}
            saved={savedAt === 'enable_trail'}
          />
          {settings.ea_enable_trailing && (
            <>
              <NumberRow
                label="Trailing trigger"
                sub="Mulai trailing saat profit capai jumlah pips ini. Default 100 pips ($10)."
                value={settings.ea_trailing_trigger_pips ?? 100}
                min={HARD_CAPS.trailing_trigger.min}
                max={HARD_CAPS.trailing_trigger.max}
                step={10}
                onChange={v => update({ ea_trailing_trigger_pips: v }, 'trail_trigger')}
                saving={saving === 'trail_trigger'}
                saved={savedAt === 'trail_trigger'}
                unit="pips"
              />
              <NumberRow
                label="Trailing distance"
                sub="Berapa pips di belakang current price untuk SL. Default 30 pips. Lebih kecil = lebih ketat."
                value={settings.ea_trailing_distance_pips ?? 30}
                min={HARD_CAPS.trailing_distance.min}
                max={HARD_CAPS.trailing_distance.max}
                step={5}
                onChange={v => update({ ea_trailing_distance_pips: v }, 'trail_dist')}
                saving={saving === 'trail_dist'}
                saved={savedAt === 'trail_dist'}
                unit="pips"
              />
            </>
          )}
        </Section>

        {/* Status snapshot */}
        <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-3 text-[10px] text-slate-500 leading-relaxed">
          <p className="text-slate-300 font-semibold mb-1">Konfigurasi sekarang:</p>
          <ul className="space-y-0.5 font-mono text-[10px]">
            <li>Mode: <span className={liveMode ? 'text-rose-400' : 'text-emerald-400'}>
              {liveMode ? 'LIVE EXECUTION' : settings.ea_enable_execution ? 'PAPER MODE' : 'DISABLED'}
            </span></li>
            <li>Daily cap: max {settings.ea_max_trades_per_day} trade/hari, max {settings.ea_max_open_positions} open simultan</li>
            <li>Risk: {settings.ea_risk_per_trade_pct}% per trade, kill at -{settings.ea_daily_loss_pct}% daily</li>
            <li>Min conf: {settings.ea_min_confidence_pct}%</li>
            <li>BEP: {settings.ea_enable_break_even ? `ON @${settings.ea_break_even_trigger_pips}pips lock+${settings.ea_break_even_lock_pips}` : 'OFF'}</li>
            <li>Trail: {settings.ea_enable_trailing ? `ON @${settings.ea_trailing_trigger_pips}pips dist ${settings.ea_trailing_distance_pips}` : 'OFF'}</li>
          </ul>
          <p className="text-slate-600 text-[9px] mt-2">EA polling /api/ea/config setiap 60 detik. Apply otomatis tanpa restart.</p>
        </div>
      </div>
    </main>
  )
}

// ─── UI Components ────────────────────────────────────────────────────────────

function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2 flex items-center gap-1.5">
        {icon} {title}
      </p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 divide-y divide-slate-800/80 overflow-hidden">
        {children}
      </div>
    </section>
  )
}

function Toggle({ label, sub, checked, onChange, saving, saved, warning }: {
  label: string; sub?: string; checked: boolean; onChange: (v: boolean) => void;
  saving?: boolean; saved?: boolean; warning?: boolean;
}) {
  return (
    <div className={`px-3.5 py-3 flex items-center gap-3 ${warning && checked ? 'bg-rose-950/20' : ''}`}>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold flex items-center gap-1.5 ${warning && checked ? 'text-rose-200' : 'text-slate-100'}`}>
          {label}
          {saved && <Check size={12} className="text-emerald-400" />}
          {saving && <Loader2 size={11} className="animate-spin text-slate-500" />}
        </p>
        {sub && <p className="text-[10px] text-slate-500 mt-0.5 leading-snug">{sub}</p>}
      </div>
      <button
        onClick={() => onChange(!checked)}
        disabled={saving}
        className={`relative w-10 h-5 rounded-full shrink-0 transition-colors ${
          checked ? (warning ? 'bg-rose-600' : 'bg-emerald-600') : 'bg-slate-700'
        }`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-0.5'
        }`} />
      </button>
    </div>
  )
}

function NumberRow({ label, sub, value, min, max, step, onChange, saving, saved, unit }: {
  label: string; sub?: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; saving?: boolean; saved?: boolean; unit?: string;
}) {
  const [local, setLocal] = useState(String(value))
  useEffect(() => { setLocal(String(value)) }, [value])

  const commit = () => {
    const n = Number(local)
    if (Number.isFinite(n) && n >= min && n <= max && n !== value) {
      onChange(n)
    } else if (n < min || n > max) {
      setLocal(String(value))
    }
  }

  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-sm font-semibold text-slate-100 flex items-center gap-1.5">
          {label}
          {saved && <Check size={12} className="text-emerald-400" />}
          {saving && <Loader2 size={11} className="animate-spin text-slate-500" />}
        </p>
        <span className="text-[10px] text-slate-500 tabular-nums">
          range {min}–{max}{unit ? ` ${unit}` : ''}
        </span>
      </div>
      {sub && <p className="text-[10px] text-slate-500 leading-snug mb-2">{sub}</p>}
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={local}
          min={min} max={max} step={step}
          onChange={e => setLocal(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          className="flex-1 bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-1.5 text-sm text-slate-100 font-mono tabular-nums focus:outline-none focus:border-sky-500"
        />
        {unit && <span className="text-[11px] text-slate-500 font-mono w-10">{unit}</span>}
      </div>
    </div>
  )
}
