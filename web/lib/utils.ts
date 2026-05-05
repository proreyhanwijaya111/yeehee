import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { TradeAction, SignalStrength, TradingStyle, RiskProfile } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ── Labels Bahasa Indonesia ────────────────────────────────────────────────────

export const ACTION_LABEL: Record<TradeAction, string> = {
  LONG:  '🟢 BELI',
  SHORT: '🔴 JUAL',
  FLAT:  '⚪ TUNGGU',
}

export const ACTION_COLOR: Record<TradeAction, string> = {
  LONG:  '#16a34a',
  SHORT: '#dc2626',
  FLAT:  '#475569',
}

export const STRENGTH_LABEL: Record<SignalStrength, string> = {
  STRONG:       '🔥 KUAT',
  NEWS_STRONG:  '📰🔥 NEWS KUAT',
  NORMAL:       '✅ NORMAL',
  WEAK:         '💭 LEMAH',
  FLAT:         '⏸ TUNGGU',
}

export const STRENGTH_COLOR: Record<SignalStrength, string> = {
  STRONG:       '#16a34a',
  NEWS_STRONG:  '#9333ea',
  NORMAL:       '#0ea5e9',
  WEAK:         '#737373',
  FLAT:         '#475569',
}

export const STRENGTH_DESC: Record<SignalStrength, string> = {
  STRONG:       'Sinyal premium — semua faktor align. Eksekusi paling confident.',
  NEWS_STRONG:  'Sinyal post-news dengan arah jelas. High momentum.',
  NORMAL:       'Sinyal valid, confidence cukup. Eksekusi dengan disiplin.',
  WEAK:         'Confidence rendah. Pertimbangkan skip atau pakai size lebih kecil.',
  FLAT:         'Belum ada konsensus. Tunggu setup yang lebih jelas.',
}

export const STYLE_LABEL: Record<TradingStyle, string> = {
  scalper:  '⚡ Scalper (M5)',
  intraday: '🎯 Intraday (M15)',
  swing:    '🌊 Swing (H4)',
}

export const REGIME_LABEL: Record<string, { label: string; desc: string }> = {
  trending_up: { label: '📈 Naik kuat',        desc: 'Tren naik. LONG ikut arus.' },
  trending_dn: { label: '📉 Turun kuat',        desc: 'Tren turun. SHORT ikut arus.' },
  ranging:     { label: '↔️ Sideways',          desc: 'Pasar nggak ada arah. Strategi trend kurang efektif.' },
  volatile:    { label: '⚡ Bergerak liar',     desc: 'Volatility tinggi tanpa arah. Hati-hati.' },
  quiet:       { label: '😴 Sepi (low vol)',    desc: 'Pasar diam. Tunggu volatility kembali.' },
}

export const SESSION_LABEL: Record<string, { label: string; desc: string }> = {
  asia:          { label: '🌏 Sesi Asia',       desc: 'Volatility rendah. Setup buat London.' },
  london:        { label: '🇬🇧 Sesi London',    desc: 'Volatility tinggi. Trend day terbentuk.' },
  ny:            { label: '🇺🇸 Sesi New York',  desc: 'Volatility tinggi. News US di sini.' },
  lon_ny_overlap:{ label: '🌐 Overlap Lon-NY',  desc: 'PEAK liquidity. Best untuk momentum.' },
  off_hours:     { label: '🌙 Off hours',        desc: 'Liquidity rendah. Hindari entry baru.' },
}

export const PROFILE_LABEL: Record<RiskProfile, { label: string; desc: string }> = {
  konservatif: { label: '🛡 Konservatif', desc: '0.5% risk · max 2% loss harian' },
  moderat:     { label: '⚖️ Moderat',     desc: '1% risk · max 4% loss harian (default)' },
  agresif:     { label: '🔥 Agresif',     desc: '2% risk · max 6% loss harian' },
  bebas:       { label: '⚠️ Bebas',       desc: '5% risk · max 20% loss harian (BAHAYA)' },
}

export const AGENT_LABEL: Record<string, string> = {
  TechnicalAnalyst: '📊 Analis Teknikal',
  MacroStrategist:  '🌍 Ahli Makro',
  OrderFlowReader:  '🔍 Pembaca Order Flow',
  DevilsAdvocate:   '😈 Devil\'s Advocate',
}

export function humanizeAgent(name: string): string {
  return AGENT_LABEL[name] ?? name
}

export function humanizeRegime(code: string) {
  return REGIME_LABEL[code] ?? { label: code.toUpperCase(), desc: '' }
}

export function humanizeSession(code: string) {
  return SESSION_LABEL[code] ?? { label: code.toUpperCase(), desc: '' }
}

