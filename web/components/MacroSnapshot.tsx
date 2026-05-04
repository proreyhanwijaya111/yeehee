import type { Intermarket, COT, IntermarketComponent } from '@/lib/types'
import { macroBiasLabel, cotLabel } from '@/lib/utils'

interface Props {
  intermarket: Intermarket
  cot:         COT
}

// Extract score number safely. Each component is {note, score, value} OR null OR undefined.
// Returns 0 kalau missing/invalid biar UI ga crash.
function score(c: IntermarketComponent | undefined | null): number {
  if (!c || typeof c !== 'object') return 0
  const v = c.score
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

export default function MacroSnapshot({ intermarket, cot }: Props) {
  const overallScore = typeof intermarket?.score === 'number' ? intermarket.score : 0
  const c   = intermarket?.components ?? {}
  const bias = macroBiasLabel(overallScore)
  const cotInfo = cotLabel(cot?.z ?? null)

  const dxy   = score(c.dxy)
  const us10y = score(c.us10y)
  const vix   = score(c.vix)

  const items = [
    {
      label: 'Bias Makro',
      value: bias.label,
      color: bias.color,
      tip:   'Skor gabungan DXY + US10Y + VIX + SPX',
    },
    {
      label: 'DXY',
      value: (dxy >= 0 ? '+' : '') + dxy.toFixed(2),
      color: dxy < 0 ? '#22c55e' : '#ef4444',
      tip:   c.dxy?.note || 'DXY naik = USD kuat = emas turun',
    },
    {
      label: 'US10Y',
      value: (us10y >= 0 ? '+' : '') + us10y.toFixed(2),
      color: us10y < 0 ? '#22c55e' : '#ef4444',
      tip:   c.us10y?.note || 'Yield naik = emas turun',
    },
    {
      label: 'VIX',
      value: (vix >= 0 ? '+' : '') + vix.toFixed(2),
      color: vix > 0 ? '#22c55e' : '#94a3b8',
      tip:   c.vix?.note || 'VIX tinggi = pasar takut = emas safe haven',
    },
    {
      label: 'COT',
      value: cotInfo.label.split('(')[0].trim(),
      color: cotInfo.color,
      tip:   'Posisi trader besar di CFTC',
    },
  ]

  return (
    <div className="bg-slate-800/40 rounded-2xl border border-slate-800 p-4">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-2">
        Kondisi pasar
      </p>
      <div className="grid grid-cols-2 gap-2">
        {items.map(({ label, value, color, tip }) => (
          <div
            key={label}
            title={tip}
            className="bg-slate-900/40 rounded-xl px-3 py-2 border border-slate-800/50"
          >
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</p>
            <p className="text-sm font-bold mt-0.5 truncate tabular-nums" style={{ color }}>
              {value}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
