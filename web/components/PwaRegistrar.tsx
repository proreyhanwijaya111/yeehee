'use client'
import { useEffect } from 'react'

/**
 * Registers /sw.js once the page loads. Mounted globally via LayoutShell so
 * every route triggers it (idempotent — browser deduplicates registrations).
 *
 * Strategy:
 *   - Try register on mount
 *   - If existing SW differs (version bump), skip-waiting + reload once
 *   - Silent fail in unsupported browsers (older Safari, in-app webview)
 */
export default function PwaRegistrar() {
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!('serviceWorker' in navigator)) return

    const url = '/sw.js'
    let mounted = true

    const register = async () => {
      try {
        const reg = await navigator.serviceWorker.register(url, { scope: '/' })
        // If a new SW is found and ready, prompt it to take over so users get
        // the latest immediately without manual hard-reload.
        reg.addEventListener('updatefound', () => {
          const sw = reg.installing
          if (!sw) return
          sw.addEventListener('statechange', () => {
            if (sw.state === 'installed' && navigator.serviceWorker.controller) {
              // A previous SW exists — tell new one to skip waiting
              sw.postMessage({ type: 'SKIP_WAITING' })
            }
          })
        })
      } catch (e) {
        // Don't surface errors — SW is optional UX boost, not critical
        if (mounted && process.env.NODE_ENV === 'development') {
          console.warn('[pwa] SW register failed:', e)
        }
      }
    }

    register()
    return () => { mounted = false }
  }, [])

  return null
}
