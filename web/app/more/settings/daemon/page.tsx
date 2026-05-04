'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Copy, Check, Terminal, Download, Loader2, Server, Eye, EyeOff } from 'lucide-react'
import {
  getAppSettings, getDaemonHeartbeat, isDaemonOnline,
  type AppSettings, type DaemonHeartbeat,
} from '@/lib/settings'

const REPO_URL = 'https://github.com/proreyhanwijaya111/yeehee.git'
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

export default function DaemonPage() {
  const [s, setS] = useState<AppSettings | null>(null)
  const [hb, setHb] = useState<DaemonHeartbeat | null>(null)
  const [activeTab, setActiveTab] = useState<'install' | 'update' | 'service'>('install')
  const [showSecrets, setShowSecrets] = useState(false)

  useEffect(() => {
    Promise.all([getAppSettings(), getDaemonHeartbeat()]).then(([a, h]) => { setS(a); setHb(h) })
  }, [])

  const online = isDaemonOnline(hb)

  if (!s) return (
    <main className="flex items-center justify-center min-h-[60vh]">
      <Loader2 className="animate-spin text-slate-500" size={28} />
    </main>
  )

  // Copy ALWAYS uses the real key — masking only affects what's rendered on screen.
  // (Previous bug: masking applied to copy too, so users pasted bullet chars and
  //  got Supabase HTTP 401 auth fail.)
  const installScriptCopy    = buildInstallScript(SUPABASE_URL, SUPABASE_KEY, true)
  const installScriptDisplay = buildInstallScript(SUPABASE_URL, SUPABASE_KEY, showSecrets)
  const updateScript  = buildUpdateScript()
  const serviceScriptCopy    = buildServiceScript(SUPABASE_URL, SUPABASE_KEY)
  const serviceScriptDisplay = buildServiceScript(
    SUPABASE_URL,
    showSecrets ? SUPABASE_KEY : (SUPABASE_KEY ? SUPABASE_KEY.slice(0, 20) + '••••••••' : SUPABASE_KEY),
  )

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
          <Section
            title="One-liner Install"
            sub="Buka PowerShell biasa (BUKAN CMD), paste 1 baris ini, Enter sekali. Auto: install Python+Git kalau belum ada, clone repo, setup venv, install deps, write config, run daemon."
          >
            <div className="flex items-center gap-2 mb-2">
              <button
                onClick={() => setShowSecrets(!showSecrets)}
                className="flex items-center gap-1 px-2 py-1 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-[10px] text-slate-300"
              >
                {showSecrets ? <EyeOff size={11} /> : <Eye size={11} />}
                {showSecrets ? 'sembunyikan' : 'tampilkan'} kredensial di tampilan
              </button>
              <p className="text-[10px] text-emerald-400">✓ Copy selalu pake key asli</p>
            </div>
            <CodeBlock displayCode={installScriptDisplay} copyCode={installScriptCopy} multiline />
          </Section>

          <Section
            title="Yang dilakukan script"
            sub="Untuk transparansi — script-nya sudah open source di repo daemon/."
          >
            <ol className="text-[11px] text-slate-400 list-decimal pl-5 space-y-1 leading-relaxed">
              <li>Bypass execution policy (per-process)</li>
              <li>Cek Python 3.13 + Git, auto-install via winget kalau belum ada</li>
              <li>Clone <span className="font-mono text-slate-300">github.com/proreyhanwijaya111/yeehee</span> ke <span className="font-mono text-slate-300">$HOME\yeehee-daemon</span></li>
              <li>Setup Python venv + install <span className="font-mono">daemon/requirements.txt</span></li>
              <li>Tulis <span className="font-mono">.env</span> dengan kredensial Supabase</li>
              <li>Run <span className="font-mono">python -m daemon.main</span> di window aktif</li>
            </ol>
          </Section>

          <Section
            title="Verifikasi"
            sub="Setelah daemon jalan, refresh halaman ini. Status di atas akan jadi 🟢 ONLINE dalam 1-2 menit."
          >
            <p className="text-[11px] text-slate-400">
              Window PowerShell akan tetap kebuka — itu daemon-nya jalan. Untuk auto-start saat boot Windows (ga perlu PowerShell window terus kebuka), lihat tab <span className="font-bold">Auto-start</span>.
            </p>
            <p className="text-[11px] text-amber-400 mt-2">
              ⚠️ Daemon ini terisolasi dari Mira WA Worker — folder beda (<span className="font-mono">yeehee-daemon</span> vs <span className="font-mono">mira-wa-worker</span>), port beda (3031 vs 3030), proses beda. Aman jalan barengan.
            </p>
          </Section>
        </>
      )}

      {activeTab === 'update' && (
        <>
          <Section
            title="Update daemon (pull versi terbaru)"
            sub="Jalankan ini di folder yeehee yang sudah ter-install."
          >
            <CodeBlock code={updateScript} multiline />
          </Section>
        </>
      )}

      {activeTab === 'service' && (
        <>
          <Section
            title="Auto-start saat boot Windows (NSSM)"
            sub="Pakai NSSM untuk register daemon sebagai Windows service — auto-start saat PC nyala."
          >
            <CodeBlock displayCode={serviceScriptDisplay} copyCode={serviceScriptCopy} multiline />
            <p className="text-[10px] text-slate-500 mt-2">
              Cara kerja: NSSM bikin Windows Service yang panggil `python daemon.py` saat boot. Service tetap jalan meski tidak login.
            </p>
          </Section>

          <Section
            title="Stop / restart service"
            sub="Pakai PowerShell sebagai administrator."
          >
            <CodeBlock code="net stop yeehee-daemon`nnet start yeehee-daemon" multiline />
          </Section>
        </>
      )}
      </div>
    </main>
  )
}

// ─── Script Builders ─────────────────────────────────────────────────────────

function buildInstallScript(supaUrl: string, supaKey: string, show: boolean): string {
  const url = supaUrl || 'YOUR_SUPABASE_URL'
  const key = show
    ? (supaKey || 'YOUR_SUPABASE_ANON_KEY')
    : (supaKey ? supaKey.slice(0, 20) + '••••••••' : 'YOUR_SUPABASE_ANON_KEY')
  // Single-line bootstrap — pattern same as Clinix Mira worker.
  // Script body served from /api/setup/script (always latest, no clipboard fragility).
  return (
    `Set-ExecutionPolicy -Scope Process Bypass -Force; ` +
    `iwr https://yeehee.vercel.app/api/setup/script -OutFile $env:TEMP\\yeehee-setup.ps1; ` +
    `& $env:TEMP\\yeehee-setup.ps1 -SupabaseUrl '${url}' -SupabaseAnonKey '${key}'`
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

function buildServiceScript(supaUrl: string, supaKey: string): string {
  const url = supaUrl || 'YOUR_SUPABASE_URL'
  const key = supaKey || 'YOUR_SUPABASE_ANON_KEY'
  return (
    `# Install sebagai Windows Service (auto-start saat boot). Run as Administrator.\n` +
    `Set-ExecutionPolicy -Scope Process Bypass -Force; ` +
    `iwr https://yeehee.vercel.app/api/setup/script -OutFile $env:TEMP\\yeehee-setup.ps1; ` +
    `& $env:TEMP\\yeehee-setup.ps1 -SupabaseUrl '${url}' -SupabaseAnonKey '${key}' -InstallServiceOnly`
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