export function macroBiasLabel(score: number): { label: string; color: string } {
  if (score >  0.5) return { label: 'Sangat bullish',  color: '#16a34a' }
  if (score >  0.2) return { label: 'Bullish',         color: '#16a34a' }
  if (score >  0.05)return { label: 'Sedikit bullish', color: '#22c55e' }
  if (score < -0.5) return { label: 'Sangat bearish',  color: '#dc2626' }
  if (score < -0.2) return { label: 'Bearish',         color: '#dc2626' }
  if (score < -0.05)return { label: 'Sedikit bearish', color: '#ef4444' }
  return { label: 'Netral', color: '#737373' }
}

export function cotLabel(z: number | null): { label: string; color: string } {
  if (z === null) return { label: 'Data N/A', color: '#737373' }
  if (z >  1.5) return { label: `Long extreme (z=${z.toFixed(1)})`,  color: '#dc2626' }
  if (z < -1.5) return { label: `Short extreme (z=${z.toFixed(1)})`, color: '#16a34a' }
  if (z >  0.8) return { label: `Long crowded (z=${z.toFixed(1)})`,  color: '#f59e0b' }
  if (z < -0.8) return { label: `Short crowded (z=${z.toFixed(1)})`, color: '#f59e0b' }
  return { label: `Normal (z=${z.toFixed(1)})`, color: '#737373' }
}

export function explainFlat(reasons: string[]): string {
  if (!reasons || reasons.length === 0) {
    return 'Belum ada konfirmasi cukup. Engine masih monitor.'
  }
  const first = reasons[0].toLowerCase()
  if (first.includes('confluence')) {
    return 'Belum waktunya entry — faktor pendukung belum cukup. Tunggu 4+ faktor sepakat.'
  }
  if (first.includes('insufficient data')) {
    return 'Data belum cukup. Tunggu beberapa candle lagi.'
  }
  if (first.includes('news blackout')) {
    return '🚨 Lagi blackout news. Engine auto-skip 30 mnt sebelum/sesudah event berdampak tinggi.'
  }
  return reasons[0]
}

// ── Number formatting ──────────────────────────────────────────────────────────

export function fmtPrice(v: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtPct(v: number, decimals = 0): string {
  return (v * 100).toFixed(decimals) + '%'
}

export function fmtUSD(v: number): string {
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

export function fmtR(v: number): string {
  return v.toFixed(1) + '×'
}

// ── Opsi B: trigger_reason → human readable Indonesian label ───────────────────
//
// Daemon writes machine-readable tags ('price_spike_up_0.42pct', 'ema9_21_bullish_cross', etc).
// UI shows user-friendly text. Returns { label, kind } where kind drives badge color.

export type TriggerKind = 'scheduled' | 'momentum' | 'cross' | 'volatility' | 'volume' | 'news' | 'manual' | 'unknown'

export function formatTriggerReason(reason?: string | null): { label: string; kind: TriggerKind } {
  if (!reason || reason === 'scheduled') {
    return { label: 'auto-refresh 5 menit', kind: 'scheduled' }
  }
  if (reason === 'manual') {
    return { label: 'manual refresh', kind: 'manual' }
  }
  if (reason.startsWith('price_spike_')) {
    // 'price_spike_up_0.42pct' → "spike harga ↑ 0.42%"
    const m = reason.match(/^price_spike_(up|down)_([\d.]+)pct$/)
    if (m) {
      const arrow = m[1] === 'up' ? '↑' : '↓'
      return { label: `spike harga ${arrow} ${m[2]}%`, kind: 'momentum' }
    }
    return { label: 'spike harga', kind: 'momentum' }
  }
  if (reason.startsWith('ema9_21_')) {
    if (reason.includes('bullish'))  return { label: 'EMA9 cross ke atas',   kind: 'cross' }
    if (reason.includes('bearish'))  return { label: 'EMA9 cross ke bawah',  kind: 'cross' }
    return { label: 'EMA cross', kind: 'cross' }
  }
  if (reason.startsWith('atr_explosion_')) {
    const m = reason.match(/^atr_explosion_([\d.]+)x$/)
    return { label: `volatilitas meledak ${m ? m[1] + 'x ATR' : ''}`.trim(), kind: 'volatility' }
  }
  if (reason.startsWith('volume_spike_')) {
    const m = reason.match(/^volume_spike_([\d.]+)x$/)
    return { label: `volume spike ${m ? m[1] + 'x' : ''}`.trim(), kind: 'volume' }
  }
  if (reason === 'blackout_exit') {
    return { label: 'pasca-news, blackout selesai', kind: 'news' }
  }
  return { label: reason, kind: 'unknown' }
}
