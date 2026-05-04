'use client'
import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Send, Check, X, Loader2 } from 'lucide-react'

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

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

  const handleSave = async () => {
    setSaving(true); setSaveMsg('')
    try {
      const r = await fetch(`${API}/api/config/telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, chat_id: chatId }),
      })
      if (!r.ok) throw new Error(await r.text())
      setSaveMsg('Disimpan. Daemon akan auto-pickup di refresh berikutnya.')
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
        {/* Step 1 */}
        <Group title="Langkah 1 - buat bot Telegram">
          <div className="px-3.5 py-3 text-[11px] text-slate-400 leading-relaxed">
            <ol className="list-decimal pl-4 space-y-1">
              <li>Buka Telegram, cari <strong className="text-slate-200">@BotFather</strong></li>
              <li>Ketik <code className="bg-slate-900/60 px-1.5 py-0.5 rounded font-mono">/newbot</code></li>
              <li>Ikuti petunjuk → dapatkan <strong className="text-slate-200">Token</strong></li>
              <li>Buka bot lo → klik <strong className="text-slate-200">Start</strong></li>
            </ol>
          </div>
        </Group>

        {/* Step 2 */}
        <Group title="Langkah 2 - masukkan kredensial">
          <div className="px-3.5 py-3 space-y-3">
            <div className="bg-slate-900/40 rounded-lg px-3 py-2 text-[11px] text-slate-500 leading-relaxed border border-slate-800">
              <p className="font-semibold text-slate-300 mb-1">Cara dapatkan Chat ID:</p>
              <p>Buka <code className="font-mono break-all">api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code></p>
              <p className="mt-1">Cari <code className="font-mono">&quot;id&quot;:</code> di dalam <code className="font-mono">&quot;chat&quot;</code></p>
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
