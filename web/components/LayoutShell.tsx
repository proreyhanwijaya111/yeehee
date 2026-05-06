'use client'
import { usePathname } from 'next/navigation'
import BottomNav from '@/components/BottomNav'

/** Wrapper that hides BottomNav on /login (no nav while gated). */
export default function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const hideNav = pathname === '/login' || pathname?.startsWith('/login/')

  return (
    <>
      <div className={hideNav ? 'min-h-dvh' : 'pb-[72px] min-h-dvh'}>
        {children}
      </div>
      {!hideNav && <BottomNav />}
    </>
  )
}
