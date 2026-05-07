# EA Go-Live Setup — Step by Step (2026-05-07)

> **Lokasi**: PC RUMAH (`DESKTOP-LHVGFIT`, worker). Setup di sini, bukan PC kantor.
>
> **Status sebelum setup**: backend ready (commits `208710b` + `aaf1196`),
> FastAPI :8001 running, daemon running, app_settings configured.
> **Yang kurang**: EA attached ke MT5 chart + WebRequest URL whitelisted.

## Pre-flight check (verify gua benar)

Buka PowerShell, paste:

```powershell
# 1. Backend services running
Get-Process python | Where-Object { $_.StartTime -gt (Get-Date).AddHours(-4) }
# Expect: 2-3 python processes (FastAPI + daemon + maybe recalibrator)

# 2. FastAPI alive
Invoke-WebRequest http://localhost:8001/healthz -UseBasicParsing | Select-Object -ExpandProperty Content

# 3. Config loaded correctly (enable_paper SHOULD BE FALSE)
Invoke-WebRequest "http://localhost:8001/api/ea/config?ea=ea-mt5-pcrumah-1" -UseBasicParsing | Select-Object -ExpandProperty Content
```

Kalau salah satu fail, balik ke `SESSION_STATUS_2026-05-06.md` restart procedure.

## STEP 1 — MT5 chart setup (~2 menit)

1. Buka MetaTrader 5 (Exness Demo Hedge, account `413737626` atau yang baru lo
   set ke $1000 modal + leverage Unlimited).
2. **Drag XAUUSDm** dari Market Watch (kolom kiri) ke area chart kosong (abu-abu)
   → candle muncul.
3. **Klik tombol "Algo Trading"** di toolbar atas (sekarang ⚠️ kuning).
   Setelah klik harus jadi 🟢 hijau. Kalau masih kuning, klik sekali lagi.

## STEP 2 — Whitelist WebRequest URL (~30 detik)

1. **Tools → Options → Expert Advisors** (Ctrl+O).
2. Centang **"Allow WebRequest for listed URL"**.
3. Tambahkan 2 URL ini (klik tombol `+`, paste, OK):
   ```
   http://localtest.me:8001
   http://localhost:8001
   ```
4. OK keluar dari Options.

## STEP 3 — Drag EA ke chart (~30 detik)

1. Di Navigator (kolom kiri), expand **Expert Advisors**, cari **DextradeEA**.
2. **Drag DextradeEA** ke chart XAUUSDm (yang udah ke-load).
3. Pop-up muncul → tab **"Common"** → centang **"Allow Algo Trading"**.
4. (Optional) Tab "Inputs" — biarkan default. Default values:
   - `EaInstanceId = ea-mt5-pcrumah-1`
   - `ApiBaseUrl = http://localtest.me:8001`
   - `MagicNumber = 20260505`
5. Klik **OK**.
6. **Verify**: pojok kanan-atas chart ada smiley face 😀 — EA running.
   Kalau ada ⛔ atau ❌, klik kanan chart → Expert Advisors → cek log.

## STEP 4 — Verify connectivity (~1 menit)

Setelah EA jalan, polling akan mulai dalam 30 detik. Verify:

### A. Daemon log shows EA hits
```powershell
Get-Content "$HOME\yeehee-daemon\logs\execapi-*.log" -Tail 20
# Expect lines like:
# INFO:     127.0.0.1:xxxxx - "GET /api/ea/config?ea=ea-mt5-pcrumah-1 HTTP/1.1" 200 OK
# INFO:     127.0.0.1:xxxxx - "POST /api/ea/heartbeat HTTP/1.1" 200 OK
# INFO:     127.0.0.1:xxxxx - "POST /api/spot/post HTTP/1.1" 200 OK
```

### B. Buka https://yeehee.vercel.app/portfolio
Di section paling atas "**EA / MT5 Demo**" panel:
- ⚡ Power icon hijau = EA online
- Mode badge "LIVE" hijau = real demo execution
- Account #413737626 + heartbeat age detik kecil
- Balance / Equity terisi
- Estimasi lot/trade muncul

