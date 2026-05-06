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

// Push notification handler (phase 2 wiring; harmless no-op if no payload)
self.addEventListener('push', (event) => {
  if (!event.data) return
  let data = {}
  try {
    data = event.data.json()
  } catch {
    data = { title: 'yeehee', body: event.data.text() }
  }
  const title = data.title || 'yeehee signal'
  const opts = {
    body: data.body || 'New signal received',
    icon: '/icons/icon.svg',
    badge: '/icons/icon.svg',
    tag: data.tag || 'signal',
    data: data.url || '/',
    vibrate: [200, 100, 200],
  }
  event.waitUntil(self.registration.showNotification(title, opts))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data || '/'
  event.waitUntil(self.clients.matchAll({ type: 'window' }).then((clients) => {
    for (const c of clients) {
      if ('focus' in c) return c.focus()
    }
    return self.clients.openWindow(url)
  }))
})
