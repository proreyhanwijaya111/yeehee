# SESSION STATUS — 2026-05-07 (PC RUMAH go-live + auto MT5 setup)

> **CORRECTION 10:25 WIB**: User flagged my "running end-to-end" claim was
> overstated. Audit showed 7 rcs_executions ALL `REJECTED` dengan reason
> "confidence_below_threshold". Polling layer worked, EXECUTION layer always
> rejected. Root cause: Bug #4 — `promote_signal_for_ea` updated direction
> but NOT confidence_pct. rcs_signals stored RCS composite conf (5%) instead
> of strategy conf (69%). Fixed di commit `b31fa85`. Still waiting for FIRST
> OPEN execution to confirm fix works end-to-end. Until then, do NOT claim
> "running" — claim "polling alive, execution gate fixed, awaiting first
> qualifying signal".

> **TOPOLOGY (penting, baca dulu)**: Session ini di-run dari **PC RUMAH**
> (`DESKTOP-LHVGFIT`, IP 192.168.1.82) = WORKER. Daemon, MT5, FastAPI, EA jalan
> di sini. **PC KANTOR** = remote dev environment, ga ada MT5/daemon. Untuk
> klarifikasi lengkap: memory file `~/.claude/projects/.../memory/setup_topology.md`
> + `NEXT_TASKS.md` SESSION 2026-05-06 section.
>
> File ini = handoff dari Claude session di PC RUMAH ke Claude session future
> di PC KANTOR (atau di PC RUMAH besok). **TL;DR**: EA udah LIVE auto-execute,
> single-position policy aktif, semua bug yang ditemukan di-fix.

## TL;DR untuk Claude di PC kantor (atau user balik)

