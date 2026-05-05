# RCS — REY Composite Signal

**Status**: v0.1 (composite, deployed) · v0.2 ML (deferred) · v1.0 MT5 EA (deferred)
**Lokasi**: `rcs/` di yeehee monorepo
**Output**: `rcs_signals` table di Supabase

---

## Apa itu RCS?

Indikator **pamungkas** buatan in-house yang **gabungin semua indikator yang udah ada di yeehee** jadi satu score tunggal. Bukan replacement untuk sistem 12-agent LLM — RCS berdiri di samping sebagai **referensi tambahan**.

**Filosofi**: setiap indikator punya bias sendiri. RSI bagus untuk momentum, EMA untuk trend, SMC untuk structure, intermarket untuk macro. RCS combine semua dengan weighting yang reasonable + per-regime tilt.

**Output**: `rcs_score ∈ [-1, +1]`
- `> +0.40` → LONG kuat
- `+0.20 .. +0.40` → LONG lemah
- `[-0.20, +0.20]` → WAIT (no clear edge)
- `-0.40 .. -0.20` → SHORT lemah
- `< -0.40` → SHORT kuat

---

## Status real per phase

| Phase | Apa | Status | Catatan |
|-------|-----|--------|---------|
| **v0.1 — Composite** | Weighted aggregation dari 6 komponen (trend/momentum/structure/intermarket/volatility/session) | ✅ **DEPLOYED** | Daemon compute setiap cycle, push ke `rcs_signals`. UI panel di `/signals` + `/more/rcs-monitor`. |
| **v0.1.1 — Outcome tracking** | Background job evaluate `rcs_signals.outcome` (TP1/TP2/SL/EXPIRED) | ⏳ TODO | Code stub di `rcs/outcome_tracker.py`, perlu cron job + price polling. |
| **v0.2 — ML enhancement** | Train XGBoost on RCS features → outcome. Auto-fit weights. | ⏳ DEFERRED | Setelah ada 500+ closed signals dengan outcome. Estimasi 4-6 jam kerja saat itu. |
| **v0.3 — Drift detection** | KL divergence feature distribution live vs training | ⏳ DEFERRED | Setelah v0.2. |
| **v1.0 — MT5 EA auto-execute** | Bot di MT5 polling rcs_signals + execute orders | ⏳ DEFERRED | Butuh user MT5 setup + EA testing. Spec di `RCS_MULTI_TF_ML_SPEC.md` Phase 10. |

---

## Komponen v0.1 (yang lagi jalan)

| Komponen | Bobot default | Source data | Logic |
|----------|---------------|-------------|-------|
| **Trend** | 25% | df_4h: EMA9/21/50/200 stack + ADX | Stack alignment count × ADX strength modulator |
| **Momentum** | 20% | df_15m: RSI14 + MACD hist | RSI zone (overbought/bullish/neutral/bearish/oversold) + hist sign |
| **Structure** | 20% | df_15m SMC: bull_sweep, fvg_bull, bos_up (recent 5 bars) | Sum of bullish/bearish events |
| **Intermarket** | 15% | features.intermarket.intermarket_score (DXY/TIPS/US10Y/VIX/etc) | Pass-through existing weighted score |
| **Volatility** | 10% | df_4h.atr14 vs 20-period rolling avg | Penalty kalau ATR ratio > 2.0 (whipsaw) atau < 0.4 (quiet) |
| **Session** | 10% | session label | Boost London/NY, penalty Asia |

**Per-regime tilt** (re-normalized):
- `trending_up/dn`: trend ×1.4, momentum ×1.2, structure ×0.7
- `ranging`: structure ×1.5, session ×1.3, trend ×0.6
- `volatile`: intermarket ×1.3, volatility ×1.5, momentum ×0.7
- `quiet`: structure + session boosted, trend + momentum dampened

---

## Cara kerja end-to-end (yang sudah jalan sekarang)

```
Daemon di PC rumah (every 5 min, on PRIMARY worker only):
  1. Fetch XAU + intermarket + COT + calendar
  2. Compute features (technical + SMC) — existing modules
  3. Compute RCS → rcs.composite.compute_rcs(...)
  4. Run 12-agent LLM debate (RCS sekarang ada di context sebagai 'rcs_composite_indicator')
  5. Push signal_bundles + rcs_signals + active_trades (kalau eligible)
       ↓
Vercel UI (yeehee.vercel.app):
  6. /signals page: SSR fetch latest signal_bundle + latest rcs_signal (parallel)
  7. Render SignalCards (12-agent output) + RcsPanel (RCS reference)
  8. /more/rcs-monitor: history + stats + breakdown drivers
```

---

## Yang lo perlu lakuin (jangan skip)

### 1. Apply migration 008 (REQUIRED)

Buka Supabase SQL editor → paste isi `supabase/migrations/008_rcs_tables.sql` → run.

Verify dengan:
```sql
select count(*) from rcs_signals;  -- expect 0 (tabel kosong, baru bikin)
```

