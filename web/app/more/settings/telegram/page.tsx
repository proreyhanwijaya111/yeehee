'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Send, Check, X, Loader2 } from 'lucide-react'
import { getAppSettings, updateAppSettings } from '@/lib/settings'

async function verifyToken(token: string) {
  const r = await fetch(`https://api.telegram.org/bot${token}/getMe`)
  const d = await r.json()
  if (!d.ok) throw new Error(d.description ?? 'Token tidak valid')
  return d.result as { username: string; id: number; first_name: string }
}

async function sendTest(token: string, chatId: string) {
  const r = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: Number(chatId),
      text: '[OK] yeehee test - koneksi ok. Siap menerima sinyal emas.',
    }),
  })
  const d = await r.json()
  if (!d.ok) throw new Error(d.description ?? 'Gagal kirim pesan')
  return d
}

export default function TelegramSettingsPage() {
  const [token,     setToken]     = useState('')
  const [chatId,    setChatId]    = useState('')
  const [tokStatus, setTokStatus] = useState<'idle'|'ok'|'err'>('idle')
  const [tokMsg,    setTokMsg]    = useState('')
  const [msgStatus, setMsgStatus] = useState<'idle'|'ok'|'err'>('idle')
  const [msgText,   setMsgText]   = useState('')
  const [verifying, setVerifying] = useState(false)
  const [sending,   setSending]   = useState(false)
  const [saving,    setSaving]    = useState(false)
  const [saveMsg,   setSaveMsg]   = useState('')

  const handleVerify = async () => {
    setVerifying(true); setTokStatus('idle'); setTokMsg('')
    try {
      const info = await verifyToken(token)
      setTokStatus('ok')
      setTokMsg(`@${info.username} (${info.first_name})`)
    } catch (e: unknown) {
      setTokStatus('err'); setTokMsg(e instanceof Error ? e.message : 'Error')
    } finally { setVerifying(false) }
  }

  const handleSendTest = async () => {
    setSending(true); setMsgStatus('idle'); setMsgText('')
    try {
      await sendTest(token, chatId)
      setMsgStatus('ok')
      setMsgText('Pesan terkirim. Cek Telegram lo.')
    } catch (e: unknown) {
      setMsgStatus('err'); setMsgText(e instanceof Error ? e.message : 'Error')
    } finally { setSending(false) }
  }

  // Load existing values on mount
  useEffect(() => {
    getAppSettings().then(s => {
      if (s.telegram_bot_token) setToken(s.telegram_bot_token)
      if (s.telegram_chat_id) setChatId(s.telegram_chat_id)
    }).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true); setSaveMsg('')
    try {
      const ok = await updateAppSettings({
        telegram_bot_token: token,
        telegram_chat_id: chatId,
        enable_telegram_push: true,
      })
      if (!ok) throw new Error('Gagal save ke Supabase. Cek migration 009 sudah di-apply.')
      setSaveMsg('Disimpan ke Supabase. Daemon akan auto-pickup di cycle berikutnya.')
    } catch (e: unknown) {
      setSaveMsg(`Error: ${e instanceof Error ? e.message : 'Gagal simpan'}`)
    } finally { setSaving(false) }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="flex items-center gap-2 mb-4">
        <Link href="/more/settings" className="p-1.5 -ml-1.5 hover:bg-slate-800 rounded-lg" aria-label="Kembali">
          <ArrowLeft size={18} className="text-slate-400" />
        </Link>
        <div className="w-8 h-8 rounded-lg bg-emerald-700/30 border border-emerald-600/30 flex items-center justify-center">
          <Send size={16} className="text-emerald-300" />
        </div>
        <div>
          <h1 className="text-lg font-black text-slate-100 leading-tight">Telegram bot</h1>
          <p className="text-[11px] text-slate-500">Push notifikasi sinyal ke HP via Telegram.</p>
        </div>
      </header>

      <div className="space-y-5">
        {/* Tutorial intro */}
        <div className="bg-emerald-950/30 border border-emerald-800/40 rounded-xl p-3.5 text-[11px] leading-relaxed">
          <p className="text-emerald-100 font-semibold mb-1.5">Apa ini buat?</p>
          <p className="text-emerald-200/80 mb-2">
            Setup biar lo dapet <span className="font-bold">notifikasi instant di HP</span> via Telegram setiap kali sistem detect signal STRONG (confidence tinggi). Total waktu setup: ~3 menit. Gratis, ga perlu bayar Telegram apapun.
          </p>
          <p className="text-emerald-200/70">
            <span className="font-semibold">Yang lo butuh siapin</span>: HP dengan Telegram. Itu aja.
          </p>
        </div>

        {/* Step 1 */}
        <Group title="Langkah 1 · Bikin bot Telegram baru (di HP lo)">
          <div className="px-3.5 py-3 text-[11px] text-slate-400 leading-relaxed">
            <ol className="list-decimal pl-4 space-y-1.5">
              <li>Buka Telegram di HP, di search bar ketik <strong className="text-slate-200">@BotFather</strong> → pilih yang ada centang biru</li>
              <li>Tap <strong className="text-slate-200">START</strong> di chat BotFather</li>
              <li>Kirim pesan: <code className="bg-slate-900/60 px-1.5 py-0.5 rounded font-mono">/newbot</code></li>
              <li>BotFather minta nama: ketik bebas (e.g. <span className="font-mono">yeehee Signal</span>)</li>
              <li>BotFather minta username: ketik nama unik akhiran <span className="font-mono">_bot</span> (e.g. <span className="font-mono">yeehee_signal_bot</span>). Kalau nama udah dipake, coba variasi.</li>
              <li>BotFather kirim pesan dengan <span className="font-bold text-amber-300">token</span>. Format: <span className="font-mono text-[10px]">1234567890:AAH...</span> Copy itu.</li>
              <li>BotFather kasih link bot lo (<span className="font-mono">t.me/...</span>). Tap → buka chat dengan bot lo → tap <strong className="text-slate-200">START</strong>. (Penting! Tanpa start, bot ga bisa kirim ke lo.)</li>
            </ol>
          </div>
        </Group>

        {/* Step 2 */}
        <Group title="Langkah 2 · Dapetin Chat ID lo">
          <div className="px-3.5 py-3 space-y-3">
            <div className="bg-slate-900/40 rounded-lg px-3 py-2 text-[11px] text-slate-400 leading-relaxed border border-slate-800">
              <p className="font-semibold text-slate-200 mb-1.5">Cara paling mudah (lewat bot):</p>
              <ol className="list-decimal pl-4 space-y-1">
                <li>Di Telegram, search <strong className="text-slate-200">@userinfobot</strong></li>
                <li>Tap <strong className="text-slate-200">START</strong></li>
                <li>Bot reply dengan info lo, copy angka di field <code className="font-mono">Id:</code> (e.g. <span className="font-mono">123456789</span>)</li>
              </ol>

              <details className="mt-2">
                <summary className="text-slate-300 font-semibold cursor-pointer">Cara alternatif (lewat browser)</summary>
                <p className="mt-1 text-[10px]">Buka URL ini di browser, ganti <span className="font-mono">&lt;TOKEN&gt;</span> dengan token lo:</p>
                <p className="mt-1"><code className="font-mono break-all bg-slate-950 px-1.5 py-0.5 rounded">api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code></p>
                <p className="mt-1">Cari <code className="font-mono">&quot;id&quot;:</code> di dalam object <code className="font-mono">&quot;chat&quot;</code> (bukan "from"). Itu Chat ID lo.</p>
                <p className="mt-1 text-amber-400">Note: harus chat ke bot dulu (Step 1 #7) biar getUpdates ada hasil.</p>
              </details>
            </div>

            <Field label="Bot Token">
              <input
                type="text"
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="1234567890:ABCdef..."
                className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
              />
            </Field>

            <Field label="Chat ID">
              <input
                type="text"
                value={chatId}
                onChange={e => setChatId(e.target.value)}
                placeholder="123456789"
                className="w-full bg-slate-900/40 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-sky-500"
              />
            </Field>

            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={handleVerify}
                disabled={!token || verifying}
                className="py-2 bg-slate-800/80 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
              >
                {verifying ? <Loader2 size={12} className="animate-spin" /> : null}
                Verifikasi token
              </button>
              <button
                onClick={handleSendTest}
                disabled={!token || !chatId || sending}
                className="py-2 bg-slate-800/80 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition-colors disabled:opacity-40 flex items-center justify-center gap-1.5"
              >
                {sending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                Test kirim
              </button>
            </div>

            {tokMsg && (
              <Result status={tokStatus} text={tokMsg} />
            )}
            {msgText && (
              <Result status={msgStatus} text={msgText} />
            )}
          </div>
        </Group>

        {/* Step 3 */}
        <Group title="Langkah 3 - simpan">
          <div className="px-3.5 py-3">
            <button
              onClick={handleSave}
              disabled={!token || !chatId || saving}
              className="w-full py-2.5 bg-emerald-700/80 hover:bg-emerald-600 active:bg-emerald-800 text-white font-semibold text-sm rounded-lg transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              Simpan ke konfigurasi
            </button>
            {saveMsg && (
              <p className={`text-[11px] mt-2 ${saveMsg.startsWith('Error') ? 'text-rose-400' : 'text-emerald-400'}`}>
                {saveMsg}
              </p>
            )}
          </div>
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] text-slate-500 uppercase tracking-wide font-semibold">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function Result({ status, text }: { status: 'idle'|'ok'|'err'; text: string }) {
  if (status === 'idle') return null
  return (
    <div className={`flex items-start gap-2 px-2.5 py-2 rounded-lg text-[11px] ${
      status === 'ok' ? 'bg-emerald-950/30 text-emerald-300' : 'bg-rose-950/30 text-rose-300'
    }`}>
      {status === 'ok' ? <Check size={13} className="shrink-0 mt-0.5" /> : <X size={13} className="shrink-0 mt-0.5" />}
      <span>{text}</span>
    </div>
  )
}
