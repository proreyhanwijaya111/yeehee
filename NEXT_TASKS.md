# yeehee — Next Tasks Backlog

Saved 2026-05-05 by code review feedback session. Order = priority, but
all items are **non-urgent**. None blocks current functionality.

---

## In progress (this session)

- [x] Twelve Data real-time spot price integration (daemon-side)
- [x] TradingView XAU/USD live widget di home page (UI-side)

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
