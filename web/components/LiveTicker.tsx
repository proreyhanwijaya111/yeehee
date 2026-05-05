'use client'
import { useEffect, useRef } from 'react'

/**
 * TradingView XAU/USD live ticker widget.
 *
 * Why client-only: TradingView's embed script is a web-component that
 * requires DOM. We mount it post-hydrate using their official embed.
 *
 * No API key needed (free embed). Data source: OANDA spot XAU/USD.
 * Updates in real-time (~1 second tick), independent dari daemon refresh.
 */
export default function LiveTicker() {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    // Clear previous (HMR safety)
    ref.current.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js'
    script.async = true
    script.type = 'text/javascript'
    script.innerHTML = JSON.stringify({
      symbol:        'OANDA:XAUUSD',
      width:         '100%',
      colorTheme:    'dark',
      isTransparent: true,
      locale:        'en',
    })
    ref.current.appendChild(script)
  }, [])

  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-2xl overflow-hidden">
      {/* Outer wrapper — TradingView injects here */}
      <div className="tradingview-widget-container">
        <div ref={ref} className="tradingview-widget-container__widget" />
        <div className="tradingview-widget-copyright px-3 py-1 text-[9px] text-slate-600">
          Live spot · powered by{' '}
          <a
            href="https://www.tradingview.com/symbols/XAUUSD/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-500 hover:text-slate-300"
          >
            TradingView
          </a>
        </div>
      </div>
    </div>
  )
}
