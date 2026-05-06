'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { User, LogOut, Loader2 } from 'lucide-react'

/** Header card shown at top of /more — displays current user + logout. */
export default function UserHeader() {
  const router = useRouter()
  const [username, setUsername] = useState<string | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [busy,     setBusy]     = useState(false)

  useEffect(() => {
    fetch('/api/auth/me', { cache: 'no-store' })
      .then(r => r.json())
      .then(j => { if (j.ok && j.user) setUsername(j.user.username) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleLogout = async () => {
    if (!confirm('Logout dari yeehee? Lo perlu login ulang.')) return
    setBusy(true)
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
      router.replace('/login')
    } catch (e) {
      alert(`Logout error: ${String(e)}`)
      setBusy(false)
    }
  }

  return (
    <section>
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
        Akun
      </p>
      <div className="bg-gradient-to-br from-amber-900/20 to-slate-800/40 rounded-2xl border border-amber-700/30 px-3.5 py-3 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center shrink-0 shadow-lg shadow-amber-900/30">
          <User size={16} className="text-slate-950" strokeWidth={2.5} />
        </div>
        <div className="flex-1 min-w-0">
          {loading ? (
            <p className="text-xs text-slate-500">Memuat...</p>
          ) : username ? (
            <>
              <p className="text-sm font-bold text-slate-100">@{username}</p>
              <p className="text-[10px] text-slate-500">Single-user mode · admin</p>
            </>
          ) : (
            <p className="text-xs text-amber-300">Tidak terdeteksi — refresh halaman.</p>
          )}
        </div>
        {username && (
          <button
            onClick={handleLogout}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/40 border border-slate-700 hover:border-rose-700/50 text-[11px] text-slate-300 hover:text-rose-200 transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {busy ? <Loader2 size={11} className="animate-spin" /> : <LogOut size={11} />}
            Logout
          </button>
        )}
      </div>
    </section>
  )
}
