# Cloudflare Pages Migration Guide

> Status PC kantor (2026-05-07): code-side setup DONE. Push terbaru sudah include
> adapter `@cloudflare/next-on-pages` + `wrangler` + `wrangler.toml`. Yang
> tinggal di sisi PC rumah: bikin Cloudflare account/project + set env vars +
> trigger first deploy. Vercel tetap dibiarkan jalan dulu sebagai fallback.

## Why migrate

Vercel Hobby free tier kena cap (1.4M/1M function invocations + 5h51m/4h CPU
per 2026-05-07 ~11:50 WIB) menyebabkan UI stale, ISR cache tidak refresh,
user-facing bug yang sempat di-misdiagnose berkali-kali.

Cloudflare Pages free tier:

| Resource         | Cloudflare Free  | Vercel Hobby   | Multiplier |
|------------------|------------------|----------------|------------|
| Workers/Functions| 100K req/day     | 1M req/month   | ~3x        |
| Static requests  | unlimited        | included       | -          |
| Bandwidth        | unlimited        | 100GB/month    | infinite   |
| Builds/month     | 500              | 6000           | lower      |
| CPU per request  | 10ms (free)      | no hard limit  | tighter    |
| Custom domain    | free             | free           | -          |
| SSL              | auto             | auto           | -          |

100K req/day = ~3M/month — kira-kira **3x lebih banyak** dari Vercel Hobby
1M/month, dan ga ada hard CPU/month cap (cuma per-request 10ms).

UI ini SSR rendering biasanya <10ms (mostly awaiting Supabase fetch — ga
count sebagai CPU time, cuma JS execution actual yang count). Jadi 10ms
limit aman untuk semua route yang ada sekarang.

## Apa yang sudah dilakukan PC kantor (commit ini)

1. `web/package.json` tambah devDependencies:
   - `@cloudflare/next-on-pages@^1.12.0`
   - `wrangler@^3.114.17`
   - `@cloudflare/workers-types@^4`
2. `web/package.json` tambah scripts:
   - `pages:build`  → run next-on-pages converter
   - `pages:preview` → wrangler local preview
   - `pages:deploy` → wrangler deploy ke Cloudflare Pages project
3. `web/wrangler.toml` baru — minimal config:
   - `compatibility_flags = ["nodejs_compat"]`
   - `pages_build_output_dir = ".vercel/output/static"`
4. `web/.dev.vars.example` baru — template env vars untuk local preview
5. `web/.gitignore` add `.dev.vars` + `.wrangler/`
6. TypeScript typecheck PASSED with new packages.

**Yang TIDAK dilakukan PC kantor (intentional)**:
- Tidak run `npx @cloudflare/next-on-pages` di Windows local — known issue
  spawn npx ENOENT di Windows (warning di tool output). Cloudflare CI build
  di Linux jadi gak masalah saat actual deploy.
- Tidak deploy — credentials Cloudflare ada di sisi user, bukan PC kantor.

## Yang harus PC rumah lakukan

### STEP 1 — One-time Cloudflare account setup (~5 menit)

1. Login/register di https://dash.cloudflare.com
2. Sidebar **Workers & Pages** → **Create** → tab **Pages** →
   **Connect to Git**
3. Pilih repo `proreyhanwijaya111/yeehee` (authorize GitHub kalau perlu)
4. Branch deployment: `main`
5. Build settings:
   - **Framework preset**: `Next.js`
   - **Build command**: `npx @cloudflare/next-on-pages`
   - **Build output directory**: `.vercel/output/static`
   - **Root directory (advanced)**: `web`
   - **Node version**: pakai env var `NODE_VERSION = 22` (lihat STEP 2)

### STEP 2 — Environment variables di Cloudflare (~5 menit)

Di project dashboard Cloudflare → **Settings** → **Variables and Secrets**.

**Production** scope, semua yg ada di Vercel sekarang:

```
NODE_VERSION                = 22
NEXT_PUBLIC_SUPABASE_URL    = https://jjcxfdkkmwchdvvczyzh.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY = (copy dari Vercel)
SUPABASE_SERVICE_ROLE_KEY   = (copy dari Vercel) [encrypt: yes]
AUTH_SECRET                 = (copy dari Vercel) [encrypt: yes]
AUTH_USERNAME               = (copy dari Vercel)
AUTH_PASSWORD               = (copy dari Vercel) [encrypt: yes]
VAPID_PUBLIC_KEY            = (copy dari Vercel)
VAPID_PRIVATE_KEY           = (copy dari Vercel) [encrypt: yes]
VAPID_SUBJECT               = (copy dari Vercel)
TWELVE_DATA_API_KEY         = (copy dari Vercel)
```

Gampangnya: dari Vercel dashboard → Settings → Environment Variables →
"Show value" tiap var → copy ke Cloudflare. Sensitif var (yang
mengandung KEY/SECRET/PASSWORD) wajib pilih **encrypted**.

### STEP 3 — Trigger first deploy (~3 menit build)

