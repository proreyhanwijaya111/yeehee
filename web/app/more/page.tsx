import Link from 'next/link'
import { FlaskConical, Settings, BookOpen, Newspaper } from 'lucide-react'

const MENU = [
  {
    href:  '/news',
    icon:  Newspaper,
    label: 'Berita Ekonomi',
    desc:  'Kalender event high-impact USD & XAU',
    color: 'text-amber-400',
    bg:    'bg-amber-950/40 border-amber-700/40',
  },
  {
    href:  '/more/backtest',
    icon:  FlaskConical,
    label: 'Test Strategi',
    desc:  'Backtest + 10k Monte Carlo simulasi',
    color: 'text-sky-400',
    bg:    'bg-sky-950/40 border-sky-700/40',
  },
  {
    href:  '/more/settings',
    icon:  Settings,
    label: 'Setup Telegram',
    desc:  'Terima sinyal di HP via Telegram bot',
    color: 'text-green-400',
    bg:    'bg-green-950/40 border-green-700/40',
  },
  {
    href:  '/more/glossary',
    icon:  BookOpen,
    label: 'Glosarium',
    desc:  '46 istilah trading dalam Bahasa Indonesia',
    color: 'text-purple-400',
    bg:    'bg-purple-950/40 border-purple-700/40',
  },
]

export default function MorePage() {
  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-3 animate-fade-in">
      <h1 className="text-lg font-black text-slate-100">☰ Lainnya</h1>

      {MENU.map(({ href, icon: Icon, label, desc, color, bg }) => (
        <Link
          key={href}
          href={href}
          className={`flex items-center gap-4 rounded-2xl border px-4 py-4 transition-all active:scale-[0.98] touch-action ${bg}`}
        >
          <div className={`shrink-0 p-2 rounded-xl bg-black/20`}>
            <Icon size={22} className={color} />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-slate-100">{label}</p>
            <p className="text-xs text-slate-400 mt-0.5 truncate">{desc}</p>
          </div>
          <span className="ml-auto text-slate-600">›</span>
        </Link>
      ))}

      <div className="mt-4 bg-slate-800/40 rounded-2xl border border-slate-700/40 p-4 text-center">
        <p className="text-xs text-slate-500">yeehee XAU/USD Signal Platform</p>
        <p className="text-xs text-slate-600 mt-0.5">Hanya untuk penggunaan pribadi</p>
      </div>
    </main>
  )
}