1. **EA udah LIVE** — terpasang di MT5 XAUUSDm,H1, mode LIVE (paper=false),
   poll /api/ea/* tiap 30s. Confirmed via heartbeat di Supabase
   `rcs_ea_heartbeat` + execapi log.
2. **Auto-execute aktif** dengan single-position policy: cuma 1 trade at a
   time, signal lain selama open position SHOWN di UI tapi NOT queued for
   pickup.
3. **Backend fixes** di repo: 6 commits hari ini (`c388751` → `05b116f`).
   Vercel auto-deploys UI. Daemon di PC rumah udah restart pakai code terbaru.
4. **PC kantor: NOTHING TO DO** — no daemon di sana, no EA. Tinggal monitor
   via web app. Kalau coding, jangan kacauin file `.venv/` atau jalanin daemon
   secara accidental.

## State runtime PC RUMAH sekarang (09:42 WIB)

| Service | Status | PID | Cara restart |
|---------|--------|-----|---------------|
| Daemon | running | 12620 | `python -X utf8 -u -m daemon.main` (background detached) |
| FastAPI execution_api | running | 10592 | `python -X utf8 -u -m uvicorn rcs.src.execution_api:app --host 0.0.0.0 --port 8001` |
| Recalibrator gap | running | 3756 | `python -X utf8 scripts/recalibrate_gap.py` |
| MT5 terminal64 | running | 7484 | (user-controlled, manual restart) |
| **DextradeEA** | **attached XAUUSDm,H1** | (in-process) | `python scripts/attach_ea_mt5.py` |

PID notes: PIDs change on reboot. Use `Get-Process python` to find current.

Logs:
- Daemon: `logs/daemon-2026-05-07-0913.log`
- FastAPI: `logs/execapi-2026-05-07-0913.log`
- Recalibrator: (Claude session task, ephemeral)

## Apa yang di-FIX hari ini (6 commits)

### `c388751` (yesterday late) — SL guard via stored extremes
**Bug**: `_evaluate_trade` augment high/low dari latest bar tapi tidak check SL.
Candle iteration loop kosong kalau ga ada bar baru sejak `last_check_at`.
Result: SL hits missed, trades expired di harga jauh worse than SL.

**Fix**: Final guard setelah candle loop, sebelum expiry check. If
`upd.low_after_open <= cur_sl` (LONG) atau `upd.high_after_open >= cur_sl`
(SHORT), close at cur_sl.

**Bonus retroactive**: trade `0c7476eb` (history SHORT) corrected from
EXPIRED -3.01% to SL -1R via direct Supabase PATCH.

### `208710b` — single-position + 3 critical bug fixes

**Bug 1**: `promote_signal_for_ea` lupa update `direction` field. Per-style
strategy decision was LONG/SHORT but rcs_signals.direction stayed at RCS
indicator value (often WAIT). EA would have executed WAIT-direction signals
at random side. Live evidence: signal id=2053 PICKED_UP dengan direction=WAIT.
**Fix**: also UPDATE direction=decision.side in promote.

**Bug 2**: `bool(row.get("ea_enable_paper") or True)` — Python `False or True`
= True. User PATCH paper=false di DB tapi config endpoint tetap return True.
**Fix**: helper `_bool(field, default)` properly handles stored False.

**Bug 3**: stale signals (>180s) tetap di queue PENDING_PICKUP. After position
close, EA pickup oldest = stale signal at outdated entry. **Fix**: sweeper
di `/api/ea/next-signal` + `.gte(generated_at, now-180s)` filter +
`.in_(direction, [LONG, SHORT])` defense-in-depth.

**New logic**: `is_position_active(store)` di confluence.py. Daemon
runner.py call sebelum per-style EA promotion loop. Returns (True, reason)
if any rcs_executions.status IN ('OPEN', 'PENDING_BROKER') OR fresh
PENDING_PICKUP/PICKED_UP signal exists. Skip all promotions if active.
Plus in-cycle re-check (after first style promotes, subsequent styles
skip same-cycle).

### `aaf1196` — UI EA status panel

`/portfolio` page sekarang punya panel "EA / MT5 Demo" di paling atas:
- Power icon hijau saat EA online (heartbeat <5min)
- Mode badge: LIVE / PAPER / OFF
- Account login + balance + equity + open positions
- Risk per trade % + estimasi USD risk
- Estimasi lot/trade (computed dari risk + SL distance + 100oz contract)
- Leverage label "1 : Unlimited (Exness demo)"
- Daily loss kill-switch threshold
- Min confidence promote
- Trailing/BEP pip settings

### `b531f98` — EA_GO_LIVE_SETUP.md

Step-by-step manual MT5 attach untuk kalau user mau lakukan sendiri.
Now superseded by `attach_ea_mt5.py` for fully-automated approach, but
docs still useful for understanding what EA needs.

### `05b116f` — scripts/attach_ea_mt5.py (auto MT5 setup)

**Untuk siapa**: future Claude session di PC rumah, OR user kalau MT5
restart bikin EA detach.

**Apa yang dilakukan**: pywinauto-based automation —
1. Connect to running MT5 process
2. Find Navigator TreeView (SysTreeView32, native MFC)
3. Walk tree, find item "DextradeEA"
4. Compute screen coords (tree.rectangle + item.client_rect)
5. Activate XAUUSDm chart
6. Double-click EA item → MT5 Attach to chart
7. Wait for confirm dialog (filter by MT5 process_id)
8. Click OK button

**Tested live 2026-05-07 09:41 WIB** — EA heartbeat received within 60s
of script run.

**Pre-conditions**: MT5 running, chart XAUUSDm any TF open, DextradeEA
compiled in Navigator.

**Failed approaches before pywinauto succeeded** (documented in commit
message untuk future reference): SendKeys, UIAutomation, MSAA, raw Win32
TVM_GETROOT — semua gagal di MT5 native MFC controls.

## Config yang di-flip (Supabase REST PATCH)

`app_settings` (user_id='default'):

```json
{
  "ea_enable_execution": true,
  "ea_enable_paper": false,
  "ea_max_open_positions": 1,
  "ea_max_trades_per_day": 10,
  "ea_risk_per_trade_pct": 1.0,
  "ea_min_confidence_pct": 65,
  "ea_daily_loss_pct": 5.0,
  "ea_enable_break_even": true,
  "ea_break_even_trigger_pips": 50,
  "ea_break_even_lock_pips": 5,
  "ea_enable_trailing": true,
  "ea_trailing_trigger_pips": 100,
  "ea_trailing_distance_pips": 30
}
```

User explicit spec: $1000 demo modal, leverage Unlimited (manual MT5 setting).

## Data cleanup hari ini (manual SQL)

1. **2 corrupt rcs_signals** id=2053 + id=2054 (direction=WAIT but
   is_executable=true) marked EXPIRED. Cause: `promote_signal_for_ea` Bug 1
   above. Now fixed at code level + data cleaned.
2. **History SHORT trade 0c7476eb** (yesterday) updated from EXPIRED to
   SL_HIT (was -3.01% became -1.000R / -0.16%) — accurate to actual price
   action (high $4711.30 violated sl $4691.90 long before expiry).

## Backup MT5 config

Di `~/.mt5-backup-2026-05-07-0930/` — common.ini, settings.ini, Profiles/.
Restore kalau MT5 setup messed up.

## Hal-hal yang Claude di PC kantor BUTUH tahu

### TIDAK perlu dilakukan di PC kantor

- ❌ Jangan run `daemon.main` di PC kantor — akan compete dengan PC rumah daemon
  via Supabase active-passive lock (migration 007), bisa cause race
- ❌ Jangan run `recalibrate_gap.py` di kantor — file gap di PC rumah, gak akan
  ada efek
- ❌ Jangan run `attach_ea_mt5.py` di kantor — gak ada MT5 di sana
- ❌ Jangan PATCH app_settings.ea_* — udah di-set sesuai spec user

### Yang BISA dilakukan di PC kantor

- ✅ Edit code di repo (UI fixes, agent prompts, etc.)
- ✅ Deploy via Vercel push (frontend changes auto-deploy, backend di rumah
  pull via git pull --rebase)
- ✅ Monitor sistem via web (`https://yeehee.vercel.app/portfolio` panel "EA /
  MT5 Demo")
- ✅ Monitor via Supabase REST API queries
- ✅ Edit migrations + apply via Supabase dashboard

### Kalau perlu coordinate antar Claude sessions

Memory `setup_topology.md` udah persistent — Claude future di mana pun
auto-load. Kalau ada change yang relevan di PC rumah, tambah feedback
memory atau project memory file.

## Yang BELUM dilakukan (defer)

- **First auto-execution observation** — sistem ready, tapi belum lihat actual
  signal qualifying (LONG/SHORT conf ≥65%) execute end-to-end. Background
  monitor task gua udah jalan untuk catch first heartbeat. Kalau session
  habis, monitor mati — perlu re-launch atau user check Supabase manually.
- **Daemon auto-restart on PC reboot** — sekarang detached process, mati
  saat PC reboot. Untuk truly persistent, perlu Windows Service via NSSM
  atau scheduled task. Defer.

## Risk awareness

- Demo account $1000, leverage Unlimited
- 1% risk per trade = max $10 loss per trade
- Single-position = no over-trading
- Daily kill switch -5% = max -$50/day
- Worst case demo balance jadi 0 — tidak ada real money at risk
- Yesterday EA crashed $500 → $317 (-36%) dalam 90 menit. Diagnosis: **belum
  jelas root cause** (could be position sizing miscalc, broker leverage too
  high, slippage). Perlu monitor first few trades carefully untuk verify
  ComputeLotSize math di EA mq5 = sane.

## Daftar file diff session ini

```
NEW:
+ SESSION_STATUS_2026-05-07.md (this file)
+ scripts/attach_ea_mt5.py
+ EA_GO_LIVE_SETUP.md
+ .mt5-backup-2026-05-07-0930/ (gitignored, di working tree only)

MODIFIED (cumulative dari c388751 → 05b116f):
M daemon/trade_tracker.py    (SL guard + GLD sanity)
M daemon/runner.py           (single-position guard, sanity, stooq tier 2.5)
M daemon/main.py             (handle _skip return)
M data/price_fetcher.py      (stooq fetcher, scale validation)
M rcs/confluence.py          (is_position_active, direction update fix)
M rcs/src/execution_api.py   (sweeper, paper bug, direction filter)
M web/lib/server-api.ts      (getEaHeartbeat, getEaConfig, ActiveTrade
                              add original_sl/sl_moved_at)
M web/app/portfolio/page.tsx (pass eaHeartbeat + eaConfig)
M web/app/portfolio/PortfolioClient.tsx (EaStatusCard, optimistic close,
                                          trailing badge)
M web/app/HomeClient.tsx     (HeroCard isExecuted, SWR 60s)
M web/app/signals/SignalsClient.tsx (SWR 60s)
M web/components/HeroCard.tsx (lifecycle 180s TTL)
M NEXT_TASKS.md              (cumulative session notes)
M SESSION_STATUS_2026-05-06.md (clarification + status updates)
```

## Untuk Claude session future (di mana pun)

Read in order:
1. **MEMORY.md** + `setup_topology.md` (auto-loaded as project memory)
2. This file (`SESSION_STATUS_2026-05-07.md`) untuk state hari ini
3. `EA_GO_LIVE_SETUP.md` kalau perlu re-attach EA
4. Latest 3-5 commits via `git log --oneline` untuk understand recent changes
5. `NEXT_TASKS.md` untuk pending backlog

Tidak perlu baca history commits dari awal repo — cumulative state ada di
file2 ini. Hemat context.
