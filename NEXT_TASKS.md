# yeehee — Next Tasks Backlog

Saved 2026-05-05 by code review feedback session. Order = priority, but
all items are **non-urgent**. None blocks current functionality.

---

## In progress (this session)

- [x] Twelve Data real-time spot price integration (daemon-side)
- [x] TradingView XAU/USD live widget di home page (UI-side)
- [x] Verified MC math correctness (analytical = actual, expectancy 0.375)
- [x] Historical backtest API + UI (real XAU OHLCV + rule-engine + equity curve)

## SESSION 2026-05-06 19:55 WIB — autonomous spot price triage (PC RUMAH / worker)

> **CLARIFICATION (2026-05-06 ~22:50 WIB)**: Claude di session ini awalnya keliru
> sebut PC ini "PC kantor" — yang BENAR adalah **PC RUMAH** (worker, hostname
> `DESKTOP-LHVGFIT`, IP 192.168.1.82). Yang menjalankan daemon, MT5 Exness, dan
> tempat semua action di session ini terjadi. **PC kantor** = remote dev env
> tempat user develop kode (tidak run daemon, tidak ada MT5). User Claude di PC
> kantor besok yang bakal baca file ini perlu paham: setiap aksi di session ini
> terjadi di PC rumah, bukan PC kantor. Topology disimpan permanent di memory
> file `setup_topology.md`.

User pergi ke RS, minta gua handle gap $4-7 antara harga sinyal vs broker. State saat
intervensi: daemon PRIMARY di PC rumah (worker, `worker_id=desktopl-auto`), log
`xau spot: $4690.70 (yfinance_fallback)`,
`entry-base spot=$4686.90 (GC=F $4693.90 - $7.00 premium)`. Broker MT5 mid $4681.55.

Diagnosis 4-tier spot resolution:
- **Tier 0 (MT5 EA mirror)**: off — FastAPI :8001 belum di-start di PC rumah + EA
  belum attach ke chart. **User harus setup manual besok di PC rumah** (lihat
  instruksi bawah; PC kantor tidak bisa setup ini karena ga ada MT5 di sana).
- **Tier 1 (Twelve Data)**: QUOTA HABIS hari ini ("1502/800 credits used"). Reset
  besok pagi (UTC 00:00 = 07:00 WIB), lalu daemon auto-recalibrate adaptive premium.
- **Tier 2 (Yahoo HTTPS XAUUSD=X)**: 404 "delisted" — symbol mati di endpoint Yahoo,
  fix yang di commit `2f91d5b` udah ga work lagi.
- **Tier 3 (GC=F - adaptive premium)**: ACTIVE PATH, tapi premium default `$7` stale
  (real gap GC=F-vs-spot saat ini `$14.31` dari yfinance GC=F $4694.00 - stooq XAU
  $4679.69).

**Action diambil — MINIMAL & REVERSIBLE (zero code change):**
- Tulis `data_cache/futures_premium_gap.txt` = `14.31`. Daemon `_load_premium_gap()`
  baca file ini next cycle, langsung kasih `entry-base spot=GC=F-$14.31` ~$4679.70
  (match broker dalam ±$2). File ini memang di-design buat di-write daemon (sanity
  check `1.0 < gap < 30.0` di runner.py:110); gua cuma seed manual karena tier 1+2
  yang biasa nge-write semuanya broken hari ini.
- Self-heal: tomorrow morning Twelve Data quota reset → daemon auto-overwrite file
  dengan gap real-time dari spot source yang hidup lagi.

**Reversible:** `del data_cache\futures_premium_gap.txt` → fallback ke
env `XAU_FUTURES_PREMIUM_USD=7.0`.

**Verified file di-baca daemon** — bundle 14:14 UTC scalper.entry=$4702.99,
GC=F bar close ~14:10 UTC = $4717.30. Match: $4717.30 - $4702.99 = exactly $14.31.

**Caveat — fast-move accuracy**: gold sempat rally cepat (GC=F $4694 -> $4719 dalam 30
menit), real GC=F-vs-spot basis swing +$10..+$22 selama itu. Static $14.31 lebih bagus
dari $7 default tapi belum sempurna track fast moves.

### UPGRADE — auto-recalibrator script (running NOW)

User bilang "akalin dengan cara pragmatis engineering biar signal akurat". Solution:
`scripts/recalibrate_gap.py` (NEW file, no daemon code change). Setiap 60 detik:
- Pull GC=F latest 5m close (yfinance python lib, proven works on PC rumah)
- Pull XAU spot dari stooq.com CSV (no key, no quota, broker-grade)
- Compute gap = GC=F - XAU
- Sanity clip ke [$1.01, $25.00] — gold basis rarely outside this range
- Write to `data_cache/futures_premium_gap.txt`