1. Klik **Save and Deploy** di Cloudflare Pages settings
2. Tunggu build selesai. Liat **Deployments** tab. Build log nampilin:
   - `npm ci` install deps
   - `npx @cloudflare/next-on-pages` convert .next → .vercel/output/static
   - Upload assets
   - Deploy URL: `https://yeehee-XXXX.pages.dev`
3. Buka URL → harusnya UI sama persis dengan yeehee.vercel.app
4. Test login + buka /portfolio → cek heartbeat panel populated, balance,
   active trades. Kalau semua jalan = success.

### STEP 4 — Custom domain (optional, ~5 menit)

Kalau lo mau pake `yeehee.vercel.app` -> ga bisa (itu domain Vercel).

Opsi:
- A) Pakai default `*.pages.dev` URL yg dikasih Cloudflare (free, no setup).
- B) Beli/pasang custom domain di Cloudflare:
  1. Project → **Custom domains** → **Set up a custom domain**
  2. Masukin domain (mis. `yeehee.app` atau subdomain mis. `app.yourdomain.com`)
  3. Cloudflare otomatis bikin DNS record kalau domain udah di Cloudflare DNS
  4. SSL cert auto-issued. Live dalam <1 menit.

### STEP 5 — Update VAPID origin (PWA push notifications)

Web Push subscription terikat ke origin. Kalau Cloudflare URL beda dari Vercel
URL yang user pernah subscribe:

1. Existing subscriber harus re-subscribe dari new domain (toggle off → on
   notifications di /more/settings/notifications). Push lama dari Vercel ga
   akan trigger ke browser yang udah pindah ke Cloudflare URL.
2. VAPID keypair sendiri sama (ga perlu regenerate).

### STEP 6 — Update daemon push target (kalau pake daemon→web push)

Cek di daemon code: ada call ke API `/api/push/...` di Vercel?
Kalau iya, update base URL daemon ke Cloudflare URL baru. Atau biarkan
Vercel jalan paralel untuk push selama transition.

### STEP 7 — Verifikasi end-to-end (15 menit observation)

1. Buka /portfolio, cek panel EA — harus consistent dengan claim "online"
2. Tunggu 1-2 cycle daemon (3-6 menit) — observe revalidate kalau ada
   bundle baru
3. Cek Cloudflare → Workers & Pages → yeehee → **Metrics**:
   - Request count per hour
   - Error rate (target 0%)
   - CPU time p99 (kalau >8ms warning, hampir limit)
4. Toggle SWR refresh balik ke 60s di [HomeClient.tsx](web/app/HomeClient.tsx)
   dan [SignalsClient.tsx](web/app/signals/SignalsClient.tsx) — quota Cloudflare
   muat. Test di Cloudflare URL dulu (jangan push ke main yet).

### STEP 8 — Cutover (PILIHAN, kapan lo siap)

**Opsi A — Soft cutover (recommended)**: tetap dual-deploy
- Push ke main → Vercel + Cloudflare dua-duanya auto-rebuild
- User access via Cloudflare URL primarily
- Vercel jadi fallback kalau Cloudflare ada issue
- Cost: 0 (Vercel rebuild masih gratis sampai cap), cuma manage 2 dashboard

**Opsi B — Full cutover**: matiin Vercel
- Project Vercel → Settings → Delete project (atau pause auto-deploy)
- Update README + docs hilangin reference yeehee.vercel.app
- Hapus `web/vercel.json`
- Hapus push notification subscription lama (semua user re-subscribe)

**Opsi C — DNS swap** (kalau pake custom domain di Vercel)
- Point DNS dari Vercel IP → Cloudflare. User ga sadar pindah host.

## Rollback plan

Kalau Cloudflare bermasalah:
1. Buka Vercel dashboard → project tetap live di yeehee.vercel.app
2. Suruh user pakai URL Vercel sementara
3. Cloudflare project ga perlu di-delete — biarkan, debug saat senggang
4. Code di repo masih kompatibel dual-deploy

## Verifikasi: bisa refresh 1 menit?

Math:
- 100K req/day Cloudflare free = 4166 req/hour
- 1 user buka /portfolio dengan SWR refresh 60s = 60 req/hour per user (1 server
  fetch per refresh — actually ~3 server fetches per page since /portfolio
  fetches heartbeat + active trades + bundle)
- Total per user dengan refresh 60s = ~180 req/hour
- 4166 / 180 = 23 concurrent users hammering 24/7 dalam quota free

Untuk skala lo sekarang (1-3 user), refresh 60s aman banget. Bahkan 30s aman
(double rate = 12 user concurrent). Vercel sebelumnya cuma muat ~7 user
concurrent dengan refresh 60s — Cloudflare 3x lebih lega.

CPU 10ms/request: server-component /portfolio rendering biasanya <5ms (mostly
async waits ke Supabase yg ga count CPU). Cek di Cloudflare metrics setelah
deploy.

## Reference

- next-on-pages docs: https://github.com/cloudflare/next-on-pages
- Cloudflare Pages limits: https://developers.cloudflare.com/pages/platform/limits/
- Workers free plan: https://developers.cloudflare.com/workers/platform/limits/
