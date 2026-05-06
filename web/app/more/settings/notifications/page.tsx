'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Bell, BellOff, Check, X, Loader2, Send, AlertTriangle } from 'lucide-react'

/**
 * Push notification settings page.
 *
 * Flow:
 *   1. Check Notification.permission (default | granted | denied)
 *   2. If granted, check if pushManager has an existing subscription
 *   3. Toggle button:
 *      - off → ask permission → subscribe via SW → POST /api/push/subscribe
 *      - on  → unsubscribe locally + POST /api/push/unsubscribe
 *   4. Test button: POST /api/push/test → daemon sends a sample push
 */

type Status = 'unknown' | 'unsupported' | 'denied' | 'inactive' | 'active'

function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64  = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  // Allocate a non-shared ArrayBuffer explicitly so TS DOM types are happy
  const buf = new ArrayBuffer(raw.length)
  const view = new Uint8Array(buf)
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i)
  return buf
}

export default function NotificationsPage() {
  const [status,   setStatus]   = useState<Status>('unknown')
  const [busy,     setBusy]     = useState(false)
  const [testing,  setTesting]  = useState(false)
  const [message,  setMessage]  = useState<{ kind: 'ok' | 'err' | 'info'; text: string } | null>(null)
  const [endpoint, setEndpoint] = useState<string | null>(null)

  const refresh = async () => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator) || !('PushManager' in window)) {
      setStatus('unsupported')
      return
    }
    if (Notification.permission === 'denied') {
      setStatus('denied')
      return
    }
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        setStatus('active')
        setEndpoint(sub.endpoint)
      } else {
        setStatus('inactive')
        setEndpoint(null)
      }
    } catch {
      setStatus('inactive')
    }
  }

  useEffect(() => { refresh() }, [])

  const handleEnable = async () => {
    setBusy(true)
    setMessage(null)
    try {
      // 1. Request permission
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') {
        setMessage({ kind: 'err', text: 'Permission ditolak. Aktifkan via Settings → Apps → yeehee → Notifications.' })
        return
      }

      // 2. Get VAPID public key from backend
      const k = await fetch('/api/push/vapid-key').then(r => r.json())
      if (!k.ok || !k.publicKey) {
        setMessage({ kind: 'err', text: k.error || 'VAPID key tidak tersedia. Set NEXT_PUBLIC_VAPID_PUBLIC_KEY di Vercel env.' })
        return
      }

      // 3. Subscribe via service worker
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(k.publicKey),
      })

      // 4. Send to backend
      const subJson = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } }
      const res = await fetch('/api/push/subscribe', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          endpoint: subJson.endpoint,
          keys:     subJson.keys,
          label:    navigator.userAgent.slice(0, 80),
        }),
      })
      const j = await res.json()
      if (!res.ok || !j.ok) {
        setMessage({ kind: 'err', text: j.error || 'Gagal save subscription ke server.' })
        return
      }
      setMessage({ kind: 'ok', text: 'Notifikasi aktif. Lo bakal dapet push saat ada STRONG signal.' })
      await refresh()
    } catch (e) {
      setMessage({ kind: 'err', text: `Error: ${String(e).slice(0, 200)}` })
    } finally {
      setBusy(false)
    }
  }

  const handleDisable = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        const ep = sub.endpoint
        await sub.unsubscribe()
        await fetch('/api/push/unsubscribe', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ endpoint: ep }),
        })
      }
      setMessage({ kind: 'ok', text: 'Notifikasi dimatikan.' })
      await refresh()
    } catch (e) {
      setMessage({ kind: 'err', text: `Error: ${String(e).slice(0, 200)}` })
    } finally {
      setBusy(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setMessage(null)
    try {
      const r = await fetch('/api/push/test', { method: 'POST' })
      const j = await r.json()
      if (!r.ok || !j.ok) {
        setMessage({ kind: 'err', text: j.error || `HTTP ${r.status}` })
      } else {
        setMessage({ kind: 'info', text: `Test push dikirim ke ${j.sent} device${j.failed > 0 ? ` · ${j.failed} gagal` : ''}. Cek notif HP.` })
      }
    } catch (e) {
      setMessage({ kind: 'err', text: `Error: ${String(e).slice(0, 200)}` })
    } finally {
      setTesting(false)
    }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-amber-700/30 border border-amber-600/30 flex items-center justify-center">
          <Bell size={16} className="text-amber-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Notifikasi push</h1>
          <p className="text-[11px] text-slate-500">Native HP notif saat ada STRONG signal — gak perlu buka app.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Status card */}
        <div className="bg-slate-800/40 rounded-2xl border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">Status</p>
            <StatusBadge status={status} />
          </div>

          {status === 'unsupported' && (
            <p className="text-[11px] text-amber-300/90 leading-relaxed">
              Browser ini gak support Web Push (mungkin in-app browser atau iOS Safari versi lama). Buka di Chrome/Brave/Firefox HP atau install dulu sebagai PWA.
            </p>
          )}

          {status === 'denied' && (
            <p className="text-[11px] text-rose-300/90 leading-relaxed">
              Notifikasi ditolak permanen. Buka <span className="font-semibold">Android Settings → Apps → yeehee → Notifications</span> → izinkan, lalu reload halaman.
            </p>
          )}

          {(status === 'inactive' || status === 'unknown') && (
            <button
              onClick={handleEnable}
              disabled={busy || status === 'unknown'}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-slate-950 font-bold text-sm shadow-lg shadow-amber-900/30 hover:from-amber-400 hover:to-amber-500 active:scale-[0.98] transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Bell size={16} />}
              {busy ? 'Mengaktifkan...' : 'Aktifkan notifikasi'}
            </button>
          )}

          {status === 'active' && (
            <div className="space-y-2">
              <button
                onClick={handleTest}
                disabled={testing || busy}
                className="w-full py-2.5 rounded-xl bg-amber-700/20 hover:bg-amber-700/30 border border-amber-700/40 text-amber-200 text-sm font-semibold disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {testing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                {testing ? 'Mengirim test...' : 'Kirim test push sekarang'}
              </button>
              <button
                onClick={handleDisable}
                disabled={busy || testing}
                className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-rose-900/30 border border-slate-700 hover:border-rose-700/40 text-slate-300 hover:text-rose-200 text-[12px] font-medium disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <BellOff size={14} />}
                {busy ? 'Mematikan...' : 'Matikan notifikasi'}
              </button>
              {endpoint && (
                <p className="text-[10px] text-slate-600 break-all font-mono mt-2">
                  Endpoint: {endpoint.slice(0, 60)}...
                </p>
              )}
            </div>
          )}

          {message && (
            <div className={`mt-3 px-3 py-2 rounded-lg text-[11px] leading-relaxed border flex items-start gap-2 ${
              message.kind === 'ok'  ? 'bg-emerald-950/40 text-emerald-200 border-emerald-800/40' :
              message.kind === 'err' ? 'bg-rose-950/40 text-rose-200 border-rose-800/40' :
                                       'bg-sky-950/40 text-sky-200 border-sky-800/40'
            }`}>
              {message.kind === 'ok'  && <Check size={12} className="shrink-0 mt-0.5" />}
              {message.kind === 'err' && <X size={12} className="shrink-0 mt-0.5" />}
              {message.kind === 'info'&& <AlertTriangle size={12} className="shrink-0 mt-0.5" />}
              <span>{message.text}</span>
            </div>
          )}
        </div>

        {/* How it works */}
        <details className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden">
          <summary className="px-4 py-3 cursor-pointer text-xs font-semibold text-slate-300 hover:bg-slate-800/40 select-none">
            Kapan notif dikirim?
          </summary>
          <div className="px-4 pb-3 pt-1 space-y-2 text-[11px] text-slate-500 leading-relaxed border-t border-slate-800/80">
            <p>Daemon kirim push otomatis saat:</p>
            <ul className="list-disc pl-4 space-y-1">
              <li>12-agent debate <span className="text-slate-300 font-semibold">STRONG</span> dengan confidence ≥ 65%</li>
              <li>ATAU RCS direction LONG/SHORT dengan confidence ≥ 70%</li>
            </ul>
            <p className="pt-1">Dedupe: gak push signal yang sama 2× dalam 30 menit.</p>
            <p className="text-amber-300">Kalo lo mau push lebih sering (e.g. confidence ≥ 55%), bilang gua — gua bisa relax threshold.</p>
          </div>
        </details>

        {/* Setup VAPID env (admin only) */}
        <details className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden">
          <summary className="px-4 py-3 cursor-pointer text-xs font-semibold text-slate-300 hover:bg-slate-800/40 select-none">
            Setup VAPID (admin only — sekali doang)
          </summary>
          <div className="px-4 pb-3 pt-1 space-y-2 text-[11px] text-slate-500 leading-relaxed border-t border-slate-800/80">
            <p>VAPID keys diperlukan untuk Web Push protocol. Sudah di-generate, tinggal isi di env:</p>
            <ol className="list-decimal pl-4 space-y-1">
              <li>Vercel dashboard → project yeehee → Settings → Environment Variables</li>
              <li>Tambah <span className="font-mono text-amber-300">NEXT_PUBLIC_VAPID_PUBLIC_KEY</span></li>
              <li>Tambah <span className="font-mono text-amber-300">VAPID_PRIVATE_KEY</span> (server-only)</li>
              <li>Tambah <span className="font-mono text-amber-300">VAPID_SUBJECT</span> = <span className="font-mono">mailto:lo@email.com</span></li>
              <li>Redeploy</li>
            </ol>
            <p>Di PC rumah .env juga set yang sama (daemon perlu untuk send push).</p>
          </div>
        </details>
      </div>
    </main>
  )
}

function StatusBadge({ status }: { status: Status }) {
  const cfg: Record<Status, { label: string; cls: string }> = {
    unknown:     { label: 'Memuat...',   cls: 'bg-slate-800 text-slate-400' },
    unsupported: { label: 'Unsupported', cls: 'bg-slate-800 text-slate-400' },
    denied:      { label: 'Ditolak',     cls: 'bg-rose-900/40 text-rose-300' },
    inactive:    { label: 'Belum aktif', cls: 'bg-slate-800 text-slate-400' },
    active:      { label: '✓ Aktif',     cls: 'bg-emerald-900/40 text-emerald-300' },
  }
  const c = cfg[status]
  return (
    <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${c.cls}`}>
      {c.label}
    </span>
  )
}