Daemon's `_load_premium_gap()` (runner.py) tetap baca file itu tiap cycle, tanpa
perubahan code. Hasilnya: setiap bundle dapet gap fresh dalam 60 detik real-time
basis, bukan stale $7 default atau static $14.31.

**Cara restart kalau crash / mati:**
```
cd C:\Users\Administrator\yeehee-daemon
.venv\Scripts\activate
python -X utf8 scripts/recalibrate_gap.py
```
(Note: `-X utf8` perlu karena ada karakter non-ASCII di output; default Windows
cp1252 console nge-crash. Sudah di-strip dari script tapi safety-belt dipertahankan.)

**Stop & revert:** Ctrl+C di terminal recalibrator. Optional: `del
data_cache\futures_premium_gap.txt` -> daemon fallback ke env $7 default.

**Status verification (2026-05-06 21:51 WIB)**: Recalibrator running background
(claude session task). Last write: gap=$17.46 (GC=F $4721.20 - XAU $4703.74).
Bundle 14:48 UTC pushed xau_price=$4708.89 vs stooq XAU $4705.21 = +$3.68 deviation
(sangat dekat broker, broker spread vs LBMA typical $1-3). VERIFIED working.

### KNOWN PRE-EXISTING BUG (not introduced by this fix)

Bundle 14:41:21 UTC pushed `xau_price=418.05` -- ini bug GLD fallback di
`data/price_fetcher.py:_fetch_with_fallback`. Kalau GC=F gagal (yfinance rate
limit), fallback ke GLD ETF yang ~10x lebih murah (~$432). Daemon downstream
tidak validate scale, jadi compute spot = $432 - $14.31 = $418 -- pushed apa adanya.
**Mitigation besok**: di runner.py setelah `df_close_now = float(...)`, tambahin:
```python
if df_close_now is not None and not (1000 < df_close_now < 10000):
    log(f"[runner] WARN df_5m close=${df_close_now} unrealistic (likely GLD fallback) -- abort")
    return  # or skip push
```
Frequency observed: 1/5 bundles tonight = 20%. User-visible kalau buka app pas
bundle corrupt. Recalibrator ga fix ini -- fix di code daemon needed (require
restart). Decision tonight: skip karena restart daemon risky tanpa user supervisi.

### Permanent code fixes (rekomendasi BESOK saat user kembali)

1. Add `fetch_stooq_spot()` di `data/price_fetcher.py` (pattern `fetch_yahoo_spot`)
2. Wire as Tier 2.5 di `daemon/runner.py` (between yahoo + adaptive premium)
3. Add df_close_now sanity check (block GLD-fallback corruption)
4. Restart daemon, retire recalibrator script (or keep as belt-and-suspenders).

### Untuk MT5 EA mirror (Tier 0) — yang user pengen utamanya, lanjutin BESOK di PC RUMAH

> Catatan: MT5 + DextradeEA hanya ada di PC rumah (worker). Setup ini harus
> dilakukan langsung di PC rumah, bukan via remote dev di PC kantor.

State PC rumah sekarang: MT5 Exness Demo running, XAUUSDm di Market Watch,
DextradeEA udah di Navigator (compiled sebelumnya). Yang kurang:

1. **Start FastAPI execution_api** (terminal terpisah, biarkan running):
   ```
   cd C:\Users\Administrator\yeehee-daemon
   .venv\Scripts\activate
   python -m uvicorn rcs.src.execution_api:app --host 0.0.0.0 --port 8001
   ```
2. **MT5 — drag XAUUSDm dari Market Watch ke chart** (sekarang chart kosong abu-abu)
3. **MT5 — klik tombol "Algo Trading"** di toolbar (sekarang ⚠️ kuning, harus 🟢)
4. **MT5 → Tools → Options → Expert Advisors** → centang
   `Allow WebRequest for listed URL` → tambah `http://localhost:8001`
5. **MT5 — drag `DextradeEA`** dari Navigator ke chart XAUUSDm. Pop-up → Common tab
   → centang Allow Algo Trading. OK. Smiley face 😀 muncul di pojok chart = running.
6. Verify: `curl http://localhost:8001/api/spot/latest` return `{ok:true, mid:...}`
7. Daemon log next cycle akan show `entry-base spot=$XXXX (mt5 broker mirror)` →
   ZERO gap dari broker quote. Tier 0 win permanen.

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
