import { AlertCircle, AlertTriangle } from 'lucide-react'
import type { NewsEvent } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  type:   'blackout' | 'warning'
  event:  NewsEvent | null
}

export default function NewsAlert({ type, event }: Props) {
  if (!event) return null

  const isBlackout = type === 'blackout'

  // Parse time, convert to WIB (+7)
  let timeStr = event.when_utc
  try {
    const t = new Date(event.when_utc)
    const wib = new Date(t.getTime() + 7 * 3600_000)
    timeStr = wib.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) + ' WIB'
  } catch { /* leave as-is */ }

  return (
    <div className={cn(
      'flex items-start gap-2.5 rounded-2xl px-4 py-3 text-sm font-medium',
      isBlackout
        ? 'bg-red-950/80 border border-red-500/50 text-red-200'
        : 'bg-amber-950/60 border border-amber-500/40 text-amber-200',
    )}>
      {isBlackout
        ? <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
        : <AlertTriangle size={16} className="text-amber-400 mt-0.5 shrink-0" />
      }
      <div className="min-w-0">
        <p className="font-semibold">
          {isBlackout ? '🚨 BLACKOUT NEWS' : '⚠️ Berita High Impact Segera'}
        </p>
        <p className="text-xs opacity-80 mt-0.5 truncate">
          {event.title} ({event.currency}) · {timeStr}
          {isBlackout && ' · Engine auto-SKIP entry'}
        </p>
      </div>
    </div>
  )
}
