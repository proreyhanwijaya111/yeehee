import type { Intermarket, COT } from '@/lib/types'
import { macroBiasLabel, cotLabel } from '@/lib/utils'

interface Props {
  intermarket: Intermarket
  cot:         COT
}

export default function MacroSnapshot({ intermarket, cot }: Props) {
  const { score, components: c } = intermarket
  const bias = macroBiasLabel(score)
  const cotInfo = cotLabel(cot?.z ?? null)

  const items = [
    {
      label: 'Bias Makro',
      value: bias.label,
      color: bias.color,
      tip:   'Skor gabungan DXY + US10Y + VIX + SPX',
    },
    {
      label: 'DXY',
      value: (c.dxy >= 0 ? '+' : '') + c.dxy.toFixed(2),
      color: c.dxy < 0 ? '#22c55e' : '#ef4444',
      tip:   'DXY naik = USD kuat = emas turun',
    },
    {
      label: 'US10Y',
      value: (c.us10y >= 0 ? '+' : '') + c.us10y.toFixed(2),
      color: c.us10y < 0 ? '#22c55e' : '#ef4444',
      tip:   'Yield naik = emas turun (korelasi negatif)',
    },
    {
      label: 'VIX',
      value: (c.vix >= 0 ? '+' : '') + c.vix.toFixed(2),
      color: c.vix > 0 ? '#22c55e' : '#94a3b8',
      tip:   'VIX tinggi = pasar takut = emas safe haven',
    },
    {
      label: 'COT',
      value: cotInfo.label.split('(')[0].trim(),
      color: cotInfo.color,
      tip:   'Posisi trader besar di CFTC',
    },
  ]

  return (
    <div className="bg-slate-800/60 rounded-2xl p-4 border border-slate-700/50 card-shadow">
      <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">
        📊 Kondisi Pasar
      </p>
      <div className="grid grid-cols-2 gap-2">
        {items.map(({ label, value, color, tip }) => (
          <div
            key={label}
            title={tip}
            className="bg-slate-700/30 rounded-xl px-3 py-2"
          >
            <p className="text-[10px] text-slate-400 uppercase tracking-wide">{label}</p>
            <p className="text-sm font-bold mt-0.5 truncate" style={{ color }}>
              {value}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
