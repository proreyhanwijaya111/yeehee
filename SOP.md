# SOP - yeehee Development & Deployment

Standard Operating Procedure untuk kerja di project yeehee. Tujuan: konsisten, no surprise, no overclaim.

## Arsitektur (jangan lupa)

```
[User HP/Browser]
       v
[Vercel - Next.js] yeehee.vercel.app  -- baca dari Supabase langsung (NO FastAPI backend)
       v read
[Supabase] - signal_bundles, signals, daemon_heartbeat, app_settings, provider_keys, agent_configs, mira_jobs
       ^ write
[Daemon Python di PC rumah user] - 9-agent LLM via OpenRouter, fetch XAU dari yfinance, push ke Supabase
       v consume
[Mira chatbot worker (Node.js, terpisah)] - pakai mira_jobs queue
```

**TIDAK ADA FastAPI/Railway backend.** Semua business logic = client-side TS atau daemon Python.

## SOP saat code change

### 1. Sebelum mulai
```bash
cd C:\Users\re\Pengaturan\Tweaks\yeehee
git status              # cek clean
git pull origin main    # sync latest
```

### 2. Saat coding
- **TypeScript**: pakai `LucideIcon` type, bukan `ComponentType<{size, className}>` (build error)
- **PowerShell scripts** di TS template literals: escape backtick `\``
- **Setup script** (route.ts): ASCII-only body + UTF-8 BOM (PS 5.1 pakai cp1252)
- **Native commands** di PS 5.1: pakai `Invoke-Native` helper, jangan `2>&1 | Out-Null` (stderr quirk)

### 3. Sebelum claim "done"
**SOP wajib semua step ini sebelum bilang sukses:**

> **NEW (post 2026-05-04 17:37):** GitHub `proreyhanwijaya111/yeehee` sudah ke-connect ke Vercel.
> Setiap `git push origin main` = AUTO-DEPLOY ke yeehee.vercel.app.
> **TIDAK PERLU manual `vercel deploy --prod --yes` lagi.** Just push, Vercel handles.

```bash
# Step 1: Build LOCAL (catch errors before pushing)
cd web
npm run build           # exit 0 + tampil semua route
                        # cek "Compiled successfully" + "Generating static pages"
                        # KALAU GAGAL: jangan push, fix dulu

# Step 2: Git commit + push (Vercel auto-deploys after push)
cd ..
git add <specific-files>      # bukan -A blindly (jangan include .env)
git status                    # verify staged correct
git commit -m "..."
git push origin main
                        # ↓ Vercel auto-trigger build + deploy ~1-2 menit

# Step 3: TUNGGU 60-90 detik, cek Vercel auto-deploy succeeded
cd web
sleep 60
vercel ls yeehee | head -3
                        # latest deploy MUST show "● Ready", bukan "● Error"
                        # umur harus < 2 menit (kalau lama = belum trigger)

# Step 4: HTTP test pages kritis
for path in "/" "/signals" "/calculator" "/analysis" "/news" "/more" "/more/settings" "/more/settings/llm" "/more/settings/agents" "/more/settings/daemon" "/api/setup/script"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://yeehee.vercel.app$path")
  echo "  $code  $path"
done
                        # SEMUA harus 200

# Step 5: Setup script content check (kalau update installer)
curl -s https://yeehee.vercel.app/api/setup/script | head -1 | xxd | head -1
                        # MUST start dengan EF BB BF (UTF-8 BOM)
```

**Manual override** kalau perlu force re-deploy tanpa commit (rare):
```bash
cd web && vercel deploy --prod --yes
```

### 4. SAAT ADA ERROR
- **JANGAN** bilang "done"
- **JANGAN** push
- Cari root cause dengan `npm run build 2>&1 | head -40` (full error)
- Fix → re-build → re-deploy → re-verify
- Hanya bilang "fixed" setelah 6-step SOP di atas pass

## Pivot reminders

### Frontend → Supabase langsung (bukan API)
```typescript
// di web/lib/api.ts
const { data } = await supabase
  .from('signal_bundles')
  .select('*')
  .order('created_at', { ascending: false })
  .limit(1)
  .maybeSingle()
```

### Pure math di frontend (calcPosition)
Logic risk sizing, lot calc semua di TypeScript di `web/lib/api.ts::calcPosition`. Port dari `risk/sizing.py`.

### Daemon push ke Supabase
- `daemon/runner.py` -> SettingsStore.push_signal_bundle
- `daemon/heartbeat.py` -> push every 30s
- `daemon/main.py` -> orchestrate signal_loop + mira_loop + heartbeat_loop

