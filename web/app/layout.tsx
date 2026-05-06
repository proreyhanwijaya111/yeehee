import type { Metadata, Viewport } from 'next'
import './globals.css'
import LayoutShell from '@/components/LayoutShell'

export const metadata: Metadata = {
  title:       'yeehee · Signal Emas XAU/USD',
  description: 'Platform sinyal XAU/USD (emas) berbasis 12-agent LLM tier pipeline. Server-rendered, mobile-first, real-time refresh.',
  manifest:    '/manifest.json',
  appleWebApp: {
    capable:           true,
    statusBarStyle:    'black-translucent',
    title:             'yeehee',
  },
  icons: {
    icon:  '/icons/icon.svg',
    apple: '/icons/icon.svg',
    shortcut: '/icons/icon.svg',
  },
  openGraph: {
    title:       'yeehee · Signal Emas XAU/USD',
    description: 'Platform sinyal XAU/USD berbasis 12 AI agent tier pipeline.',
    type:        'website',
  },
}

export const viewport: Viewport = {
  width:               'device-width',
  initialScale:        1,
  maximumScale:        1,
  userScalable:        false,
  themeColor:          '#fbbf24',
  viewportFit:         'cover',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className="dark">
      <head>
        {/* iOS PWA install — distinct from android via apple-touch-icon */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="yeehee" />
        <link rel="apple-touch-icon" href="/icons/icon.svg" />
      </head>
      <body className="bg-slate-950 text-slate-100 min-h-dvh">
        <LayoutShell>{children}</LayoutShell>
      </body>
    </html>
  )
}
