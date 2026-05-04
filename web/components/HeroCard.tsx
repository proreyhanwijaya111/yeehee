import type { SignalBundle } from '@/lib/types'
import {
  ACTION_LABEL, STRENGTH_LABEL, STRENGTH_DESC,
  humanizeRegime, humanizeSession, explainFlat, fmtPrice, fmtPct, fmtR,
  cn,
} from '@/lib/utils'

interface Props {
  bundle: SignalBundle
}

export default function HeroCard({ bundle }: Props) {
  const { final_action: action, signal_strength: strength, confidence } = bundle
  const strDesc = STRENGTH_DESC[strength]

  // Best non-flat signal for level display
  const bestSig = [bundle.intraday_signal, bundle.swing_signal, bundle.scalper_signal]
    .find(s => s?.side !== 'FLAT') ?? bundle.intraday_signal

  const regimeInfo  = humanizeRegime(bundle.regime)
  const sessionInfo = humanizeSession(bundle.session)

  const bgGradient =
    action === 'LONG'  ? 'from-green-800 via-green-700 to-green-600' :
    action === 'SHORT' ? 'from-red-800 via-red-700 to-red-600' :
                         'from-slate-800 via-slate-700 to-slate-700'

  const borderColor =
    action === 'LONG'  ? 'border-green-500/30' :
    action === 'SHORT' ? 'border-red-500/30' :
                         'border-slate-600/30'

  return (
    <div className={cn(
      'bg-gradient-to-br rounded-3xl p-5 border card-shadow-lg hero-live',
      bgGradient, borderColor,
    )}>
      <div className="flex justify-between items-start gap-3">
        {/* Left: action */}
        <div className="flex-1 min-w-0">
          <p className="text-4xl font-black tracking-tight leading-none">
            {ACTION_LABEL[action]}
          </p>
          <p className="mt-1.5 text-sm font-semibold opacity-90">
            {STRENGTH_LABEL[strength]}
          </p>
          <p className="mt-0.5 text-xs opacity-70">
            {strDesc}
          </p>

          {/* Confidence bar */}
          <div className="mt-3 flex items-center gap-2">
            <div className="flex-1 bg-black/20 rounded-full h-1.5">
              <div
                className="h-1.5 rounded-full bg-white/80 transition-all duration-700"
                style={{ width: `${(confidence * 100).toFixed(0)}%` }}
              />
            </div>
            <span className="text-xs font-bold opacity-90 tabular-nums whitespace-nowrap">
              {fmtPct(confidence)} yakin
            </span>
          </div>

          {/* Context tags */}
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <span className="text-[11px] bg-black/20 px-2 py-0.5 rounded-full opacity-80">
              {regimeInfo.label}
            </span>
            <span className="text-[11px] bg-black/20 px-2 py-0.5 rounded-full opacity-80">
              {sessionInfo.label}
            </span>
          </div>

          {/* FLAT explanation */}
          {action === 'FLAT' && (
            <p className="mt-3 text-xs opacity-70 bg-black/15 rounded-xl px-3 py-2 leading-relaxed">
              {explainFlat(bundle.intraday_signal?.reasons ?? [])}
            </p>
          )}
        </div>

        {/* Right: price */}
        <div className="text-right shrink-0">
          <p className="text-[11px] opacity-60 font-medium uppercase tracking-wider">XAU/USD</p>
          <p className="text-2xl font-black tabular-nums leading-tight">
            ${fmtPrice(bundle.xau_price)}
          </p>
          <p className="text-[10px] opacity-50 mt-0.5">per troy oz</p>
        </div>
      </div>

      {/* Entry levels (jika ada sinyal aktif) */}
      {action !== 'FLAT' && bestSig && bestSig.side !== 'FLAT' && (
        <div className="mt-4 grid grid-cols-4 gap-2 bg-black/15 rounded-2xl p-3">
          {[
            { label: 'Entry',  value: fmtPrice(bestSig.entry) },
            { label: 'SL',     value: fmtPrice(bestSig.sl) },
            { label: 'TP1',    value: fmtPrice(bestSig.tp1) },
            { label: 'R:R',    value: fmtR(bestSig.rr_to_tp1) },
          ].map(({ label, value }) => (
            <div key={label} className="text-center">
              <p className="text-[10px] opacity-60 uppercase tracking-wide">{label}</p>
              <p className="text-xs font-bold tabular-nums mt-0.5">{value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
