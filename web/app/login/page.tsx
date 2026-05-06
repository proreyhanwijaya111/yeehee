'use client'
import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { TrendingUp, Lock, User, Loader2, Eye, EyeOff } from 'lucide-react'

/**
 * Trader-themed login page. Dark + amber/gold accents, animated candlestick
 * background, mobile-first. Fires POST /api/auth/login with username +
 * password; backend sets httpOnly cookie. On success, router.push to redirect
 * target (defaults /).
 *
 * Initial admin: rey666 / tested1234 (hardcoded in env or hashed in DB).
 * Multi-user signup deferred to phase 2 with Supabase Auth.
 */
export default function LoginPage() {
  const router = useRouter()
  const params = useSearchParams()
  const next   = params.get('next') || '/'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPwd,  setShowPwd]  = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  // If already authenticated (cookie present), bounce to next.
  useEffect(() => {
    fetch('/api/auth/me', { cache: 'no-store' })
      .then(r => r.json())
      .then(j => { if (j.ok && j.user) router.replace(next) })
      .catch(() => {})
  }, [next, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('Username dan password wajib.')
      return
    }
    setLoading(true)
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      const j = await r.json()
      if (!r.ok || !j.ok) {
        setError(j.error || 'Login gagal — cek username/password.')
        setLoading(false)
        return
      }
      router.replace(next)
    } catch (e) {
      setError(`Network error: ${String(e)}`)
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen relative overflow-hidden bg-slate-950 flex items-center justify-center px-4 py-8">
      {/* Animated candlestick background */}
      <div className="absolute inset-0 pointer-events-none opacity-30">
        <CandlestickBackdrop />
      </div>

      {/* Subtle gold gradient sheen */}
      <div className="absolute inset-0 bg-gradient-to-br from-amber-900/10 via-transparent to-amber-900/5 pointer-events-none" />

      <div className="relative z-10 w-full max-w-sm">
        {/* Brand */}
        <div className="text-center mb-7">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-600 shadow-[0_0_30px_rgba(251,191,36,0.4)] mb-3">
            <TrendingUp size={28} className="text-slate-950" strokeWidth={2.5} />
          </div>
          <h1 className="text-3xl font-black text-slate-100 tracking-tight">
            yee<span className="text-amber-400">hee</span>
          </h1>
          <p className="text-[11px] text-slate-500 mt-1 tracking-wide uppercase">
            XAU/USD signal · 12-agent AI
          </p>
        </div>

        {/* Login card */}
        <form
          onSubmit={handleSubmit}
          className="bg-slate-900/70 backdrop-blur-xl border border-slate-800/80 rounded-3xl p-6 shadow-2xl shadow-black/40"
        >
          <h2 className="text-base font-bold text-slate-100 mb-1">Masuk ke akun lo</h2>
          <p className="text-[11px] text-slate-500 mb-5">
            Personal trading platform · single-user mode
          </p>

          {/* Username */}
          <label className="block mb-3">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1 block">
              Username
            </span>
            <div className="relative">
              <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="rey666"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-sm text-slate-100 font-mono placeholder:text-slate-700 focus:outline-none focus:border-amber-500/60 focus:ring-1 focus:ring-amber-500/30 transition-colors"
              />
            </div>
          </label>

          {/* Password */}
          <label className="block mb-4">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1 block">
              Password
            </span>
            <div className="relative">
              <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-9 py-2.5 text-sm text-slate-100 font-mono placeholder:text-slate-700 focus:outline-none focus:border-amber-500/60 focus:ring-1 focus:ring-amber-500/30 transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowPwd(v => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                tabIndex={-1}
              >
                {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </label>

          {error && (
            <div className="mb-4 px-3 py-2 bg-rose-950/50 border border-rose-800/50 rounded-lg text-[11px] text-rose-200 leading-relaxed">
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-slate-950 font-bold text-sm shadow-lg shadow-amber-900/40 hover:from-amber-400 hover:to-amber-500 active:scale-[0.98] transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : null}
            {loading ? 'Memverifikasi...' : 'Masuk'}
          </button>

          {/* Hint */}
          <details className="mt-4">
            <summary className="text-[10px] text-slate-600 hover:text-slate-400 cursor-pointer list-none">
              Akun default + setup user baru
            </summary>
            <div className="mt-2 px-3 py-2 bg-slate-950/60 border border-slate-800 rounded-lg text-[10px] text-slate-500 leading-relaxed space-y-1">
              <p><span className="text-amber-400 font-semibold">Default admin</span>: <span className="font-mono text-slate-300">rey666</span> · password sudah di-set.</p>
              <p>User baru: registrasi multi-user via Supabase Auth — dijadwalkan phase 2. Untuk sekarang single-user mode.</p>
            </div>
          </details>
        </form>

        <p className="text-center text-[10px] text-slate-600 mt-5">
          v1.0 · personal use only · {new Date().getFullYear()}
        </p>
      </div>
    </main>
  )
}

/** Subtle animated candlesticks for the login background. Pure CSS, no canvas. */
function CandlestickBackdrop() {
  // Predefined candle positions (deterministic, won't hydrate-mismatch)
  const candles = [
    { x:  5,  y: 60, h: 24, kind: 'green' },
    { x: 12,  y: 50, h: 36, kind: 'red'   },
    { x: 19,  y: 55, h: 28, kind: 'green' },
    { x: 26,  y: 45, h: 40, kind: 'green' },
    { x: 33,  y: 50, h: 30, kind: 'red'   },
    { x: 40,  y: 40, h: 50, kind: 'green' },
    { x: 47,  y: 55, h: 25, kind: 'red'   },
    { x: 54,  y: 35, h: 55, kind: 'green' },
    { x: 61,  y: 45, h: 35, kind: 'green' },
    { x: 68,  y: 50, h: 28, kind: 'red'   },
    { x: 75,  y: 38, h: 48, kind: 'green' },
    { x: 82,  y: 50, h: 30, kind: 'red'   },
    { x: 89,  y: 40, h: 45, kind: 'green' },
  ]
  return (
    <svg viewBox="0 0 100 200" preserveAspectRatio="xMidYMid slice" className="w-full h-full">
      {/* trend line */}
      <path
        d="M 0 130 Q 25 120, 40 100 T 75 60 L 100 50"
        fill="none"
        stroke="rgba(251,191,36,0.3)"
        strokeWidth={0.4}
        strokeDasharray="1,1"
      />
      {candles.map((c, i) => {
        const fill = c.kind === 'green' ? '#22c55e' : '#f43f5e'
        const opacity = 0.35
        return (
          <g key={i}>
            <line x1={c.x} y1={c.y - 4} x2={c.x} y2={c.y + c.h + 4}
                  stroke={fill} strokeWidth={0.3} opacity={opacity} />
            <rect x={c.x - 1.5} y={c.y} width={3} height={c.h}
                  fill={fill} opacity={opacity} />
          </g>
        )
      })}
    </svg>
  )
}
