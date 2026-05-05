# yeehee — Next Tasks Backlog

Saved 2026-05-05 by code review feedback session. Order = priority, but
all items are **non-urgent**. None blocks current functionality.

---

## In progress (this session)

- [x] Twelve Data real-time spot price integration (daemon-side)
- [x] TradingView XAU/USD live widget di home page (UI-side)
- [x] Verified MC math correctness (analytical = actual, expectancy 0.375)
- [x] Historical backtest API + UI (real XAU OHLCV + rule-engine + equity curve)

## Pending (waiting on user action)

- [ ] **Set TWELVE_DATA_API_KEY in Vercel env vars** (so /api/backtest-historical
      works without per-request key). User key: `33e77a449b184ce897f4aa2d1c7c03fb`
      (paste this with `vercel env add TWELVE_DATA_API_KEY production`).
      User said: "boleh tapi jangan dikerjain dulu buat list aja" — execute when
      user explicitly says go.

- [ ] **Set TWELVE_DATA_API_KEY in PC daemon .env** (so daemon uses real-time
      spot via fetch_realtime_xau_spot, not yfinance fallback). Same key as above.
      User reminder: "step 2 saya bingung ingetin saya nanti".

- [ ] **Verify Historis backtest end-to-end** after API key set:
      1. Buka /more/backtest, klik tab "Historis"
      2. Settings: 1h timeframe, 90d lookback, 10000 modal, 1% risk, 10K MC runs
      3. Click "Jalankan backtest historis"
      4. Verify: trades count > 0, equity curve renders, MC stats populate
      5. Compare expected output: ~50-150 trades over 90d, win rate 35-55%
         depending on volatility, expectancy positive if rule-engine works

## Deferred — UI/UX polish

- [ ] **Loading skeleton placeholders** to replace generic "Memuat..."
      text. Even though SSR now fills first paint, slow Supabase
      response could still show empty state — better with shimmer card
      shapes matching final content.
- [ ] **Settings to gear icon top-right** of each page. Free up the
      "Lainnya" tab to be more focused (currently hub for settings +
      news + backtest + glossary). Settings deserves dedicated quick
      access.
- [ ] **Page-specific subtitle on header** ("Sinyal · 12 aktif",
      "Kalkulator · Moderat", etc) instead of static branding.
- [ ] **Calculator placeholders** sudah ada (10000, 100) — but consider
      pre-fill defaults yang langsung bisa "Hitung" tanpa input.

## Deferred — Engine improvements

- [ ] **Pattern Recognition Python detector** — currently agent disabled
      because LLM hallucinate from raw OHLC. Need scipy.signal-based
      pattern detection (H&S, double top/bottom, triangles) before
      re-enable.
- [ ] **Volume Profile Python calculator** — POC/VAH/VAL needs proper
      volume bar aggregation. Currently agent disabled.
- [ ] **Backtest fat-tail Monte Carlo** — switch from uniform noise to
      Markov regime-switching with 5% tail event multiplier. Or
      historical bootstrap once 100+ real trades collected in Supabase.

## Deferred — Security / Ops

- [ ] **JWT secret rotate** — leaked anon keys still in git history
      (commit `2a819f1` etc.). User can rotate via Supabase dashboard
      anytime, then update Vercel env + daemon .env.
- [ ] **Multi-PC failover** (worker_id + primary/standby) — currently
      running 2 PCs creates duplicate signal pushes + double LLM cost.
      Active-passive lock via app_settings.active_worker_id.
- [ ] **RLS policies** instead of disabled — current state allows anon
      full CRUD. Add SELECT-only public policy + writes via service_role
      only.

## Deferred — Future features

- [ ] **Mira chatbot worker integration** — `mira_jobs` queue exists,
      Python consumer wired. Need actual chatbot prompts + WhatsApp
      bridge from Mira repo (CliniX monorepo) once user shares hooks.
- [ ] **Telegram push integration** — daemon sends signal alerts when
      STRONG/NORMAL signal triggers. Need Telegram bot token + chat ID
      from user.
- [ ] **PWA install** — manifest + service worker exists, test offline
      mode.
- [ ] **Mobile app wrapper** — Capacitor/React Native shell around
      Vercel PWA for App Store / Play Store distribution.

---

**Resume**: when user kembali ke task ini, baca file ini, pick item, eksekusi.
SOP saat eksekusi: build local → manual deploy from repo root → `vercel ls`
verify `● Ready` → curl HTML check content → commit + push → user verify in browser.
