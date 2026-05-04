import type { Metadata, Viewport } from 'next'
import './globals.css'
import BottomNav from '@/components/BottomNav'

export const metadata: Metadata = {
  title:       'yeehee · Signal Emas',
  description: 'Platform sinyal XAU/USD (emas) berbasis 4 AI agent. Analisis institutional-grade.',
  manifest:    '/manifest.json',
  appleWebApp: {
    capable:           true,
    statusBarStyle:    'black-translucent',
    title:             'yeehee',
  },
  icons: {
    icon:  '/icons/icon-192.png',
    apple: '/icons/icon-192.png',
  },
  openGraph: {
    title:       'yeehee · Signal Emas XAU/USD',
    description: 'Platform sinyal XAU/USD berbasis 4 AI agent',
    type:        'website',
  },
}

export const viewport: Viewport = {
  width:               'device-width',
  initialScale:        1,
  maximumScale:        1,
  userScalable:        false,
  themeColor:          '#0f172a',
  viewportFit:         'cover',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-dvh">
        {/* Main content — bottom padding for nav bar */}
        <div className="pb-[72px] min-h-dvh">
          {children}
        </div>

        {/* Bottom navigation */}
        <BottomNav />
      </body>
    </html>
  )
}
