'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, Briefcase, Loader2, AlertTriangle, Check, X } from 'lucide-react'

/**
 * Portfolio data management page.
 *
 * Two destructive actions:
 *   1. "Tutup semua OPEN"  → POST /api/portfolio/reset {scope:'open'}
 *      Marks every active trade as MANUAL close with pnl_r=0. History
 *      preserved.
 *   2. "Hapus SEMUA history" → POST /api/portfolio/reset {scope:'all'}
 *      Hard-deletes every active_trades row for this user. Clean slate.
 *
 * Both require explicit native confirm() + POST to backend. Used after
 * code changes (BEP fix, new pipeline) when user wants reproducible
 * stats from the new logic onward.
 */
export default function PortfolioSettingsPage() {
  const router = useRouter()
  const [busy,    setBusy]    = useState<null | 'open' | 'all'>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const reset = async (scope: 'open' | 'all') => {
    const msg = scope === 'all'
      ? 'Hapus SEMUA trade history (open + closed)? Tidak bisa di-undo.'
      : 'Tutup semua trade yang masih OPEN sebagai MANUAL close (pnl=0)?'
    if (!confirm(msg)) return
    setBusy(scope)
    setMessage(null)
    try {
      const r = await fetch('/api/portfolio/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok || !j.ok) {
        setMessage({ kind: 'err', text: j.error || `HTTP ${r.status}` })
      } else {
        const n = scope === 'all' ? (j.deleted ?? 0) : (j.closed ?? 0)
        const verb = scope === 'all' ? 'di-hapus' : 'di-tutup'
        setMessage({ kind: 'ok', text: `${n} trade ${verb}.` })
        router.refresh()
      }
    } catch (e) {
      setMessage({ kind: 'err', text: String(e) })
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-emerald-700/30 border border-emerald-600/30 flex items-center justify-center">
          <Briefcase size={16} className="text-emerald-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Manajemen Portfolio</h1>
          <p className="text-[11px] text-slate-500">Reset open trades / hapus history.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Warning banner */}
        <div className="bg-amber-950/30 border border-amber-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed flex gap-2">
          <AlertTriangle size={14} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-amber-100 font-semibold mb-0.5">Action destruktif</p>
            <p className="text-amber-200/80">
              Reset trade history mengubah data Supabase langsung. Pakai cuma kalau lo benar-benar mau clean slate
              (e.g. setelah update logic, mulai paper test ulang).
            </p>
          </div>
        </div>

        {/* Tutup semua OPEN */}
        <section>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
            Tutup semua OPEN trades
          </p>
          <div className="bg-slate-800/40 border border-slate-800 rounded-2xl p-3.5">
            <p className="text-[11px] text-slate-400 leading-relaxed mb-3">
              Mark setiap trade dengan status OPEN sebagai <span className="text-slate-200 font-semibold">MANUAL close</span>.
              Exit price = spot terkini, pnl_r = 0 (gak ngaruh stats).
              Berguna kalau lo mau bersihin trade lama tanpa hapus history.
            </p>
            <button
              onClick={() => reset('open')}
              disabled={busy !== null}
              className="w-full py-2.5 rounded-xl bg-amber-700/20 hover:bg-amber-700/40 border border-amber-700/40 text-amber-200 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-50 transition-colors"
            >
              {busy === 'open' ? <Loader2 size={14} className="animate-spin" /> : null}
              {busy === 'open' ? 'Menutup...' : 'Tutup semua OPEN trades'}
            </button>
          </div>
        </section>

        {/* Hapus SEMUA */}
        <section>
          <p className="text-[10px] font-semibold text-rose-400 uppercase tracking-widest mb-1.5 px-2">
            Danger zone
          </p>
          <div className="bg-rose-950/20 border border-rose-800/30 rounded-2xl p-3.5">
            <p className="text-[11px] text-slate-400 leading-relaxed mb-3">
              Hard-delete <span className="text-rose-200 font-semibold">SEMUA</span> active_trades row (open + closed).
              Total return, win rate, breakdown per kategori — semua reset ke 0.
              Tidak bisa di-undo. Pakai untuk fresh start setelah code change major.
            </p>
            <button
              onClick={() => reset('all')}
              disabled={busy !== null}
              className="w-full py-2.5 rounded-xl bg-rose-900/30 hover:bg-rose-900/60 border border-rose-800/50 text-rose-200 text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-50 transition-colors"
            >
              {busy === 'all' ? <Loader2 size={14} className="animate-spin" /> : null}
              {busy === 'all' ? 'Menghapus...' : 'Hapus SEMUA history'}
            </button>
          </div>
        </section>

        {/* Status message */}
        {message && (
          <div className={`px-3 py-2 rounded-lg text-[11px] leading-relaxed border flex items-start gap-2 ${
            message.kind === 'ok'
              ? 'bg-emerald-950/40 text-emerald-200 border-emerald-800/40'
              : 'bg-rose-950/40 text-rose-200 border-rose-800/40'
          }`}>
            {message.kind === 'ok' ? <Check size={12} className="shrink-0 mt-0.5" /> : <X size={12} className="shrink-0 mt-0.5" />}
            <span>{message.text}</span>
          </div>
        )}

        <Link
          href="/portfolio"
          className="block text-center text-[11px] text-sky-300 hover:text-sky-200 py-2"
        >
          ← Kembali ke Portfolio
        </Link>
      </div>
    </main>
  )
}