### 2. Pull + restart daemon di PC rumah (REQUIRED)

Daemon harus pakai code latest dengan folder `rcs/`. Run di PowerShell:

```powershell
Set-Location $HOME\yeehee-daemon
git pull origin main
.\.venv\Scripts\python.exe -m pip install -r rcs\requirements.txt --quiet --upgrade

# Stop daemon lama
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*daemon.main*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Start fresh
.\.venv\Scripts\python.exe -m daemon.main
```

### 3. Verify bahwa RCS aktif

Di log daemon, cari baris:
```
[rcs] score=+0.546 dir=LONG conf=54% top=['trend: EMA stack fully bullish, ADX=28 dev (s=+0.70 w=0.32)']
[rcs] pushed signal id=1 tf=M15 dir=LONG score=+0.546 conf=54%
```

Buka https://yeehee.vercel.app/more/rcs-monitor — harus muncul "Sinyal terkini" card.

---

## v0.2 future: ML enhancement (deferred)

Setelah accumulate 500+ closed `rcs_signals` dengan `outcome` populated:

1. **Outcome tracker** (TODO):
   - Background job tiap 30 menit
   - Untuk setiap signal `outcome IS NULL`: cek apa price udah hit `tp1`, `tp2`, atau `sl`
   - Update outcome + `prediction_correct`

2. **Train weight optimizer**:
   - Input: feature_snapshot (component scores) + actual outcome
   - Algo: XGBoost classification (3-class: TP1_HIT/SL_HIT/EXPIRED)
   - Output: optimal weights per regime
   - Replace manual `DEFAULT_WEIGHTS` + `REGIME_WEIGHT_TILT` dengan trained values
   - Save model to `rcs/models/composite_weights_v1.pkl`

3. **Drift detection**:
   - Weekly: compute KL divergence feature distribution this week vs training set
   - If drift > threshold → auto-pause + retrain

Estimasi: 6-8 jam kerja saat data sudah cukup.

---

## v1.0 future: MT5 auto-execute EA (deferred)

Spec lengkap di `RCS_MULTI_TF_ML_SPEC.md` Phase 10.

Singkatnya:
1. EA (MQL5 source di `rcs/ea/DextradeEA.mq5`) running di MT5 client lo
2. EA polling FastAPI endpoint di home PC → fetch signal `WHERE execution_status = 'PENDING_PICKUP'`
3. EA execute order (with user-configured lot size from Kalkulator profile)
4. EA report execution back ke `rcs_executions` table
5. Risk validation: min SL distance, max daily loss, news filter, kill switch

Pre-requisite:
- v0.1 stable + lo confident dengan output quality
- 30+ hari paper test (manual decisions, observe RCS prediction vs actual market)
- Setup MT5 demo/live account
- Test EA di demo account 2-4 minggu sebelum live

---

## File structure

```
rcs/
├── __init__.py              # Public API: compute_rcs, RCSResult
├── composite.py             # Core indicator (weighted aggregation)
├── persistence.py           # push_rcs_signal + get_latest_rcs
├── config.yaml              # MT5 broker config + thresholds (used by Phase 1.0+ MT5 connector)
├── requirements.txt         # ML stack deps (XGBoost, scikit-learn, MetaTrader5)
├── .env.example             # Template untuk credentials
├── .gitignore               # Exclude models/*.pkl, data/*.parquet
├── README.md                # ← lo lagi baca
├── data/                    # Empty (Phase v0.2+ akan isi parquet OHLCV)
├── models/                  # Empty (Phase v0.2+ akan isi xgb_*.pkl)
├── notebooks/               # Empty (untuk EDA waktu v0.2)
├── tests/                   # Empty (TODO: pytest unit tests)
├── ea/                      # Empty (Phase v1.0 akan isi DextradeEA.mq5)
└── src/                     # Phase v0.2+ ML pipeline
    ├── __init__.py
    └── mt5_connector.py     # Stub — works in mock mode without MT5 lib
```

---

## Honest disclaimers

- **v0.1 sudah deployed dan jalan** — daemon compute setiap cycle, UI panel rendering, monitor page exists.
- **Calibration belum di-validate** — kita belum ada 500 closed signals dengan outcome buat verify "RCS bilang 70% confidence, actual 70% benar?". Sampai itu validate, treat RCS as HEURISTIC, not statistical truth.
- **No backtest yet** — manual heuristic weights belum di-test on historical data. Phase v0.2 will do this properly via walk-forward CV.
- **v0.2/v1.0 deferred bukan dimatiin** — semua schema (rcs_signals, rcs_models, rcs_executions, rcs_ea_heartbeat) sudah disiapkan. Pipa data + UI integration sudah ada. Saat lo siap go ML/EA, fondasi sudah ada.
- **NO promises tentang accuracy** — gold market regime-dependent. Indikator yang work di 2024 mungkin gagal di 2026. Kelola expectation: directional accuracy 50-58% sudah respectable, > 65% probably overfit.
