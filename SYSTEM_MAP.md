# yeehee — System Map

Single source of truth untuk semua file & service yang relevant.

## TL;DR — semua di-control dari satu folder

```
C:\Users\Administrator\yeehee-daemon\          ← REPO ROOT (this folder)
```

Yang bisa dimove: 100% repo content (Python code, EA source, web frontend, scripts, docs).
Yang TIDAK bisa dimove (system-managed): MT5 install, Windows Startup folder, .cloudflared in user profile, cloudflared.exe.

## Folder breakdown (inside repo)

| Folder | Isi |
|---|---|
| `daemon/` | Signal generator + trade tracker + orphan sweeper |
| `rcs/` | Core composite (RCS) + per-style strategies + EA source code |
| `rcs/ea/DextradeEA.mq5` | EA source (canonical, version-controlled) |
| `rcs/ea/DextradeEA.ex5` | Compiled EA (committed for backup) |
| `rcs/src/execution_api.py` | FastAPI :8001 — EA polling + spot mirror endpoints |
| `web/` | Next.js frontend (yeehee.clinix.id), runs on :3000 |
| `strategies/` | Per-style signal generation (scalper, intraday, swing) |
| `features/` | Indicators (technical, SMC, regime, intermarket) |
| `data/` | Price fetchers (yfinance, stooq, MT5 mirror) |
| `notify/` | Telegram + Web Push (VAPID) notifications |
| `config/` | Strategy ATR multipliers + thresholds |
| `scripts/` | Cmd/PS1 launchers, install scripts, attach automation |
| `supabase/migrations/` | DB schema migrations (apply via Supabase dashboard) |
| `system/` | Documentation pointing to external (out-of-repo) files |
| `logs/` | Per-day rotating logs (web-task, daemon-task, execapi, tunnel-task) |

## External files yang TIDAK bisa di-move

### 1. MT5 install
- Path: `C:\Program Files\MetaTrader 5\terminal64.exe`
- Auto-launches at logon via Startup folder shortcut
- EA reads compiled .ex5 from MT5's own Experts folder

### 2. MT5 EA compiled .ex5
- Path: `%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\DextradeEA.ex5`
- Source canonical: `rcs/ea/DextradeEA.mq5` (this repo)
- After edit + recompile: copy back to MT5 Experts dir, trigger `yeehee-mt5-attach` task

### 3. MT5 startup shortcut
- Path: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\MetaTrader 5.lnk`
- Effect: launches MT5 every Windows logon (so EA can run unattended)
- Don't delete

### 4. Cloudflare tunnel config + secrets
- Path: `%USERPROFILE%\.cloudflared\`
- Files:
  - `config.yml` — tunnel ingress mapping (backed up to `system/cloudflared/`)
  - `5e18741a-...json` — tunnel credentials (SECRET, never in repo)
  - `cert.pem` — Cloudflare account cert (SECRET, never in repo)
- cloudflared binary expects this exact path

### 5. cloudflared.exe binary
- Path: `C:\Program Files (x86)\cloudflared\cloudflared.exe`
- Installed via `winget install Cloudflare.cloudflared`
- Used by `yeehee-tunnel` Task Scheduler task

### 6. Desktop launcher shortcut
- Path: `%USERPROFILE%\OneDrive\Desktop\yeehee - Start All.lnk`
- Target: `scripts/start-all-yeehee.cmd` (in this repo)
- Effect: double-click → launches MT5 + 6 yeehee Task Scheduler tasks

## Service inventory (Windows Task Scheduler)

All have `AtLogOn` trigger — auto-start on user login. Run as Administrator (Limited principal).

| Task | What | Action | Auto-restart |
|---|---|---|---|
| `yeehee-web` | Next.js (port 3000) | `scripts/start-web.cmd` | ✓ wrapper :loop |
| `yeehee-tunnel` | Cloudflare tunnel | `scripts/start-tunnel.cmd` | ✓ wrapper :loop |
| `yeehee-daemon` | Python signal worker | `scripts/start-daemon.cmd` | ✓ wrapper :loop |
| `yeehee-fastapi` | FastAPI :8001 (EA poll) | uvicorn direct | ✗ no wrapper |
| `yeehee-recalibrator` | Premium gap recalibrator | direct python | ✗ no wrapper |
| `yeehee-mt5-attach` | EA attach via pywinauto | direct python (90s wait) | one-shot |

## Public URLs

- **App**: https://yeehee.clinix.id (Next.js → Cloudflare tunnel → port 3000)
- **EA local API**: http://localhost:8001 (only EA + daemon hit this)
- **Supabase REST**: https://jjcxfdkkmwchdvvczyzh.supabase.co/rest/v1/

## Recovery scenarios

**A. Daemon crashed**
- Wrapper `:loop` auto-respawns within 30s
- Or manually: double-click desktop shortcut

**B. EA detached**
- Run `Start-ScheduledTask yeehee-mt5-attach` (or click desktop shortcut)

**C. MT5 closed**
- Restart MT5 via desktop shortcut OR click Startup folder shortcut

**D. PC reboot**
- Windows logon → MT5 auto-launch via Startup folder
- 6 Task Scheduler tasks AtLogOn fire → all services up
- yeehee-mt5-attach (delayed 90s) → EA attached

**E. Cloudflare tunnel down**
- yeehee-tunnel wrapper auto-respawns
- Verify: `curl https://yeehee.clinix.id/login` should return 200

## Quick commands

```powershell
# Status all services
Get-ScheduledTask -TaskName "yeehee-*" | Format-Table TaskName, State

# Restart all
& "$env:USERPROFILE\OneDrive\Desktop\yeehee - Start All.lnk"

# Force-stop daemon (wrapper will respawn within 30s)
Get-CimInstance Win32_Process -Filter 'Name="python.exe"' |
  Where-Object { $_.CommandLine -like '*daemon.main*' } |
  Stop-Process -Force

# View latest daemon log
Get-Content C:\Users\Administrator\yeehee-daemon\logs\daemon-task-*.log -Tail 30

# Check EA log
Get-Content "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Logs\$(Get-Date -Format yyyyMMdd).log" -Tail 20
```

## Update workflow

```bash
# Edit code
cd C:\Users\Administrator\yeehee-daemon
git pull
# ... make changes ...
git add . && git commit -m "..." && git push

# If web changed
cd web
npm run build
Stop-ScheduledTask yeehee-web; Start-ScheduledTask yeehee-web

# If daemon changed (auto picked up next cycle, or force restart)
Stop-ScheduledTask yeehee-daemon  # wrapper :loop respawns

# If EA changed
# 1. Copy rcs/ea/DextradeEA.mq5 to MT5 Experts dir
# 2. metaeditor64.exe /compile:DextradeEA.mq5
# 3. Copy compiled .ex5 back to rcs/ea/
# 4. Start-ScheduledTask yeehee-mt5-attach
```