## Deploy + Test daemon di PC user

### One-liner install (production-ready)
```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; iwr https://yeehee.vercel.app/api/setup/script -OutFile $env:TEMP\yeehee-setup.ps1; & $env:TEMP\yeehee-setup.ps1 -SupabaseUrl 'https://rzvlunlxcqcjobtkfxwp.supabase.co' -SupabaseAnonKey '<ANON_KEY>'
```

Mode flags:
- (default): Service mode, butuh Admin, auto-start saat boot
- `-Foreground`: testing mode, log live di window
- `-InstallServiceOnly`: alias backwards-compat (sama dengan default)
- `-StopOnly`: stop daemon yang lagi jalan

### Update daemon di PC user setelah code change
```powershell
cd $HOME\yeehee-daemon
git pull
# Service: net stop yeehee-signal-daemon ; net start yeehee-signal-daemon
# Foreground: Ctrl+C window lama, .\.venv\Scripts\python.exe -m daemon.main
```

## Repo structure

```
yeehee/
  ai_agent/             # 9-agent LLM system (llm_router, agents, orchestrator)
  config/               # settings.py (TICKERS, SESSIONS, RISK_PROFILES)
  data/                 # price_fetcher (yfinance + fallback chain), calendar, cot
  features/             # technical, smc, regime, session, intermarket
  strategies/           # scalper/intraday/swing rule-based signal generators
  risk/                 # sizing.py (Python original; ported to TS in lib/api.ts)
  backtest/             # engine + monte_carlo (Python; not yet wired to UI)
  daemon/               # main.py, runner.py, mira.py, heartbeat.py, requirements.txt
  notify/               # telegram_bot
  web/                  # Next.js frontend (Vercel)
    app/                # routes (Beranda, Sinyal, Kalkulator, AI, Lainnya, settings/*)
    components/         # HeroCard, SignalCard, BottomNav, etc.
    lib/                # api.ts (Supabase + math), settings.ts, llm-models.ts
  supabase/             # schema.sql (initial)
  SOP.md                # this file
  PROGRESS.md           # current state + pending tasks
```

## Vercel + Supabase config

- **Vercel project**: `ahmadreywijaya-4649s-projects/yeehee`, alias `yeehee.vercel.app`
- **Vercel env vars** (set via `vercel env add <NAME> production`):
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `NEXT_PUBLIC_API_URL` (legacy, masih ada tapi ga dipake setelah pivot)
- **Supabase project**: `rzvlunlxcqcjobtkfxwp` (region ap-southeast-1)
- **Supabase tables**: signal_bundles, signals, alert_log, app_settings, provider_keys, agent_configs, mira_jobs, daemon_heartbeat

## Lanjut di device lain

```bash
git clone https://github.com/proreyhanwijaya111/yeehee.git
cd yeehee
cat SOP.md         # baca SOP ini
cat PROGRESS.md    # cek status terakhir + pending tasks
```

Vercel CLI:
```bash
npm i -g vercel
vercel login              # device code via browser
vercel link --project yeehee --yes
```

Python venv (untuk run engine local):
```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r daemon\requirements.txt
```

## Gotchas yang sudah pernah bikin masalah (jangan lupakan)

| # | Issue | Fix |
|---|---|---|
| 1 | TS template literal `` ` `` ga di-escape | Pake `\`` di route.ts |
| 2 | Lucide icon as React.ComponentType | Pake `LucideIcon` type |
| 3 | PS 5.1 codepage cp1252 | UTF-8 BOM + ASCII body di setup script |
| 4 | PS 5.1 `2>&1` stderr quirk | `Invoke-Native` helper |
| 5 | MS Store Python alias (Win 11) | `Test-RealPython` checks file size + version |
| 6 | Yahoo `GC=F` empty/region-block | Fallback chain ke `XAUUSD=X` -> `GLD` |
| 7 | Pip `pypi.org` slow di Indonesia | Default `pypi.tuna.tsinghua.edu.cn` |
| 8 | Pip default timeout 15s | Bump ke `--timeout 300 --retries 20` |
| 9 | Supabase `/rest/v1/` returns 401 walau key valid | Pake `/rest/v1/app_settings?limit=1` untuk pre-flight |
| 10 | UI masking applied to copy too | Split `displayCode` vs `copyCode` di CodeBlock |
| 11 | Daemon foreground mati saat PC restart | Default = Service mode (NSSM auto-start) |
| 12 | Frontend ngarep FastAPI yang ga ada | Refactor `lib/api.ts` ke Supabase-direct |
