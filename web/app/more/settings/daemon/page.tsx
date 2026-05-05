'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Copy, Check, Terminal, Download, Loader2, Server, Eye, EyeOff, Key, Crown, MoonStar, Cpu } from 'lucide-react'
import {
  getAppSettings, getDaemonHeartbeat, isDaemonOnline,
  getDaemonWorkers, getActiveWorkerId, setActiveWorkerId,
  type AppSettings, type DaemonHeartbeat, type DaemonWorkerStatus,
} from '@/lib/settings'

const REPO_URL = 'https://github.com/proreyhanwijaya111/yeehee.git'
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// LocalStorage keys for persisting input across page loads (browser only)
const LS_OPENROUTER = 'yeehee:install:openrouter'
const LS_TWELVE     = 'yeehee:install:twelve'
const LS_SVCKEY     = 'yeehee:install:svckey'

export default function DaemonPage() {
  const [s, setS] = useState<AppSettings | null>(null)
  const [hb, setHb] = useState<DaemonHeartbeat | null>(null)
  const [activeTab, setActiveTab] = useState<'install' | 'update' | 'service'>('install')
  const [showSecrets, setShowSecrets] = useState(false)

  // Multi-PC active-passive lock state (migration 007)
  const [workers,    setWorkers]    = useState<DaemonWorkerStatus[]>([])
  const [activeWid,  setActiveWid]  = useState<string | null>(null)
  const [switchingWid, setSwitchingWid] = useState<string | null>(null)

  // Optional extra keys (multi-PC ready). Persisted to localStorage so user
  // doesn't have to retype every time. Empty string = "skip / use existing".
  const [openRouterKey, setOpenRouterKey] = useState('')
  const [twelveKey,     setTwelveKey]     = useState('')
  const [svcKey,        setSvcKey]        = useState('')

  const refreshWorkers = async () => {
    const [list, active] = await Promise.all([getDaemonWorkers(), getActiveWorkerId()])
    setWorkers(list)
    setActiveWid(active)
  }

  useEffect(() => {
    Promise.all([getAppSettings(), getDaemonHeartbeat()]).then(([a, h]) => { setS(a); setHb(h) })
    refreshWorkers()
    if (typeof window !== 'undefined') {
      setOpenRouterKey(localStorage.getItem(LS_OPENROUTER) || '')
      setTwelveKey(localStorage.getItem(LS_TWELVE) || '')
      setSvcKey(localStorage.getItem(LS_SVCKEY) || '')
    }
    // Auto-refresh workers every 30s while on this page
    const interval = setInterval(refreshWorkers, 30_000)
    return () => clearInterval(interval)
  }, [])

  const handleSwitchPrimary = async (workerId: string) => {
    setSwitchingWid(workerId)
    try {
      const ok = await setActiveWorkerId(workerId)
      if (ok) await refreshWorkers()
    } finally {
      setSwitchingWid(null)
    }
  }

  // Persist to localStorage on change (debounced via setTimeout in handler)
  const persistKey = (lsKey: string, value: string) => {
    if (typeof window === 'undefined') return
    if (value) localStorage.setItem(lsKey, value)
    else localStorage.removeItem(lsKey)
  }

  const online = isDaemonOnline(hb)

  if (!s) return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )

  // Copy ALWAYS uses the real key — masking only affects what's rendered on screen.
  // (Previous bug: masking applied to copy too, so users pasted bullet chars and
  //  got Supabase HTTP 401 auth fail.)
  const extras = { openRouterKey, twelveKey, svcKey }
  const installScriptCopy    = buildInstallScript(SUPABASE_URL, SUPABASE_KEY, extras, true)
  const installScriptDisplay = buildInstallScript(SUPABASE_URL, SUPABASE_KEY, extras, showSecrets)
  const updateScript  = buildUpdateScript()
  const serviceScriptCopy    = buildServiceScript(SUPABASE_URL, SUPABASE_KEY, extras)
  const serviceScriptDisplay = buildServiceScript(SUPABASE_URL, SUPABASE_KEY, extras, showSecrets)

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-pink-700/30 border border-pink-600/30 flex items-center justify-center">
          <Server size={16} className="text-pink-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Daemon PC rumah</h1>
          <p className="text-[11px] text-slate-500">Worker Python signal engine + Mira queue.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Multi-PC worker list (migration 007) */}
        {workers.length > 0 && (
          <Section
            title={`Workers aktif (${workers.length})`}
            sub="Multi-PC active-passive: hanya 1 PRIMARY yang push signal + buka trade. STANDBY workers cuma kirim heartbeat. Klik worker buat jadiin primary manual."
          >
            <div className="space-y-1.5">
              {workers.map(w => {
                const isPrimary  = activeWid === w.worker_id
                const isOnline   = w.status === 'fresh' || w.status === 'recent'
                const isSwitching = switchingWid === w.worker_id
                const dotColor =
                  w.status === 'fresh' ? 'bg-emerald-500' :
                  w.status === 'recent' ? 'bg-amber-500' : 'bg-slate-500'
                return (
                  <button
                    key={w.worker_id}
                    onClick={() => isPrimary || isSwitching ? null : handleSwitchPrimary(w.worker_id)}
                    disabled={isPrimary || isSwitching || !isOnline}
                    className={`w-full text-left rounded-lg border transition-colors px-3 py-2.5 ${
                      isPrimary
                        ? 'bg-amber-950/30 border-amber-700/50'
                        : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 disabled:opacity-50'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
                      {isPrimary
                        ? <Crown size={13} className="text-amber-400 shrink-0" />
                        : <MoonStar size={13} className="text-slate-500 shrink-0" />}
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-mono text-slate-200 truncate">{w.worker_id}</p>
                        <p className="text-[10px] text-slate-500 truncate">
                          {w.hostname || '?'} · {Math.floor(w.heartbeat_age_seconds / 60)}m ago
                          {w.cpu_percent !== null && <> · CPU {w.cpu_percent}%</>}
                        </p>
                      </div>
                      <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0 ${
                        isPrimary
                          ? 'bg-amber-700/40 text-amber-200'
                          : isOnline
                            ? 'bg-slate-800 text-slate-400'
                            : 'bg-rose-900/40 text-rose-300'
                      }`}>
                        {isSwitching ? '...' : isPrimary ? 'PRIMARY' : isOnline ? 'STANDBY' : 'STALE'}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
            {!activeWid && workers.length > 0 && (
              <p className="text-[10px] text-amber-400 mt-1.5">
                Belum ada PRIMARY. Daemon akan auto-claim cycle berikutnya.
              </p>
            )}
          </Section>
        )}

        {/* Status pill (compact) */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl px-3.5 py-3 flex items-center gap-3">
          <span className={`w-2 h-2 rounded-full shrink-0 ${
            online
              ? 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]'
              : 'bg-amber-500'
          }`} />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-slate-200">
              {online ? 'Daemon online' : 'Daemon offline'}
            </p>
            <p className="text-[10px] text-slate-500 truncate">
              {hb?.hostname && <span className="font-mono">{hb.hostname}</span>}
              {hb?.last_signal_at && <> · signal {timeAgo(hb.last_signal_at)}</>}
              {!hb && <>belum pernah connect</>}
              {hb?.error && <span className="text-rose-400"> · {hb.error.slice(0, 40)}</span>}
            </p>
          </div>
        </div>

        {/* Architecture (collapsed by default) */}
        <details className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden">
          <summary className="px-3.5 py-3 cursor-pointer text-xs font-semibold text-slate-300 hover:bg-slate-800/40 select-none flex items-center gap-2">
            <span className="w-1 h-1 rounded-full bg-slate-500" />
            Cara kerja daemon
          </summary>
          <div className="px-3.5 pb-3.5 pt-1 space-y-2 text-[11px] text-slate-500 leading-relaxed border-t border-slate-800/80">
            <p className="text-slate-400">Tiap {s.refresh_interval_minutes} menit:</p>
            <ol className="list-decimal pl-4 space-y-1">
              <li>Pull config (provider key, model, agent settings) dari Supabase</li>
              <li>Fetch data XAU/USD + intermarket + COT + calendar</li>
              <li>Run 9-agent LLM debate (paralel per tier)</li>
              <li>Push hasil signal ke Supabase</li>
              <li>Vercel UI baca dari Supabase, tampilkan ke HP lo</li>
              <li>Cek queue Mira chatbot tiap 5 detik, proses kalau ada</li>
            </ol>
            <p className="pt-1 text-amber-400">Port lokal 3031 - beda dari Mira WA worker (3030). Aman jalan barengan.</p>
          </div>
        </details>

        {/* Tabs */}
        <div className="grid grid-cols-3 gap-px bg-slate-800/80 rounded-xl overflow-hidden p-px">
          {[
            { id: 'install', label: 'Install' },
            { id: 'update',  label: 'Update' },
            { id: 'service', label: 'Auto-start' },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id as 'install' | 'update' | 'service')}
              className={`py-2 px-3 text-[11px] font-semibold transition-colors ${
                activeTab === t.id
                  ? 'bg-sky-900/40 text-sky-100 rounded-[10px]'
                  : 'bg-slate-900/40 text-slate-400 hover:text-slate-200 rounded-[10px]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

      {activeTab === 'install' && (
        <>
          {/* INTRO — what is this for */}
          <div className="bg-sky-950/30 border border-sky-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
            <p className="text-sky-100 font-semibold mb-1.5">Install daemon di PC rumah lo</p>
            <p className="text-sky-200/80 mb-2">
              Daemon = program kecil yang jalan terus di PC lo, fetch data XAU + jalanin AI agent + push signal ke cloud. Tanpa daemon, signal di app tidak update otomatis.
            </p>
            <p className="text-sky-200/70">
              <span className="font-semibold text-sky-100">Total waktu</span>: ~5 menit (otomatis install Python + Git kalo belum ada). Cukup 1× setup per PC.
            </p>
          </div>

          {/* STEP 1: Fill API keys */}
          <Section
            title="Langkah 1 · Isi API key (di HP/laptop ini, BUKAN PC tujuan)"
            sub="Form ini cuma simpan key di browser lo (localStorage). Kosong juga boleh, tapi daemon-nya kurang optimal. Lo bisa skip ini kalo udah pernah isi sebelumnya."
          >
            <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-3 mb-3 text-[11px] text-slate-400 space-y-1.5 leading-relaxed">
              <p className="text-slate-200 font-semibold">Cara dapat API key (semua gratis):</p>
              <p>
                <span className="font-bold text-amber-300">OpenRouter</span>: buka{' '}
                <a href="https://openrouter.ai/keys" target="_blank" rel="noopener" className="text-sky-300 underline">openrouter.ai/keys</a>{' '}
                → login Google → Create Key → copy
              </p>
              <p>
                <span className="font-bold text-amber-300">Twelve Data</span>: buka{' '}
                <a href="https://twelvedata.com" target="_blank" rel="noopener" className="text-sky-300 underline">twelvedata.com</a>{' '}
                → Sign Up → Dashboard → API Keys → copy
              </p>
              <p>
                <span className="font-bold text-amber-300">Supabase service key</span> (optional): Supabase dashboard → Settings → API → service_role secret
              </p>
            </div>
            <KeyInput
              label="OpenRouter API key"
              placeholder="sk-or-v1-..."
              value={openRouterKey}
              onChange={(v) => { setOpenRouterKey(v); persistKey(LS_OPENROUTER, v) }}
              hint="Tanpa ini → daemon pakai 4-agent rule_engine (kurang akurat). Dengan ini → 12-agent LLM full pipeline."
              showSecrets={showSecrets}
            />
            <KeyInput
              label="Twelve Data API key"
              placeholder="33e7..."
              value={twelveKey}
              onChange={(v) => { setTwelveKey(v); persistKey(LS_TWELVE, v) }}
              hint="Tanpa ini → harga emas delay 15 menit (yfinance). Dengan ini → real-time spot."
              showSecrets={showSecrets}
            />
            <KeyInput
              label="Supabase service-role key (optional, boleh kosong)"
              placeholder="eyJh..."
              value={svcKey}
              onChange={(v) => { setSvcKey(v); persistKey(LS_SVCKEY, v) }}
              hint="Anon key dari env udah cukup. Service key cuma kalo lo enable Row-Level Security di Supabase."
              showSecrets={showSecrets}
            />
            <p className="text-[10px] text-emerald-400 mt-2">
              ✓ Key disimpan di browser lo doang (localStorage), tidak di-upload ke server kita.
            </p>
          </Section>

          {/* STEP 2: Copy + Run */}
          <Section
            title="Langkah 2 · Copy 1 baris di bawah, paste ke PowerShell di PC tujuan"
            sub="Boleh PC rumah, laptop, atau VPS Windows. PowerShell biasa (BUKAN CMD!). Klik tombol copy biar aman."
          >
            {/* Visual instruction first */}
            <ol className="bg-slate-900/40 border border-slate-700/50 rounded-lg p-3 text-[11px] text-slate-300 leading-relaxed list-decimal pl-5 space-y-1.5 mb-3">
              <li>Di PC tujuan, klik tombol <span className="font-bold text-slate-100">Start</span> Windows → ketik <span className="font-mono bg-slate-800 px-1.5 rounded">PowerShell</span> → Enter</li>
              <li>Click kanan tombol copy di kotak code di bawah → seluruh script ke clipboard</li>
              <li>Di PowerShell window, click kanan → paste → Enter sekali</li>
              <li>Tunggu 3-5 menit. Auto install Python, Git, daemon. Window PowerShell akan tetap kebuka — itu daemon-nya jalan</li>
            </ol>

            <div className="flex items-center gap-2 mb-2">
              <button
                onClick={() => setShowSecrets(!showSecrets)}
                className="flex items-center gap-1 px-2 py-1 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-[10px] text-slate-300"
              >
                {showSecrets ? <EyeOff size={11} /> : <Eye size={11} />}
                {showSecrets ? 'sembunyikan' : 'tampilkan'} kredensial di tampilan
              </button>
              <p className="text-[10px] text-emerald-400">✓ Tombol copy selalu pakai key asli</p>
            </div>
            <CodeBlock displayCode={installScriptDisplay} copyCode={installScriptCopy} multiline />
          </Section>

          {/* STEP 3: Verification */}
          <Section
            title="Langkah 3 · Verifikasi daemon udah jalan"
            sub="Tunggu 1-2 menit setelah Step 2 selesai. Daemon perlu fetch data + run cycle pertama."
          >
            <ol className="text-[11px] text-slate-400 list-decimal pl-5 space-y-1.5 leading-relaxed">
              <li>Refresh halaman ini (pull-down di mobile, atau F5 di laptop)</li>
              <li>Lihat status pill di paling atas:
                <ul className="list-none pl-2 mt-1 space-y-0.5">
                  <li>🟢 <span className="text-emerald-400 font-semibold">Daemon online</span> = berhasil, lo sudah selesai</li>
                  <li>🟡 <span className="text-amber-400 font-semibold">Daemon offline</span> = belum push, tunggu 1 menit lagi</li>
                </ul>
              </li>
              <li>Buka <Link href="/signals" className="text-sky-300 underline">/signals</Link> di app — signal harus muncul dengan timestamp recent</li>
            </ol>

            <details className="mt-3 bg-slate-900/40 rounded-lg border border-slate-800">
              <summary className="px-3 py-2 cursor-pointer text-[11px] text-slate-300 font-semibold">
                Kalau masih offline setelah 5 menit
              </summary>
              <div className="px-3 pb-3 text-[10px] text-slate-400 leading-relaxed space-y-1.5">
                <p>Cek di window PowerShell yang masih kebuka — apakah ada error merah?</p>
                <p>Common errors + fix:</p>
                <ul className="list-disc pl-4 space-y-1">
                  <li><span className="font-mono">[fatal] SUPABASE_URL...</span> = .env corrupt, run installer ulang</li>
                  <li><span className="font-mono">no LLM credential</span> = OpenRouter key salah, buka openrouter.ai/keys → cek key valid</li>
                  <li><span className="font-mono">winget tidak ditemukan</span> = manual install Python 3.11+ dari python.org dulu</li>
                  <li><span className="font-mono">git command not found</span> = manual install Git dari git-scm.com</li>
                </ul>
              </div>
            </details>
          </Section>

          {/* Notes */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-3 text-[10px] text-slate-500 leading-relaxed space-y-1.5">
            <p className="text-slate-300 font-semibold">Catatan penting:</p>
            <p>• Window PowerShell harus tetap kebuka biar daemon jalan. Tutup window = daemon stop.</p>
            <p>• Untuk auto-start saat boot (ga perlu PowerShell terus kebuka), lihat tab <span className="font-bold text-slate-300">Auto-start</span>.</p>
            <p>• Worker ID auto-generate per install. Kalo lo install di 2 PC, masing-masing punya worker_id beda — keduanya bakal muncul di "Workers aktif" di atas.</p>
          </div>
        </>
      )}

      {activeTab === 'update' && (
        <>
          <div className="bg-sky-950/30 border border-sky-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
            <p className="text-sky-100 font-semibold mb-1">Update daemon ke versi terbaru</p>
            <p className="text-sky-200/80">
              Jalankan kalau ada commit baru di repo (e.g. fitur baru, bug fix). Cukup di PC tempat daemon udah ter-install.
            </p>
          </div>

          <Section
            title="Langkah 1 · Stop daemon yang lama"
            sub="Daemon process di memory harus di-kill biar code baru ke-load."
          >
            <CodeBlock multiline code={`Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*daemon.main*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`} />
            <p className="text-[10px] text-slate-500 mt-2">
              Output: kalo ada baris <span className="font-mono">"PID killed"</span> = success. Kalau kosong = ga ada daemon python yang running, lanjut Step 2.
            </p>
          </Section>

          <Section
            title="Langkah 2 · Pull code baru + restart"
          >
            <CodeBlock code={updateScript} multiline />
            <p className="text-[10px] text-slate-500 mt-2">
              Daemon akan re-start dengan code latest. Cek log baris pertama harus muncul <span className="font-mono">"yeehee daemon v1.0.0"</span>.
            </p>
          </Section>

          <Section
            title="Langkah 3 · Verifikasi"
          >
            <p className="text-[11px] text-slate-400">
              Refresh halaman ini → status pill harus tetap 🟢 online + timestamp signal terbaru.
            </p>
          </Section>
        </>
      )}

      {activeTab === 'service' && (
        <>
          <div className="bg-amber-950/30 border border-amber-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
            <p className="text-amber-100 font-semibold mb-1">Auto-start daemon saat Windows boot</p>
            <p className="text-amber-200/80">
              Tanpa ini: lo harus run installer manual setiap kali PC restart. Dengan ini: daemon auto-start setiap kali Windows hidup, ga perlu login dulu.
            </p>
            <p className="text-amber-200/70 mt-2">
              <span className="font-semibold">⚠️ Butuh PowerShell sebagai Administrator</span>. Klik kanan PowerShell → Run as Administrator.
            </p>
          </div>

          <Section
            title="Langkah 1 · Buka PowerShell sebagai Administrator"
            sub="Click Start → ketik PowerShell → klik kanan → Run as Administrator. Window judulnya akan ada 'Administrator: Windows PowerShell'."
          >
            <p className="text-[11px] text-slate-400">
              Kalau muncul UAC popup ("Allow this app to make changes?") → klik <span className="font-bold text-slate-200">Yes</span>.
            </p>
          </Section>

          <Section
            title="Langkah 2 · Copy + run script di bawah"
          >
            <CodeBlock displayCode={serviceScriptDisplay} copyCode={serviceScriptCopy} multiline />
            <p className="text-[10px] text-slate-500 mt-2">
              Script ini install NSSM (tool buat bikin Windows Service), register daemon-nya, lalu start service. Total ~3-5 menit.
            </p>
          </Section>

          <Section
            title="Langkah 3 · Test setelah PC restart"
          >
            <ol className="text-[11px] text-slate-400 list-decimal pl-5 space-y-1.5">
              <li>Restart Windows lo</li>
              <li>Tanpa login, daemon udah jalan di background</li>
              <li>Refresh halaman ini setelah login → status 🟢 online</li>
            </ol>
          </Section>

          <Section
            title="Stop / Start / Restart service"
            sub="Pakai PowerShell sebagai Administrator."
          >
            <div className="space-y-2">
              <div>
                <p className="text-[10px] text-slate-500 mb-1 font-semibold">Stop:</p>
                <CodeBlock code="net stop yeehee-signal-daemon" />
              </div>
              <div>
                <p className="text-[10px] text-slate-500 mb-1 font-semibold">Start:</p>
                <CodeBlock code="net start yeehee-signal-daemon" />
              </div>
              <div>
                <p className="text-[10px] text-slate-500 mb-1 font-semibold">Cek status:</p>
                <CodeBlock code="Get-Service yeehee-signal-daemon" />
              </div>
            </div>
          </Section>
        </>
      )}
      </div>
    </main>
  )
}

// ─── Script Builders ─────────────────────────────────────────────────────────

interface ExtraKeys {
  openRouterKey: string
  twelveKey: string
  svcKey: string
}

/** Mask a key for display: first 5 + bullets + last 4 (or all bullets if too short) */
function maskKey(k: string): string {
  if (!k) return ''
  if (k.length <= 12) return '••••••••'
  return k.slice(0, 5) + '••••••••' + k.slice(-4)
}

/** Build optional `-Param 'value'` segment, or empty string if value missing */
function optParam(name: string, value: string, show: boolean): string {
  if (!value) return ''
  const v = show ? value : maskKey(value)
  return ` -${name} '${v}'`
}

function buildInstallScript(
  supaUrl: string,
  supaAnon: string,
  extras: ExtraKeys,
  show: boolean,
): string {
  const url     = supaUrl  || 'YOUR_SUPABASE_URL'
  const anon    = show ? (supaAnon || 'YOUR_SUPABASE_ANON_KEY') : maskKey(supaAnon) || 'YOUR_SUPABASE_ANON_KEY'

  // Optional segments (only added when key has value)
  const orSeg     = optParam('OpenRouterKey',      extras.openRouterKey, show)
  const tdSeg     = optParam('TwelveDataKey',      extras.twelveKey,     show)
  const svcSeg    = optParam('SupabaseServiceKey', extras.svcKey,        show)

  // Single-line bootstrap — pattern same as Clinix Mira worker.
  // Script body served from /api/setup/script (always latest, no clipboard fragility).
  return (
    `Set-ExecutionPolicy -Scope Process Bypass -Force; ` +
    `iwr https://yeehee.vercel.app/api/setup/script -OutFile $env:TEMP\\yeehee-setup.ps1; ` +
    `& $env:TEMP\\yeehee-setup.ps1 -SupabaseUrl '${url}' -SupabaseAnonKey '${anon}'` +
    `${svcSeg}${orSeg}${tdSeg}`
  )
}

function buildUpdateScript(): string {
  return [
    `# Update daemon: pull versi terbaru lalu restart`,
    `Set-ExecutionPolicy -Scope Process Bypass -Force`,
    `$Dest = "$HOME\\yeehee-daemon"`,
    `Set-Location $Dest`,
    `git pull --rebase --autostash`,
    `& .\\.venv\\Scripts\\python.exe -m pip install -r daemon\\requirements.txt --quiet`,
    ``,
    `# Kalau jalan sebagai Service:`,
    `# net stop yeehee-signal-daemon; net start yeehee-signal-daemon`,
    ``,
    `# Kalau jalan foreground (window manual): Ctrl+C window lama, run ini:`,
    `& .\\.venv\\Scripts\\python.exe -m daemon.main`,
  ].join('\n')
}

function buildServiceScript(
  supaUrl: string,
  supaAnon: string,
  extras: ExtraKeys,
  show: boolean = true,
): string {
  const url     = supaUrl  || 'YOUR_SUPABASE_URL'
  const anon    = show ? (supaAnon || 'YOUR_SUPABASE_ANON_KEY') : maskKey(supaAnon) || 'YOUR_SUPABASE_ANON_KEY'
  const orSeg   = optParam('OpenRouterKey',      extras.openRouterKey, show)
  const tdSeg   = optParam('TwelveDataKey',      extras.twelveKey,     show)
  const svcSeg  = optParam('SupabaseServiceKey', extras.svcKey,        show)
  return (
    `# Install sebagai Windows Service (auto-start saat boot). Run as Administrator.\n` +
    `Set-ExecutionPolicy -Scope Process Bypass -Force; ` +
    `iwr https://yeehee.vercel.app/api/setup/script -OutFile $env:TEMP\\yeehee-setup.ps1; ` +
    `& $env:TEMP\\yeehee-setup.ps1 -SupabaseUrl '${url}' -SupabaseAnonKey '${anon}'` +
    `${svcSeg}${orSeg}${tdSeg} -InstallServiceOnly`
  )
}

// ─── UI Bits ─────────────────────────────────────────────────────────────────

function Section({ title, sub, children }: {
  title: string; sub?: string; children: React.ReactNode
}) {
  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">{title}</p>
      <div className="bg-slate-800/40 rounded-2xl border border-slate-800 px-3.5 py-3 space-y-2">
        {sub && <p className="text-[11px] text-slate-500 leading-relaxed">{sub}</p>}
        {children}
      </div>
    </section>
  )
}

function KeyInput({ label, placeholder, value, onChange, hint, showSecrets }: {
  label: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  hint?: string
  showSecrets: boolean
}) {
  return (
    <div className="space-y-1">
      <label className="text-[11px] font-semibold text-slate-300 flex items-center gap-1.5">
        <Key size={11} className="text-slate-500" />
        {label}
        {value && <span className="text-emerald-400 text-[10px]">✓ tersimpan</span>}
      </label>
      <input
        type={showSecrets ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-100 font-mono placeholder:text-slate-700 focus:outline-none focus:border-sky-700"
        autoComplete="off"
        spellCheck={false}
      />
      {hint && <p className="text-[10px] text-slate-500 leading-tight">{hint}</p>}
    </div>
  )
}

function CodeBlock({ code, displayCode, copyCode, multiline }: {
  code?: string
  displayCode?: string
  copyCode?: string
  multiline?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const shown   = displayCode ?? code ?? ''
  const onCopy  = copyCode    ?? code ?? ''
  const handleCopy = async () => {
    await navigator.clipboard.writeText(onCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="relative">
      <pre className={`bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-[11px] text-slate-200 font-mono overflow-x-auto ${
        multiline ? 'whitespace-pre' : 'whitespace-nowrap'
      } leading-relaxed`}>
        {shown}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-1.5 right-1.5 p-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-slate-100 transition-colors"
        title="Copy script asli"
      >
        {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
      </button>
    </div>
  )
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'baru saja'
  if (m < 60) return `${m} menit lalu`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} jam lalu`
  return `${Math.floor(h / 24)} hari lalu`
}
