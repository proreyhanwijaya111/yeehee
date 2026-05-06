/**
 * yeehee service worker — minimal scope.
 *
 * Why exists:
 *   - Required for PWA "Add to Home Screen" install prompt to auto-fire on
 *     Chrome (browser checks: HTTPS + manifest + SW with fetch handler +
 *     icons present).
 *   - Foundation for phase 2 web push notifications (push event handler is
 *     stubbed below; will be wired with VAPID once subscription flow lands).
 *
 * What it does NOT do (yet):
 *   - No offline cache (signals are realtime — caching stale data is harmful)
 *   - No push notifications (phase 2: will subscribe + handle 'push' events)
 *   - No background sync
 *
 * Versioning: bump CACHE_VERSION whenever this file changes shape so old
 * clients pick up the new SW on next visit.
 */
const CACHE_VERSION = 'yeehee-sw-v2'

self.addEventListener('install', (event) => {
  // Take over immediately — don't wait for old tabs to close
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Clear ANY old cache (we don't cache anything yet)
    const keys = await caches.keys()
    await Promise.all(keys.map(k => caches.delete(k)))
    await self.clients.claim()
  })())
})

// Fetch handler — pass-through (network only). Required for Chrome to count
// this as a "real" SW for install prompt purposes.
self.addEventListener('fetch', (event) => {
  // Let the browser handle it normally. No cache, no offline fallback.
  // Wrapping in respondWith would force us to handle every edge case;
  // returning early lets the platform default kick in.
  return
})

// Push notification handler — fires when daemon (or /api/push/test) posts an
// encrypted message via the Web Push protocol. Browser already decrypted the
// payload; we receive plaintext via event.data.
//
// Payload formats handled:
//   - JSON: { title, body, url?, tag? }            ← daemon production push
//   - Plain text: 'message'                        ← simple fallback
//   - Empty (no payload): generic "Sinyal baru"    ← /api/push/test
self.addEventListener('push', (event) => {
  let data = { title: 'yeehee', body: 'Sinyal baru tersedia' }
  if (event.data) {
    try {
      const parsed = event.data.json()
      data = { ...data, ...parsed }
    } catch {
      try {
        const t = event.data.text()
        if (t) data.body = t
      } catch {/* ignore */}
    }
  }
  const opts = {
    body:     data.body || 'Sinyal baru',
    icon:     data.icon  || '/icons/icon.svg',
    badge:    data.badge || '/icons/icon.svg',
    tag:      data.tag   || 'yeehee-signal',
    data:     { url: data.url || '/', ts: Date.now() },
    requireInteraction: data.requireInteraction === true,
    vibrate:  data.vibrate || [200, 100, 200],
    silent:   false,
  }
  event.waitUntil(self.registration.showNotification(data.title || 'yeehee signal', opts))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil((async () => {
    // Focus existing tab if open, else open new one
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const c of allClients) {
      try {
        const u = new URL(c.url)
        if (u.origin === self.location.origin) {
          await c.focus()
          if ('navigate' in c) {
            await c.navigate(targetUrl)
          }
          return
        }
      } catch {/* ignore */}
    }
    await self.clients.openWindow(targetUrl)
  })())
})
