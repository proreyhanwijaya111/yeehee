import Link from 'next/link'
import {
  Settings, Server, Brain, Cpu, Send, FlaskConical, BookOpen, Newspaper,
  Calculator, ChevronRight, Github, ExternalLink, Sparkles, Zap,
  type LucideIcon,
} from 'lucide-react'
import UserHeader from '@/components/UserHeader'

export const runtime = 'edge'

type Item = {
  href: string
  icon: LucideIcon
  label: string
  desc?: string
  badge?: string
  external?: boolean
}

type Section = {
  title: string
  items: Item[]
}

const SECTIONS: Section[] = [
  {
    title: 'Tools',
    items: [
      { href: '/calculator',         icon: Calculator,   label: 'Kalkulator posisi',  desc: 'Hitung lot size dari profile risk + level signal' },
      { href: '/more/backtest',      icon: FlaskConical, label: 'Test strategi',      desc: 'Backtest historis XAU + Monte Carlo' },
      { href: '/more/rcs-monitor',   icon: Sparkles,     label: 'RCS Composite',      desc: 'Indikator pamungkas — gabungan semua signal jadi satu', badge: 'v0.1' },
    ],
  },
  {
    title: 'Konten',
    items: [
      { href: '/news',           icon: Newspaper,    label: 'Berita ekonomi',     desc: 'Kalender event high-impact USD & XAU' },
      { href: '/more/glossary',  icon: BookOpen,     label: 'Glosarium',          desc: '46 istilah trading dalam Bahasa Indonesia' },
    ],
  },
  {
    title: 'Konfigurasi sistem',
    items: [
      { href: '/more/settings',          icon: Settings, label: 'Pengaturan',     desc: 'Provider, agent, daemon, telegram' },
      { href: '/more/settings/llm',      icon: Brain,    label: 'LLM Provider',   desc: 'API key & default model' },
      { href: '/more/settings/agents',   icon: Cpu,      label: '9 AI Agent',     desc: 'Pipeline + per-agent override' },
      { href: '/more/settings/daemon',   icon: Server,   label: 'Daemon worker',  desc: 'Generate script untuk PC rumah' },
      { href: '/more/settings/execution',icon: Zap,      label: 'Execution & EA', desc: 'Auto-trade MT5: risk, BEP, trailing, daily cap', badge: 'NEW' },
      { href: '/more/settings/telegram', icon: Send,     label: 'Telegram bot',   desc: 'Push notifikasi sinyal ke HP' },
    ],
  },
  {
    title: 'Tentang',
    items: [
      { href: 'https://github.com/proreyhanwijaya111/yeehee', icon: Github,  label: 'Source code', desc: 'GitHub repo (public)', external: true },
    ],
  },
]

export default function MorePage() {
  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 animate-fade-in">
      <header className="mb-4">
        <h1 className="text-lg font-black text-slate-100">Lainnya</h1>
        <p className="text-[11px] text-slate-500 mt-0.5">yeehee XAU/USD signal platform · v1.0</p>
      </header>

      <div className="space-y-5">
        <UserHeader />

        {SECTIONS.map(section => (
          <section key={section.title}>
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 px-2">
              {section.title}
            </p>
            <div className="bg-slate-800/40 rounded-2xl border border-slate-800 overflow-hidden divide-y divide-slate-800/80">
              {section.items.map(item => (
                <RowLink key={item.href} item={item} />
              ))}
            </div>
          </section>
        ))}

        <p className="text-center text-[10px] text-slate-600 py-3">
          Hanya untuk penggunaan pribadi
        </p>
      </div>
    </main>
  )
}

function RowLink({ item }: { item: Item }) {
  const Icon = item.icon
  const inner = (
    <div className="flex items-center gap-3 px-3.5 py-3 hover:bg-slate-800/40 active:bg-slate-800/70 transition-colors touch-action">
      <div className="w-8 h-8 rounded-lg bg-slate-800/80 border border-slate-700/50 flex items-center justify-center shrink-0 text-slate-300">
        <Icon size={16} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-100 leading-tight">{item.label}</p>
        {item.desc && <p className="text-[11px] text-slate-500 mt-0.5 truncate">{item.desc}</p>}
      </div>
      {item.badge && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-700/40 text-sky-300 font-mono shrink-0">
          {item.badge}
        </span>
      )}
      {item.external
        ? <ExternalLink size={14} className="text-slate-600 shrink-0" />
        : <ChevronRight size={16} className="text-slate-600 shrink-0" />
      }
    </div>
  )
  if (item.external) {
    return (
      <a href={item.href} target="_blank" rel="noopener noreferrer" className="block">
        {inner}
      </a>
    )
  }
  return <Link href={item.href} className="block">{inner}</Link>
}
