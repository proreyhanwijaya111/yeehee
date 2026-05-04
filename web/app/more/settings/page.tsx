'use client'
import { useState } from 'react'
import { CheckCircle, XCircle, Send } from 'lucide-react'

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
      text: '✅ yeehee test — koneksi OK! Siap menerima sinyal emas 🪙',
    }),
  })
  const d = await r.json()
  if (!d.ok) throw new Error(d.description ?? 'Gagal kirim pesan')
  return d
}

export default function SettingsPage() {
  const [token,     setToken]     = useState('')
  const [chatId,    setChatId]    = useState('')
  const [tokStatus, setTokStatus] = useState<'idle'|'ok'|'err'>('idle')
  const [tokMsg,    setTokMsg]    = useState('')
  const [msgStatus, setMsgStatus] = useState<'idle'|'ok'|'err'>('idle')
  const [msgText,   setMsgText]   = useState('')
  const [saving,    setSaving]    = useState(false)
  const [saveMsg,   setSaveMsg]   = useState('')

  const handleVerify = async () => {
    setTokStatus('idle')
    setTokMsg('')
    try {
      const info = await verifyToken(token)
      setTokStatus('ok')
      setTokMsg(`✅ @${info.username} (${info.first_name})`)
    } catch (e: unknown) {
      setTokStatus('err')
      setTokMsg(e instanceof Error ? e.message : 'Error')
    }
  }

  const handleSendTest = async () => {
    setMsgStatus('idle')
    setMsgText('')
    try {
      await sendTest(token, chatId)
      setMsgStatus('ok')
      setMsgText('✅ Pesan terkirim! Cek Telegram lo.')
    } catch (e: unknown) {
      setMsgStatus('err')
      setMsgText(e instanceof Error ? e.message : 'Error')
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      // Call backend to save to .env (endpoint tersedia di FastAPI)
      const r = await fetch(`${API}/api/config/telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, chat_id: chatId }),
      })
      if (!r.ok) throw new Error(await r.text())
      setSaveMsg('✅ Disimpan! Restart bot untuk aktif.')
    } catch (e: unknown) {
      setSaveMsg(`❌ ${e instanceof Error ? e.message : 'Gagal simpan'}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-4 animate-fade-in">
      <h1 className="text-lg font-black text-slate-100">📱 Setup Telegram</h1>
      <p className="text-xs text-slate-400">Ikuti 3 langkah ini untuk terima sinyal di HP via Telegram.</p>

      {/* Step 1 */}
      <StepCard step={1} title="Buat bot Telegram">
        <ol className="text-xs text-slate-300 space-y-1.5 leading-relaxed">
          <li>1. Buka Telegram → cari <strong>@BotFather</strong></li>
          <li>2. Ketik <code className="bg-slate-700 px-1 rounded">/newbot</code></li>
          <li>3. Ikuti petunjuk → dapatkan <strong>Token</strong></li>
          <li>4. Buka bot lo → klik <strong>Start</strong></li>
        </ol>
      </StepCard>

      {/* Step 2 */}
      <StepCard step={2} title="Masukkan Token & Chat ID">
        <div className="space-y-3">
          <div className="text-xs text-slate-400 bg-slate-700/30 rounded-xl px-3 py-2.5 leading-relaxed">
            <p className="font-semibold mb-1">Cara dapatkan Chat ID:</p>
            <p>Buka: <code className="break-all">api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code></p>
            <p className="mt-1">Cari <code>&quot;id&quot;:</code> di dalam bagian <code>&quot;chat&quot;</code></p>
          </div>

          <input
            type="text"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="Bot Token: 1234567890:ABCdef..."
            className="w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500 font-mono"
          />

          <input
            type="text"
            value={chatId}
            onChange={e => setChatId(e.target.value)}
            placeholder="Chat ID: 123456789"
            className="w-full bg-slate-700/50 border border-slate-600 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500 font-mono"
          />

          <div className="flex gap-2">
            <button
              onClick={handleVerify}
              disabled={!token}
              className="flex-1 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-semibold rounded-xl transition-all touch-action disabled:opacity-40"
            >
              🔍 Verifikasi Token
            </button>
            <button
              onClick={handleSendTest}
              disabled={!token || !chatId}
              className="flex-1 py-2.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-semibold rounded-xl transition-all touch-action disabled:opacity-40 flex items-center justify-center gap-1"
            >
              <Send size={14} /> Test Kirim
            </button>
          </div>

          {tokMsg && (
            <p className={`text-xs ${tokStatus === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
              {tokMsg}
            </p>
          )}
          {msgText && (
            <p className={`text-xs ${msgStatus === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
              {msgText}
            </p>
          )}
        </div>
      </StepCard>

      {/* Step 3 */}
      <StepCard step={3} title="Simpan & Aktifkan">
        <button
          onClick={handleSave}
          disabled={!token || !chatId || saving}
          className="w-full py-3 bg-green-700 hover:bg-green-600 active:bg-green-800 text-white font-bold rounded-xl transition-all touch-action disabled:opacity-40"
        >
          {saving ? 'Menyimpan...' : '💾 Simpan ke Konfigurasi'}
        </button>
        {saveMsg && (
          <p className={`text-xs mt-2 ${saveMsg.startsWith('✅') ? 'text-green-400' : 'text-red-400'}`}>
            {saveMsg}
          </p>
        )}
        <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
          Setelah disimpan, restart backend dengan <code className="bg-slate-700 px-1 rounded">run.bat bot</code>
        </p>
      </StepCard>

      {/* Bot commands */}
      <div className="bg-slate-800/60 rounded-2xl border border-slate-700/50 p-4">
        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">
          Perintah Bot
        </p>
        {[
          ['/signal',  'Sinyal terbaru (3 style)'],
          ['/risk',    'Hitung ukuran posisi'],
          ['/news',    'Berita high-impact hari ini'],
          ['/regime',  'Kondisi pasar sekarang'],
          ['/debate',  'Hasil debat 4 AI agent'],
          ['/strong',  'Hanya sinyal STRONG'],
        ].map(([cmd, desc]) => (
          <div key={cmd} className="flex items-start gap-2 py-1.5 border-b border-slate-700/30 last:border-0">
            <code className="text-sky-400 text-xs font-mono w-16 shrink-0">{cmd}</code>
            <p className="text-xs text-slate-400">{desc}</p>
          </div>
        ))}
      </div>
    </main>
  )
}

function StepCard({ step, title, children }: {
  step: number; title: string; children: React.ReactNode
}) {
  return (
    <div className="bg-slate-800/60 rounded-2xl border border-slate-700/50 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-6 h-6 rounded-full bg-sky-600 text-white text-xs font-bold flex items-center justify-center shrink-0">
          {step}
        </span>
        <p className="font-semibold text-sm text-slate-100">{title}</p>
      </div>
      {children}
    </div>
  )
}