Kalau panel masih "EA tidak terhubung" / kosong setelah 90 detik:
- MT5 chart Algo Trading masih kuning? Klik sampai hijau.
- WebRequest URL ke-add bener? Cek Tools → Options → Expert Advisors.
- Smiley face ada di chart? Kalau ⛔, EA error — cek tab "Experts" di MT5 bawah.

## STEP 5 — Tunggu signal pertama

Sistem auto-execute kalau:
- Signal direction LONG/SHORT (bukan WAIT)
- Confidence ≥ 65%
- Single-position policy: ga ada open position lain
- Stale signals (>180s) auto-expire (EA tidak akan ambil signal basi)

**Daemon push signal tiap ~3 menit**. Kalau confidence cukup, daemon promote
ke PENDING_PICKUP. EA polls /api/ea/next-signal tiap 30 detik, claim,
OrderSend ke broker. Result POSTed back ke /api/ea/report.

Eksekusi trade akan muncul di:
- `rcs_executions` table (Supabase)
- Portfolio page (active trades)
- MT5 chart (open position with arrow + line)

### Logic single-position (verified):
- Signal di jam 13:00, EA execute jam 13:00:30 (poll cycle), open posisi.
- Saat open posisi, daemon SKIP promotion semua signal baru sampai close.
- Signal baru tetap muncul di Beranda + Sinyal page (info only).
- Setelah position close (TP/SL/trailing/expiry), signal NEXT cycle promoted.

## Kalau ada masalah

### Mode masih PAPER walau config = LIVE
Restart FastAPI:
```powershell
# Kill old
taskkill /F /PID <PID FastAPI dari Get-Process>
# Relaunch via SESSION_STATUS_2026-05-06.md procedure
```

### EA opens, tapi langsung error / rejected
Cek `rcs_executions` rows dengan `status=REJECTED` + `rejected_reason`. Common:
- `Invalid stops` — broker reject kalau SL/TP terlalu dekat (broker minimum stop level)
- `Not enough money` — leverage atau lot perhitungan salah

### Lo mau panic stop semua execution
```sql
UPDATE app_settings SET ea_enable_execution=false WHERE user_id='default';
```
EA polls /api/ea/config tiap 60s, akan auto-stop. Or close MT5 entirely.

### Lo mau switch back ke paper mode (test only)
```sql
UPDATE app_settings SET ea_enable_paper=true WHERE user_id='default';
```
EA tetap log "execution" tapi ga kirim OrderSend ke broker.

## Knobs yang bisa lo tweak

Via Supabase REST PATCH `/rest/v1/app_settings?user_id=eq.default`:

| Field | Current | Constraint | Effect |
|---|---|---|---|
| `ea_min_confidence_pct` | 65 | 50-95 | Naikin = signal lebih jarang, kualitas lebih tinggi |
| `ea_risk_per_trade_pct` | 1.0 | 0.1-3.0 | Risk per trade % balance |
| `ea_max_trades_per_day` | 10 | 1-10 | Hard cap per UTC day |
| `ea_daily_loss_pct` | 5.0 | — | Kill switch saat balance turun X% dari starting |
| `ea_trailing_trigger_pips` | 100 | — | Profit pips sebelum trailing aktif (XAU $1 = 10 pips) |
| `ea_trailing_distance_pips` | 30 | — | Distance trailing SL behind price |
| `ea_break_even_trigger_pips` | 50 | — | Profit pips sebelum BEP move |

## Final note

Backend code di repo: commits `208710b` + `aaf1196`. Logic verified end-to-end.
Stuck data cleaned. Sistem stay clean sampai EA attached + signal qualifying.

**Risiko go-live di demo $1000 + leverage Unlimited:**
- Worst case 1 trade: 1% risk = $10 loss, dengan SL ATR-based ~$5-15 per oz.
- Lot size auto-computed by EA: ~0.05-0.10 lot (small).
- Kill switch 5% daily = max -$50/day.
- Single position = no over-trading.

Demo, jadi worst case = balance jadi 0. Ga ada money lost, cuma ego 😅.
