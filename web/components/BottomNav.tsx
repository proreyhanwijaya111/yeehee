'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Home, TrendingUp, Briefcase, Brain, MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'

// 5-item bottom nav. Portfolio promoted (was in /more) — main user value
// is real positions + win rate. Kalkulator moved to /more (tool, not core).
const NAV = [
  { href: '/',            label: 'Beranda',   icon: Home },
  { href: '/signals',     label: 'Sinyal',    icon: TrendingUp },
  { href: '/portfolio',   label: 'Portfolio', icon: Briefcase },
  { href: '/analysis',    label: 'Analisis',  icon: Brain },
  { href: '/more',        label: 'Lainnya',   icon: MoreHorizontal },
]

export default function BottomNav() {
  const path = usePathname()

  return (
    <nav className="nav-glass fixed bottom-0 left-0 right-0 z-50 safe-bottom">
      <div className="flex items-center justify-around h-[56px] px-2 max-w-lg mx-auto">
        {NAV.map(({ href, label, icon: Icon }) => {
          // active: exact match or sub-path match
          const active = href === '/' ? path === '/' : path.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex flex-col items-center gap-0.5 min-w-[56px] py-1 px-2',
                'rounded-xl transition-all duration-150 touch-action active:scale-95',
                active
                  ? 'text-sky-400'
                  : 'text-slate-500 hover:text-slate-300',
              )}
            >
              <Icon size={22} strokeWidth={active ? 2.5 : 1.8} />
              <span className={cn(
                'text-[10px] leading-none font-medium',
                active ? 'text-sky-400' : 'text-slate-500',
              )}>
                {label}
              </span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
