# RCS — REY Composite Signal (Multi-TF ML Edition)

**Versi:** 1.2 (refactored: isolated project + MT5 integration ready)
**Owner:** Reyhan Wijaya
**Project:** **yeehee** (a.k.a. **dextrade**) — XAU/USD trading signal platform
**Pendekatan:** Multi-Timeframe (M5 + M15 + H1) + XGBoost + Logistic Regression baseline
**Status:** Spec final untuk dikerjakan oleh Claude Code

---

## 🚧 ISOLASI PROJECT (CLAUDE CODE WAJIB BACA)

**RCS adalah komponen INTI dari yeehee/dextrade. Project ini berdiri sendiri, TIDAK terhubung dengan project lain manapun yang dimiliki Reyhan.**

### Aturan isolasi (HARDCODE):

1. **Folder kerja:** `D:\dextrade\rcs\` — JANGAN nyimpen di folder project lain
2. **Supabase:** akun & project terpisah (yeehee-dedicated). Credentials di `.env` lokal yeehee, bukan dari mana-mana.
3. **Vercel:** akun & project terpisah (yeehee-dedicated). Deployment yeehee.vercel.app.
4. **GitHub repo:** `proreyhanwijaya111/yeehee` (sudah ada). JANGAN push ke repo lain.
5. **Telegram bot:** bot terpisah khusus yeehee, dengan token sendiri di `.env` yeehee.
6. **API keys (data provider, dll):** dedicated untuk yeehee, jangan share dari project lain.
7. **Codebase:** JANGAN import, reference, atau copy-paste pattern dari codebase lain. Bahkan kalau ada utilitas yang mirip, rewrite untuk yeehee dari awal supaya gak ada cross-contamination.

**Kalau Claude Code menemukan referensi atau import dari project lain di codebase yeehee, harus dianggap BUG dan di-flag, bukan di-merge.**

---

## 🎯 Scope (PENTING — BACA DULU)

**RCS adalah PURE INDICATOR**, bukan trading system. Tugasnya cuma satu:

```
INPUT:  OHLCV data (M5 + M15 + H1) dari MT5 broker
OUTPUT: { direction, entry, sl, tp1, tp2, confidence%, probabilities, top_features }
```

**RCS TIDAK menangani:**
- ❌ Lot size calculation
- ❌ Account risk percentage
- ❌ Position sizing
- ❌ Money management profile
- ❌ Daily loss limits

Itu semua urusan **Kalkulator** page (existing di yeehee). Indikator outputnya level (entry/SL/TP), user yang decide pakai berapa lot di Kalkulator.

**Future (Phase 10):** Output RCS akan di-konsumsi oleh **MT5 Expert Advisor (EA)** untuk auto-execution. Spec ini sudah dirancang dengan struktur supaya transisi ke auto-execution clean (lihat Phase 10).

---

## ⚠️ Realita Teknis (BACA DULU)

1. **Target realistis** untuk indikator yang well-built di gold M15:
   - Directional accuracy: 52-60% (NOT >70%)
   - Precision per kelas (LONG, SHORT): >55%
   - Calibration: kalau model bilang prob 70%, actual frequency outcome harus ~70%
2. **Kalau setelah training dapat accuracy >65% atau angka2 luar biasa lainnya, probably overfit.** Jangan deploy. Investigate dulu.
3. **Live performance akan lebih buruk dari backtest**, biasanya 15-30% lebih rendah karena slippage, news, market regime change.
4. Spec ini wajib di-execute **berurutan**. Phase berikutnya tidak boleh mulai sebelum phase sebelumnya PASS validation.

---

## Tech Stack (ALL YEEHEE-DEDICATED)

| Layer | Tool | Lokasi | Account/Instance |
|---|---|---|---|
| Data source | MetaTrader 5 (broker live/demo account) | Home PC | yeehee MT5 account |
| Data ingestion | Python + MetaTrader5 lib | Home PC daemon | yeehee folder |
| Feature engineering | Python + pandas + pandas-ta | Home PC | — |
| ML training | Python + XGBoost + scikit-learn + Optuna | Home PC (offline) | — |
| Model storage | joblib `.pkl` files | Home PC + Supabase Storage | yeehee Supabase |
| Inference service | FastAPI (Python) | Home PC daemon | yeehee folder |
| Signal storage | Supabase Postgres | Cloud | **yeehee-dedicated Supabase project** |
| Frontend | Next.js (existing yeehee codebase) | Vercel | **yeehee-dedicated Vercel project** |
| Telegram | Bot dedicated | — | **yeehee-dedicated bot** |
| Future EA execution | MQL5 Expert Advisor on MT5 | Home PC MT5 | yeehee MT5 |
| Monitoring | Custom dashboard di yeehee `/more/rcs-monitor` | Vercel | — |

**Why Python di home PC, bukan Vercel:** XGBoost training butuh resource & waktu lama (10-30 menit per run). Vercel function timeout 10s. Home PC udah jadi production server (running `dextrade-daemon` services).

**Why MT5 sebagai data source utama (BUKAN Twelve Data atau lainnya):**
- Real broker data → matching broker yang dipakai user untuk trading nanti
- Symbol, spread, time zone, point value SAMA dengan execution environment
- Future EA akan jalan di MT5 yang sama → consistency antara training data & live execution
- Gratis (cuma butuh akun broker, bahkan demo account cukup buat data historis)

**Flow data (current scope, manual execution):**
```
Home PC daemon (every 5 min):
  1. Fetch latest M5/M15/H1 candle dari MT5 (MetaTrader5 Python lib)
  2. Compute features
  3. Run inference (load model.pkl, predict)
  4. Apply sanity checks (price deviation, news filter, time-of-day)
  5. Push signal ke yeehee Supabase if valid
       ↓
Vercel (Next.js yeehee):
  6. Read from yeehee Supabase
  7. Render di yeehee.vercel.app/signals page
  8. Send to yeehee Telegram bot if confidence > threshold
       ↓
User:
  9. Manual decide: execute? skip? Pakai berapa lot? (decide di Kalkulator yeehee)
  10. Open trade manually di MT5
```

**Future flow (Phase 10, auto-execution):**
```
... step 1-5 sama ...
  6. EA on MT5 polling FastAPI on home PC
  7. EA pickup signal → execute trade dengan lot size sesuai pre-config user
  8. EA report execution result back ke yeehee Supabase (rcs_executions table)
  9. Frontend monitoring real-time di /more/rcs-monitor
```

---

## Phase 0: Persiapan Project (1 jam)

### 0.1 Folder structure di home PC

**Lokasi:** `D:\dextrade\rcs\` (dedicated yeehee/dextrade folder, tidak di mix dengan folder project lain)

```
D:\dextrade\rcs\
├── data\
│   ├── raw\              # Raw candle data dari MT5 (parquet)
│   ├── features\         # Engineered features
│   └── labels\           # Triple barrier labels
├── models\
│   ├── xgb_m5.pkl
│   ├── xgb_m15.pkl
│   ├── xgb_h1.pkl
│   ├── logreg_m5.pkl     # Baseline models
│   ├── logreg_m15.pkl
│   └── logreg_h1.pkl
├── src\
│   ├── mt5_connector.py        # MT5 connection & symbol resolution
│   ├── data_ingestion.py
│   ├── feature_engineering.py
│   ├── labeling.py
│   ├── cross_validation.py
│   ├── training.py
│   ├── evaluation.py
│   ├── inference.py
│   ├── daemon.py               # Main signal generation daemon
│   └── execution_api.py        # FastAPI for future EA polling (Phase 10)
├── ea\                          # MQL5 Expert Advisor (Phase 10)
│   └── DextradeEA.mq5
├── notebooks\                   # Jupyter notebooks untuk EDA
├── tests\
├── config.yaml                  # Broker symbol, timezone, model paths
├── .env                         # yeehee Supabase, Telegram, MT5 credentials
├── requirements.txt
└── README.md
```

### 0.2 Dependencies (`requirements.txt`)

```
pandas==2.2.0
numpy==1.26.4
pandas-ta==0.3.14b
scikit-learn==1.4.0
xgboost==2.0.3
optuna==3.5.0
joblib==1.3.2
fastapi==0.110.0
uvicorn==0.27.0
supabase==2.4.0
python-dotenv==1.0.1
pyarrow==15.0.0
matplotlib==3.8.2
seaborn==0.13.2
MetaTrader5==5.0.45
pytz==2024.1
```

### 0.3 Config file (`config.yaml`)

Penting untuk MT5 broker compatibility (broker beda punya symbol & spec beda):

```yaml
mt5:
  # Broker symbol untuk gold (CEK BROKER LO!) - common variants:
  # - "XAUUSD" (most brokers)
  # - "XAUUSD." (Tickmill, IC Markets dengan suffix)
  # - "XAUUSDm" (Exness micro)
  # - "GOLD" (some brokers)
  symbol: "XAUUSD"

  # Point size (gold biasanya 0.01 = 1 pip, tapi cek broker lo)
  point_size: 0.01

  # Tick value untuk 1 lot (USD per 1 point movement)
  # Cek di MT5: SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE)
  tick_value_per_lot: 1.0

  # Min/max lot, lot step (cek SymbolInfo)
  min_lot: 0.01
  max_lot: 100.0
  lot_step: 0.01

  # Stop level: minimum SL/TP distance dari current price (in points)
  # Cek SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL)
  stops_level_points: 30

  # Server timezone offset dari UTC (broker biasanya GMT+2 atau GMT+3)
  server_tz_offset_hours: 2

  # Display timezone untuk UI yeehee
  display_tz: "Asia/Jakarta"  # WIB (UTC+7)

data:
  history_years: 3
  timeframes: ["M5", "M15", "H1"]

model:
  m5_path: "models/xgb_m5.pkl"
  m15_path: "models/xgb_m15.pkl"
  h1_path: "models/xgb_h1.pkl"

inference:
  m5_interval_seconds: 300
  m15_interval_seconds: 900
  h1_interval_seconds: 3600
  confidence_threshold_telegram: 65

api:
  port: 8001
  ea_polling_endpoint: "/api/ea/next-signal"
```

### 0.4 Supabase tables (run SQL di yeehee Supabase Studio)

**⚠️ Pastikan login ke yeehee-dedicated Supabase project, BUKAN project lain.**

```sql
-- ====================================
-- SIGNAL TABLES (RCS pure indicator)
-- ====================================

-- Candle data (cache di yeehee Supabase, optional — bisa juga di local parquet aja)
CREATE TABLE rcs_candles (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL DEFAULT 'XAUUSD',
  timeframe TEXT NOT NULL CHECK (timeframe IN ('M5', 'M15', 'H1')),
  timestamp TIMESTAMPTZ NOT NULL,
  open NUMERIC(10,3) NOT NULL,
  high NUMERIC(10,3) NOT NULL,
  low NUMERIC(10,3) NOT NULL,
  close NUMERIC(10,3) NOT NULL,
  volume BIGINT,
  spread INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(symbol, timeframe, timestamp)
);

CREATE INDEX idx_rcs_candles_lookup ON rcs_candles(symbol, timeframe, timestamp DESC);

-- Live signals (output indikator yang ditampilkan di yeehee)
CREATE TABLE rcs_signals (
  id BIGSERIAL PRIMARY KEY,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  timeframe TEXT NOT NULL CHECK (timeframe IN ('M5', 'M15', 'H1')),
  broker_symbol TEXT NOT NULL,         -- e.g., "XAUUSD" or broker variant

  -- Inputs at generation time
  spot_price NUMERIC(10,3) NOT NULL,
  atr_14 NUMERIC(10,3) NOT NULL,

  -- Model outputs (PURE INDICATOR)
  prob_long NUMERIC(5,4) NOT NULL,
  prob_short NUMERIC(5,4) NOT NULL,
  prob_neutral NUMERIC(5,4) NOT NULL,
  rcs_score NUMERIC(5,4) NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT', 'WAIT')),

  -- Predicted price levels (where indicator predicts price will reach)
  entry NUMERIC(10,3),
  sl NUMERIC(10,3),                    -- Invalidation level
  tp1 NUMERIC(10,3),                   -- Conservative target
  tp2 NUMERIC(10,3),                   -- Extended target

  -- Distance in points (for EA easy consumption)
  sl_points INT,                       -- abs(entry - sl) / point_size
  tp1_points INT,
  tp2_points INT,

  -- Confidence & explainability
  confidence_pct INT NOT NULL CHECK (confidence_pct BETWEEN 0 AND 95),
  feature_snapshot JSONB,
  shap_top_5 JSONB,
  model_version TEXT NOT NULL,

  -- Execution gating (Phase 10 ready)
  is_executable BOOLEAN DEFAULT FALSE, -- TRUE = EA boleh ambil signal ini
  execution_status TEXT DEFAULT 'NOT_FOR_EXECUTION' CHECK (execution_status IN (
    'NOT_FOR_EXECUTION',  -- Manual mode (Phase 1-9, current scope)
    'PENDING_PICKUP',     -- Available untuk EA (Phase 10)
    'PICKED_UP',          -- EA udah claim
    'EXECUTED',           -- Trade open di MT5
    'REJECTED',           -- EA tolak (filter, broker error, dll)
    'EXPIRED'             -- Signal kadaluarsa (>5 min for M5, dll)
  )),

  -- Outcome tracking (untuk evaluasi indicator quality, BUKAN PnL trading)
  outcome TEXT CHECK (outcome IN ('TP1_HIT', 'TP2_HIT', 'SL_HIT', 'EXPIRED', 'PENDING')),
  outcome_price NUMERIC(10,3),
  outcome_at TIMESTAMPTZ,
  prediction_correct BOOLEAN
);

CREATE INDEX idx_rcs_signals_recent ON rcs_signals(generated_at DESC, timeframe);
CREATE INDEX idx_rcs_signals_outcome ON rcs_signals(outcome) WHERE outcome IS NULL;
CREATE INDEX idx_rcs_signals_pickup ON rcs_signals(execution_status, generated_at DESC)
  WHERE execution_status = 'PENDING_PICKUP';

-- ====================================
-- EXECUTION TABLES (Phase 10 — auto-trade)
-- Empty for now, populated saat EA dibangun
-- ====================================

CREATE TABLE rcs_executions (
  id BIGSERIAL PRIMARY KEY,
  signal_id BIGINT REFERENCES rcs_signals(id),

  -- MT5 trade info
  mt5_ticket_id BIGINT UNIQUE,
  mt5_symbol TEXT NOT NULL,
  mt5_account_login BIGINT,            -- which account executed (multi-account future)

  -- Execution details
  requested_at TIMESTAMPTZ NOT NULL,
  executed_at TIMESTAMPTZ,
  execution_price NUMERIC(10,3),       -- actual fill (may differ from entry due to slippage)
  execution_lot NUMERIC(8,2) NOT NULL,
  execution_sl NUMERIC(10,3),
  execution_tp NUMERIC(10,3),
  slippage_points INT,                 -- (execution_price - signal.entry) / point_size

  -- Lifecycle
  status TEXT NOT NULL CHECK (status IN (
    'PENDING_BROKER',  -- order sent, waiting fill
    'OPEN',            -- trade running
    'CLOSED_TP',       -- closed at TP
    'CLOSED_SL',       -- closed at SL
    'CLOSED_MANUAL',   -- user closed manually
    'CLOSED_TRAILING', -- closed by trailing stop
    'CLOSED_NEWS',     -- closed by news filter pre-close
    'REJECTED'         -- broker rejected
  )),

  -- Close info
  closed_at TIMESTAMPTZ,
  close_price NUMERIC(10,3),
  close_reason TEXT,

  -- PnL (broker-reported)
  pnl_money NUMERIC(12,2),             -- in account currency
  pnl_points INT,
  commission NUMERIC(8,2),
  swap NUMERIC(8,2),

  -- Risk metadata (recorded at execution time, BUKAN computed by RCS)
  account_balance_at_open NUMERIC(12,2),
  risk_pct_used NUMERIC(5,3),          -- user-defined risk %, recorded for audit
  rejected_reason TEXT,

  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_rcs_executions_signal ON rcs_executions(signal_id);
CREATE INDEX idx_rcs_executions_open ON rcs_executions(status) WHERE status = 'OPEN';
CREATE INDEX idx_rcs_executions_recent ON rcs_executions(executed_at DESC);

-- EA heartbeat untuk health monitoring
CREATE TABLE rcs_ea_heartbeat (
  id BIGSERIAL PRIMARY KEY,
  ea_instance_id TEXT NOT NULL,        -- unique per EA running
  account_login BIGINT NOT NULL,
  ts TIMESTAMPTZ DEFAULT NOW(),
  account_balance NUMERIC(12,2),
  account_equity NUMERIC(12,2),
  open_positions INT,
  is_paused BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_ea_heartbeat_recent ON rcs_ea_heartbeat(ts DESC);

-- ====================================
-- MODEL & MONITORING
-- ====================================

CREATE TABLE rcs_models (
  id BIGSERIAL PRIMARY KEY,
  version TEXT UNIQUE NOT NULL,
  timeframe TEXT NOT NULL,
  model_type TEXT NOT NULL,
  trained_at TIMESTAMPTZ NOT NULL,
  training_window_start DATE,
  training_window_end DATE,

  -- Performance metrics (INDICATOR QUALITY, bukan trading outcome)
  oos_accuracy NUMERIC(5,4),
  oos_precision_long NUMERIC(5,4),
  oos_precision_short NUMERIC(5,4),
  oos_recall_long NUMERIC(5,4),
  oos_recall_short NUMERIC(5,4),
  oos_f1_macro NUMERIC(5,4),
  oos_log_loss NUMERIC(6,4),
  oos_calibration_error NUMERIC(5,4),
  oos_tp_hit_rate NUMERIC(5,4),
  num_features INT,

  -- Storage
  storage_path TEXT,
  feature_list JSONB,
  hyperparameters JSONB,

  is_active BOOLEAN DEFAULT FALSE,
  notes TEXT
);

CREATE TABLE rcs_performance_daily (
  id BIGSERIAL PRIMARY KEY,
  date DATE NOT NULL,
  timeframe TEXT NOT NULL,
  num_signals INT NOT NULL,
  num_correct INT NOT NULL,
  num_tp_hit INT NOT NULL,
  num_sl_hit INT NOT NULL,
  num_expired INT NOT NULL,
  directional_accuracy NUMERIC(5,4),
  tp_hit_rate NUMERIC(5,4),
  avg_confidence NUMERIC(5,4),
  UNIQUE(date, timeframe)
);
```

---

## Phase 1: Data Ingestion via MT5 (2-3 jam)

### 1.1 MT5 Connector module (`src/mt5_connector.py`)

**Tugas:** centralize SEMUA komunikasi dengan MT5. Module lain tidak boleh import MetaTrader5 langsung — selalu lewat connector ini. Alasan: kalau nanti ganti broker atau symbol berubah, edit di satu tempat.

```python
import MetaTrader5 as mt5
import pandas as pd
import yaml
from datetime import datetime, timedelta
import pytz

class MT5Connector:
    def __init__(self, config_path='config.yaml'):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.symbol = self.cfg['mt5']['symbol']
        self.point_size = self.cfg['mt5']['point_size']
        self.server_tz = pytz.FixedOffset(self.cfg['mt5']['server_tz_offset_hours'] * 60)
        self._connected = False

    def connect(self, login, password, server):
        if not mt5.initialize():
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        if not mt5.login(login, password=password, server=server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

        # Verify symbol exists & enabled
        info = mt5.symbol_info(self.symbol)
        if info is None:
            raise RuntimeError(f"Symbol {self.symbol} not found in broker")
        if not info.visible:
            mt5.symbol_select(self.symbol, True)

        # Verify config matches broker reality
        actual_point = info.point
        if abs(actual_point - self.point_size) > 1e-9:
            print(f"⚠️  Config point_size {self.point_size} != broker actual {actual_point}")
            print(f"   Updating config in memory. Update config.yaml after verification.")
            self.point_size = actual_point

        self._connected = True
        return info

    def fetch_candles(self, timeframe, n_candles=100000):
        """
        Fetch historical candles from MT5.
        timeframe: 'M5', 'M15', 'H1'
        Returns DataFrame with index=timestamp (UTC), columns=[open,high,low,close,volume,spread]
        """
        tf_map = {
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'H1': mt5.TIMEFRAME_H1
        }
        rates = mt5.copy_rates_from_pos(self.symbol, tf_map[timeframe], 0, n_candles)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No data for {self.symbol} {timeframe}")

        df = pd.DataFrame(rates)
        # MT5 timestamps are in server time. Convert to UTC.
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        # Adjust from server tz to true UTC
        df['time'] = df['time'] - timedelta(hours=self.cfg['mt5']['server_tz_offset_hours'])
        df = df.set_index('time')
        df = df.rename(columns={'tick_volume': 'volume', 'real_volume': 'real_vol'})
        return df[['open', 'high', 'low', 'close', 'volume', 'spread']]

    def get_current_spot(self):
        """Latest tick — for sanity check di daemon."""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return None
        return (tick.bid + tick.ask) / 2

    def get_symbol_specs(self):
        """Return dict of broker specs untuk EA & Kalkulator integration."""
        info = mt5.symbol_info(self.symbol)
        return {
            'symbol': self.symbol,
            'point_size': info.point,
            'tick_value': info.trade_tick_value,
            'min_lot': info.volume_min,
            'max_lot': info.volume_max,
            'lot_step': info.volume_step,
            'stops_level': info.trade_stops_level,
            'spread_typical': info.spread,
            'digits': info.digits
        }
```

### 1.2 Data fetch script (`src/data_ingestion.py`)

Tugas:
1. Fetch 3 tahun XAU/USD untuk M5, M15, H1 (sekitar 220k, 70k, 18k candle)
2. Save ke parquet di `data/raw/` (UTC timestamps)
3. Run quality check:
   - No duplicate timestamps
   - No gaps >1 hour saat market hours (gold trading 24/5, gaps wajar weekend)
   - No price spike >5% dalam 1 candle (likely bad tick)
   - High >= max(open, close), Low <= min(open, close)
   - Spread reasonable (<200 points untuk gold)
4. Update incremental setiap run

**MT5 historical data limitation:** MT5 cuma simpan data sejauh "Charts / Max bars in history" setting. Default 100k bars. Untuk M5 = ~6 bulan. Solusi:
- Set Max bars to "Unlimited" di MT5 Tools → Options → Charts
- Atau kombinasi: download bulk dari MT5, supplement dengan sumber lain (Dukascopy historical) untuk older data

### 1.3 Quality check report

```
DATA QUALITY REPORT — XAUUSD (broker: <name>)
===============================================
M5:  220,154 candles, 2023-01-02 → 2026-05-04, 12 gaps detected (skipped)
M15:  73,384 candles, gaps: 4
H1:   18,346 candles, gaps: 1

Symbol specs (live):
  point_size: 0.01
  tick_value: 1.00 USD
  min_lot: 0.01, lot_step: 0.01
  stops_level: 30 points
  typical_spread: 25 points
===============================================
Status: PASS
```

Kalau **FAIL**, jangan lanjut ke phase berikutnya.

---

## Phase 2: Feature Engineering (4-6 jam)

### 2.1 Filosofi feature

Tiap timeframe dapet feature set sendiri. Tapi setiap signal generation, kita combine cross-TF features (e.g., "M5 long alignment dengan H1 trend?").

### 2.2 Feature list per TF (sama untuk M5/M15/H1, beda parameter)

#### Trend features (8)
- `ema_20`, `ema_50`, `ema_200` (raw values, akan dinormalisasi)
- `ema_20_50_diff_pct`: (ema_20 - ema_50) / close * 100
- `ema_50_200_diff_pct`: (ema_50 - ema_200) / close * 100
- `adx_14`
- `di_plus_minus_diff`: DI+ minus DI-
- `price_vs_ema_200_pct`: (close - ema_200) / ema_200 * 100

#### Momentum features (10)
- `rsi_14`
- `rsi_14_slope_5`: RSI now minus RSI 5 candles ago
- `macd_line`, `macd_signal`, `macd_hist`
- `macd_hist_slope_3`
- `stoch_k_14`, `stoch_d_3`
- `roc_10`
- `cci_20`

#### Volatility features (7)
- `atr_14`
- `atr_14_pct`: atr / close * 100
- `atr_14_percentile_100`: posisi ATR di rolling 100-period (0-1)
- `bb_width_20`: Bollinger band width
- `bb_position`: (close - bb_lower) / (bb_upper - bb_lower)
- `keltner_width`
- `range_5`: (high_5 - low_5) / close

#### Structure features (6)
- `dist_to_swing_high_20`: % dari close ke swing high 20-period
- `dist_to_swing_low_20`: % dari close ke swing low 20-period
- `dist_to_pivot_pp`: % ke daily pivot
- `dist_to_pivot_r1`, `dist_to_pivot_s1`
- `is_inside_bb`: 1 kalau close di antara BB bands, 0 kalau breakout

#### Time/cyclical features (5)
- `hour_sin`, `hour_cos`: encoding hour-of-day
- `dow_sin`, `dow_cos`: encoding day-of-week
- `is_session_overlap_lon_ny`: 1 kalau jam 19:30-23:00 WIB

#### Lag features (12 — important untuk capture sequence)
- `return_1`, `return_3`, `return_5`, `return_10`: % return n candle ago
- `rsi_lag_1`, `rsi_lag_3`, `rsi_lag_5`
- `macd_hist_lag_1`, `macd_hist_lag_3`
- `volume_lag_1`, `volume_lag_3`, `volume_ratio_5`: vol / 5-period avg

**Total per TF: 48 features**

### 2.3 Cross-TF features (8 — DIBUAT SAAT INFERENCE)

Saat generate signal di M5, kita lookup feature dari M15 & H1 *as of timestamp M5 sekarang*:

- `h1_trend_direction`: sign(h1.ema_50_200_diff)
- `h1_rsi_14`: nilai RSI H1 saat ini
- `m15_adx_14`: ADX M15
- `m15_macd_hist`: MACD hist M15
- `m5_h1_trend_alignment`: 1 kalau M5 trend searah H1, -1 kalau lawan, 0 kalau ranging
- `m15_h1_rsi_diff`: RSI M15 minus RSI H1
- `volatility_regime`: kategori (1=low, 2=normal, 3=high) berdasarkan ATR percentile H1
- `news_proximity_min`: menit ke high-impact news terdekat (negatif kalau setelah news)

**Total feature saat inference M5: 48 + 8 = 56 features**
**Total feature saat inference M15: 48 + 8 = 56 features**
**Total feature saat inference H1: 48 + 8 = 56 features**

### 2.4 Implementation rules

1. **Hindari lookahead bias mati-matian.** Setiap feature harus computable hanya dari data <= timestamp t. ZigZag, swing high/low, dll, harus pakai versi "online" (lihat candle ke belakang aja).
2. **Jangan normalize sebelum train/test split.** Normalisasi (StandardScaler) di-fit hanya di train, di-apply ke test.
3. **NaN handling:** drop rows pertama (warmup period 200 candle untuk EMA 200). Sisa NaN diisi forward-fill, terakhir resort 0.
4. **Save versi dengan metadata:**
```
data/features/xauusd_m5_features_v1.parquet
data/features/xauusd_m5_features_v1.meta.json   # feature names, generation date, raw data hash
```

### 2.5 Sanity check feature

Sebelum lanjut, cek:
- Tidak ada feature dengan correlation >0.95 (redundant, drop)
- Tidak ada feature dengan variance ~0 (useless)
- Distribusi feature tidak ada outlier ekstrem >10 std

---

## Phase 3: Labeling (Triple Barrier Method) (3-4 jam)

### 3.1 Why triple barrier

Cara amatir: label = sign(return n-candle ke depan). **Salah karena:** ngabaikan path-dependency. Kalau harga turun dulu kena SL baru naik, "true return" misleading.

Cara benar (López de Prado, Advances in Financial Machine Learning):
- Set **upper barrier** (TP) = entry + k_tp × ATR
- Set **lower barrier** (SL) = entry - k_sl × ATR
- Set **vertical barrier** (max hold time)
- Label = barrier yang ke-hit pertama:
  - +1 → TP hit (long good)
  - -1 → SL hit (long bad)
  - 0 → time expired (no signal)

### 3.2 Parameter per TF

| TF | k_tp | k_sl | max_hold_candles | Real-time horizon |
|---|---|---|---|---|
| M5 | 1.5 | 1.0 | 24 | 2 jam |
| M15 | 2.0 | 1.5 | 32 | 8 jam |
| H1 | 2.5 | 2.0 | 48 | 2 hari |

R:R = k_tp / k_sl: 1.5, 1.33, 1.25 (slightly aggressive untuk lower TF, more conservative untuk higher).

### 3.3 Implementation (`src/labeling.py`)

```python
def triple_barrier_label(df, k_tp, k_sl, max_hold):
    """
    Return DataFrame dengan kolom 'label' (-1, 0, +1) untuk LONG perspective.
    Untuk SHORT, swap interpretasi (label = -1 berarti SHORT good).

    KRITIS: jangan ada lookahead. Loop forward hanya, hanya pakai future data
    untuk DETERMINE LABEL, bukan untuk compute feature.
    """
    labels = np.zeros(len(df))
    atr = df['atr_14'].values
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values

    for i in range(len(df) - max_hold):
        entry = close[i]
        tp = entry + k_tp * atr[i]
        sl = entry - k_sl * atr[i]

        # Look forward up to max_hold candles
        for j in range(i+1, min(i+1+max_hold, len(df))):
            if high[j] >= tp:
                labels[i] = 1
                break
            if low[j] <= sl:
                labels[i] = -1
                break
        # else label stays 0 (time barrier)

    return labels
```

### 3.4 Two-class vs three-class

Pilih: **3-class** (LONG / SHORT / NEUTRAL).

Alasan: 2-class (just LONG vs SHORT) memaksa model selalu prediksi salah satu, padahal kondisi terbaik adalah "no trade". 3-class lebih jujur, dan kelas NEUTRAL = paling banyak (50-60% sample), yang membuat model belajar "kapan harus diem".

### 3.5 Class balance check

Distribusi label realistis:
- LONG: 18-25%
- SHORT: 18-25%
- NEUTRAL: 50-65%

Kalau jauh dari ini (e.g., LONG 60%), cek bug labeling. Kalau imbalance moderat, **jangan oversample/SMOTE** — pakai `class_weight='balanced'` atau `scale_pos_weight` di XGBoost.

---

## Phase 4: Train/Validation Split (2-3 jam)

### 4.1 Combinatorial Purged Cross-Validation (CPCV)

⚠️ **JANGAN PAKAI sklearn.model_selection.KFold atau train_test_split untuk time series financial data.** Itu menyebabkan label leakage karena trade di training set bisa overlap dengan trade di test set.

**Yang harus dipakai:** Purged K-Fold dengan embargo period.

### 4.2 Split strategy

Total data: ~2-3 tahun.

**Split:**
- Train+Val: 70% (oldest) → untuk Optuna hyperparameter search
- Out-of-Sample (holdout): 30% (newest) → SEKALI dipakai di akhir, jangan pakai untuk decision

**Dalam Train+Val:** 5-fold purged CV dengan embargo 1% (sekitar 2-3 hari untuk M5).

### 4.3 Implementation (`src/cross_validation.py`)

Pakai library `mlfinlab` atau implement manual:

```python
from sklearn.model_selection import KFold

def purged_kfold_indices(n_samples, n_splits=5, embargo_pct=0.01):
    """
    Return list of (train_idx, test_idx) tuples.
    Embargo: skip embargo_pct of samples around test set.
    """
    embargo = int(n_samples * embargo_pct)
    fold_size = n_samples // n_splits
    splits = []

    for i in range(n_splits):
        test_start = i * fold_size
        test_end = test_start + fold_size

        train_idx = list(range(0, max(0, test_start - embargo))) + \
                    list(range(min(n_samples, test_end + embargo), n_samples))
        test_idx = list(range(test_start, test_end))

        splits.append((train_idx, test_idx))

    return splits
```

### 4.4 Walk-forward validation (untuk final assessment)

Setelah dapat hyperparameter dari CPCV, lakukan walk-forward di OOS set:
- Train di 6 bulan pertama OOS → predict di bulan ke-7
- Train di 7 bulan → predict bulan ke-8
- Dst.
- Aggregate metrics across all forward predictions.

Ini realistis simulasikan production: model di-retrain tiap bulan dengan data terbaru.

---

## Phase 5: Model Training (4-6 jam)

### 5.1 Two-tier approach

Train dua model untuk tiap TF:

1. **Logistic Regression baseline** — interpretable, fast, sebagai sanity check. Kalau XGBoost gak significantly outperform LogReg, **berarti tidak ada non-linear pattern dan XGBoost overkill / overfit**.

2. **XGBoost** — main model, capture non-linear interactions.

### 5.2 LogReg baseline (`src/training.py`)

```python
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

logreg = LogisticRegression(
    multi_class='multinomial',
    class_weight='balanced',
    max_iter=1000,
    C=1.0,
    random_state=42
)
logreg.fit(X_train_scaled, y_train)
```

### 5.3 XGBoost dengan Optuna hyperparameter search

```python
import optuna
import xgboost as xgb

def objective(trial):
    params = {
        'objective': 'multi:softprob',
        'num_class': 3,
        'eval_metric': 'mlogloss',
        'max_depth': trial.suggest_int('max_depth', 3, 8),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
        'n_estimators': trial.suggest_int('n_estimators', 100, 800),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'gamma': trial.suggest_float('gamma', 0, 5),
        'reg_alpha': trial.suggest_float('reg_alpha', 0, 5),
        'reg_lambda': trial.suggest_float('reg_lambda', 0, 5),
        'random_state': 42,
        'tree_method': 'hist',
    }

    # Average score across CPCV folds
    scores = []
    for train_idx, val_idx in purged_kfold_indices(len(X), n_splits=5):
        model = xgb.XGBClassifier(**params)
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        # Custom metric: profit factor on validation set, NOT accuracy
        preds = model.predict_proba(X.iloc[val_idx])
        score = compute_profit_factor_from_probs(preds, y.iloc[val_idx])
        scores.append(score)

    return np.mean(scores)

study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=100, timeout=1800)  # 30 min max
```

**KRITIS:** Optuna optimize harus pakai metric yang relevant ke **kualitas prediksi indikator**, bukan accuracy biasa. Pilih salah satu:

- **F1-macro** — balance precision & recall across 3 kelas (LONG/SHORT/NEUTRAL)
- **Brier score** — kualitas kalibrasi probabilitas (lebih rendah = lebih baik)
- **TP hit rate** — % signal di mana TP1 ke-hit sebelum SL (paling relevant ke indicator quality)

**Rekomendasi:** pakai **TP hit rate** sebagai primary metric — paling jelas relasinya dengan "apakah indikator beneran predictive". Profit factor / Sharpe gak relevant di sini karena RCS bukan trading system.

### 5.4 Probability calibration

XGBoost output probabilitas yang sering miscalibrated. Kalibrasi pakai isotonic regression:

```python
from sklearn.calibration import CalibratedClassifierCV

calibrated = CalibratedClassifierCV(
    base_estimator=best_xgb_model,
    method='isotonic',
    cv=3
)
calibrated.fit(X_train, y_train)
```

Setelah kalibrasi, `predict_proba()` lebih akurat reflect actual frequency.

### 5.5 Save model

```python
import joblib
joblib.dump({
    'model': calibrated,
    'scaler': scaler,
    'feature_list': feature_names,
    'hyperparameters': best_params,
    'training_window': (train_start, train_end),
    'metrics': metrics_dict,
    'version': 'xgb_m15_v1.0_20260101'
}, 'models/xgb_m15.pkl')
```

---

## Phase 6: Validation & Anti-Overfitting Checks (3-4 jam)

### 6.1 Required metrics di OOS set (INDICATOR QUALITY)

| Metric | Apa yang diukur | Target | Red flag |
|---|---|---|---|
| Directional Accuracy | % prediksi arah benar | 52-60% | >65% |
| Precision LONG | Saat predict LONG, % beneran naik | >55% | <50% |
| Precision SHORT | Saat predict SHORT, % beneran turun | >55% | <50% |
| TP Hit Rate | % signal di mana TP1 ke-hit duluan | 55-65% | >75% |
| Brier Score | Kualitas kalibrasi probabilitas | <0.22 | <0.10 (terlalu sempurna) |
| Calibration Curve | Predicted prob vs actual freq | Slope ~1.0 | Slope <0.7 atau >1.3 |
| Trade frequency | Berapa signal per minggu | 3-15/week (M15) | >50/day |

**Kalau ada metric di kolom "red flag", investigate dulu sebelum deploy.** Biasanya:
- Bug labeling (lookahead di triple barrier)
- Feature leakage (feature pakai future data)
- Train/test contamination (purging gak bener)
- Class imbalance handled wrongly

### 6.2 Probability Calibration Check

XGBoost output prob sering miscalibrated. Setelah isotonic calibration di Phase 5, validate:

```python
from sklearn.calibration import calibration_curve
import matplotlib.pyplot as plt

# Untuk tiap kelas (LONG, SHORT)
prob_true, prob_pred = calibration_curve(y_oos_long, probs_long, n_bins=10)

# Plot harus mendekati garis diagonal y=x
plt.plot(prob_pred, prob_true, marker='o')
plt.plot([0,1], [0,1], '--')
```

**Kriteria PASS:**
- Calibration curve slope dalam [0.85, 1.15]
- Brier score < 0.22
- Expected Calibration Error (ECE) < 0.05

**Kalau gagal kalibrasi:** model bilang prob 80% tapi actual cuma 60% true → user (atau Telegram bot) akan over-trust signal. Critical bug.

### 6.3 Probability of Backtest Overfitting (PBO)

Setelah CPCV dengan multiple folds, hitung berapa fraksi parameter combo yang OOS-rank-nya lebih buruk dari median in-sample. PBO < 0.5 = strategy robust.

### 6.4 Feature importance & SHAP

Setelah training:
1. Plot feature importance (gain). Cek apakah top features make sense (RSI, ATR di top = OK; random lag features di top = suspicious).
2. SHAP values untuk explain individual predictions. Save SHAP top-5 untuk tiap signal di production (untuk debugging).

```python
import shap
explainer = shap.TreeExplainer(best_xgb_model)
shap_values = explainer.shap_values(X_oos)
shap.summary_plot(shap_values, X_oos)
```

### 6.5 Live forward test (CRUCIAL — minimal 1 bulan)

**Sebelum deploy ke yeehee live UI, jalankan paper test 1 bulan:**
- Generate signal seperti production
- Simpan ke Supabase dengan flag `is_paper=true`
- Track outcome: TP hit? SL hit? Direction correct?
- Compare live metrics dengan OOS metrics:
  - Live directional accuracy harus dalam 80% dari OOS accuracy
  - Live TP hit rate harus dalam 80% dari OOS TP hit rate
  - Live calibration curve masih reasonable
- Kalau live performance crash → jangan go live, investigate (concept drift? feature pipeline bug?)

---

## Phase 7: Production Deployment (3-4 jam)

### 7.1 Inference daemon (`src/daemon.py`)

```python
import schedule
import time

def generate_rcs_signal(timeframe='M15'):
    # 1. Fetch latest candle
    candle = fetch_latest_candle(timeframe)

    # 2. Compute features
    features = compute_features(candle, timeframe)

    # 3. Add cross-TF features
    cross_tf = compute_cross_tf_features(timeframe)
    features.update(cross_tf)

    # 4. Sanity check on inputs
    if not validate_features(features):
        log_error("Feature validation failed")
        return

    # 5. Load model
    model_pkg = joblib.load(f'models/xgb_{timeframe.lower()}.pkl')

    # 6. Predict
    X = pd.DataFrame([features])[model_pkg['feature_list']]
    X_scaled = model_pkg['scaler'].transform(X)
    probs = model_pkg['model'].predict_proba(X_scaled)[0]
    # probs = [p_short, p_neutral, p_long]

    # 7. Compute RCS score
    rcs = probs[2] - probs[0]   # long - short, range [-1, +1]

    # 8. Determine direction & confidence
    if rcs >= 0.40:
        direction = 'LONG'
    elif rcs <= -0.40:
        direction = 'SHORT'
    else:
        direction = 'WAIT'
    confidence = min(95, int(abs(rcs) * 100))

    # 9. Compute predicted price levels (INDICATOR OUTPUT, bukan risk-managed exit)
    # Entry = harga sekarang (where signal generated)
    # SL = invalidation level (kalau ke sini, prediksi salah)
    # TP1 = conservative target, TP2 = extended target
    # Multipliers ATR udah di-tune di training (lihat Phase 3 triple barrier params)
    spot = candle['close']
    atr = features['atr_14']
    if direction == 'LONG':
        entry = spot
        sl = spot - 1.5 * atr      # invalidation
        tp1 = spot + 1.5 * atr     # conservative target
        tp2 = spot + 3.0 * atr     # extended target
    elif direction == 'SHORT':
        entry = spot
        sl = spot + 1.5 * atr
        tp1 = spot - 1.5 * atr
        tp2 = spot - 3.0 * atr
    else:
        entry = sl = tp1 = tp2 = None

    # 10. SANITY CHECK SEBELUM PUSH
    if direction != 'WAIT':
        # Price deviation check
        if abs(entry - spot) / spot > 0.005:  # >0.5% deviation = bug
            log_error(f"Entry {entry} deviates too much from spot {spot}")
            return
        # SL distance sanity (must be 0.5% - 3% from entry)
        sl_dist_pct = abs(sl - entry) / entry
        if sl_dist_pct < 0.005 or sl_dist_pct > 0.03:
            log_error(f"SL distance {sl_dist_pct} out of bounds")
            return
        # News filter
        if features['news_proximity_min'] > -30 and features['news_proximity_min'] < 30:
            log_error("Skipping signal: too close to news")
            return

    # 11. Push to Supabase
    push_signal_to_supabase({
        'timeframe': timeframe,
        'spot_price': spot,
        'atr_14': atr,
        'prob_long': probs[2],
        'prob_short': probs[0],
        'prob_neutral': probs[1],
        'rcs_score': rcs,
        'direction': direction,
        'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
        'confidence_pct': confidence,
        'feature_snapshot': dict(list(features.items())[:10]),
        'shap_top_5': compute_shap_top5(model_pkg, X_scaled),
        'model_version': model_pkg['version']
    })

# Schedule
schedule.every(5).minutes.do(generate_rcs_signal, timeframe='M5')
schedule.every(15).minutes.do(generate_rcs_signal, timeframe='M15')
schedule.every(1).hour.do(generate_rcs_signal, timeframe='H1')

while True:
    schedule.run_pending()
    time.sleep(30)
```

### 7.2 FastAPI service (optional, kalau mau on-demand inference)

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/rcs/signal/{timeframe}")
async def get_signal(timeframe: str):
    return generate_rcs_signal(timeframe)
```

Run: `uvicorn src.inference:app --host 0.0.0.0 --port 8001`

Pakai cloudflared tunnel atau ngrok kalau Vercel perlu akses langsung.

### 7.3 Cara push ke Supabase dari home PC

Sudah punya pattern dari BeautyBot. Pakai supabase-py:
```python
from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
sb.table('rcs_signals').insert(signal_data).execute()
```

---

## Phase 8: yeehee Frontend Integration (2-3 jam)

### 8.1 Modifikasi `/signals` page

Existing signal page (yang kemarin ada bug $417.85) di-replace pakai data dari `rcs_signals` table.

```tsx
// app/signals/page.tsx (Next.js Server Component)
import { createClient } from '@supabase/supabase-js';

export default async function SignalsPage() {
  const supabase = createClient(URL, ANON_KEY);
  const { data: signals } = await supabase
    .from('rcs_signals')
    .select('*')
    .order('generated_at', { ascending: false })
    .limit(3);  // M5, M15, H1 latest

  return (
    <div>
      {signals.map(sig => (
        <SignalCard key={sig.id} signal={sig} />
      ))}
    </div>
  );
}
```

**Benefit:** SSR, no more "Memuat sinyal..." blank state. Kalau Supabase down, error proper bukan stuck loading.

### 8.2 Komponen SignalCard

Layout untuk pure indicator output:

- **Direction badge:** LONG (hijau) / SHORT (merah) / WAIT (kuning)
- **Confidence%:** big number, dengan progress bar
- **Probability breakdown bar:** bar 3 segment menunjukkan `prob_long`, `prob_neutral`, `prob_short`
- **Predicted levels:**
  - Entry (harga sekarang saat signal generated)
  - SL (invalidation level — kalau ke sini, prediksi salah)
  - TP1 (conservative target)
  - TP2 (extended target)
- **Top 3 reason (dari SHAP):** misal "RSI H1 oversold (+0.18)", "M15 MACD bullish cross (+0.12)", "ATR di percentile 70 (-0.05)"
- **Model version pill:** kecil, klik untuk lihat training metrics
- **Last update timestamp:** "Updated 2 min ago"

**TIDAK ADA di SignalCard:**
- ❌ Lot size suggestion
- ❌ Account risk %
- ❌ R:R ratio (user hitung sendiri di Kalkulator kalau perlu)
- ❌ "Recommended position" apapun

**Link ke Kalkulator:** tombol "Hitung lot size →" yang pre-fill Kalkulator dengan entry/SL dari signal ini. User decide sendiri profile risk-nya.

### 8.3 Halaman baru: `/more/rcs-monitor`

Dashboard internal untuk monitor RCS health:
- Win rate 7-day, 30-day per TF
- Equity curve dari `rcs_performance_daily`
- Recent signals table dengan outcome
- Feature drift indicator: distribution feature live vs training (KL divergence)
- Trigger manual retrain button

### 8.4 Update Telegram bot

Modify Telegram push: kirim signal hanya kalau:
- `direction != 'WAIT'`
- `confidence_pct >= 65`
- Belum kirim signal sama dalam 30 menit terakhir (debounce)

Format pesan:
```
🟢 LONG XAU/USD (M15) — Confidence 78%
Entry: 4571.80
SL:    4565.30  (invalidation)
TP1:   4581.55  (conservative)
TP2:   4591.30  (extended)

Probabilitas: LONG 78% · NEUTRAL 15% · SHORT 7%
Why: RSI H1 oversold, M15 trend bullish, low volatility regime
Model: xgb_m15_v1.0

⚠️ Indikator output saja. Ukuran lot & risk → Kalkulator.
```

---

## Phase 9: Monitoring & Auto-Retrain (2-3 jam)

### 9.1 Daily performance log

Daemon di home PC, jalan 23:59 WIB tiap hari:
- Query semua signal hari ini
- Untuk yang `outcome = PENDING`, check apakah TP/SL ke-hit
- Update `outcome`, `pnl_pct`
- Aggregate ke `rcs_performance_daily`

### 9.2 Drift detection

Tiap minggu, hitung KL divergence antara distribusi feature 7 hari terakhir vs training set. Kalau >threshold:
- Log warning
- Kirim Telegram notif ke lo
- Disable auto-trade (set confidence threshold ke 100, effectively pause)

### 9.3 Auto-retrain trigger

Conditions untuk retrain:
1. **Scheduled:** tiap 30 hari, retrain dengan window terbaru
2. **Performance degradation:** kalau win rate 7-day drop >15% dari 30-day, trigger retrain
3. **Manual:** dari dashboard `/more/rcs-monitor`

Process: jalankan ulang Phase 5 dengan data baru, evaluate (Phase 6), kalau lulus → activate model baru.

### 9.4 Auto-pause trigger (INDICATOR QUALITY based, bukan MM)

Hard rule untuk pause indikator:
- **Directional accuracy 7-day < 45%** → indikator berperilaku worse than random, pause auto-publish ke Telegram
- **TP hit rate 7-day < 35%** → prediksi level meleset signifikan, pause
- **5 signal terakhir berturut-turut wrong direction** → pause 24 jam, manual review
- **Calibration drift detected (Phase 9.2)** → pause auto-publish, butuh retrain

⚠️ **Catatan:** "Pause" di sini = stop kirim Telegram & set flag `is_paused=true` di table model. Signal masih di-generate ke `rcs_signals` table tapi gak di-promote. User masih bisa lihat di UI dengan badge "PAUSED — under review". Money management decisions (lot size, account risk) tetap di tangan user via Kalkulator.

---

## Phase 10: MT5 Auto-Execution Architecture (DESIGN ONLY untuk fase ini)

⚠️ **Phase ini TIDAK di-build sekarang.** Tujuannya: kasih "bayangan" arsitektur ke Claude Code supaya kode di Phase 1-9 sudah siap di-extend ke auto-trade nanti tanpa breaking refactor. Spec konkret EA dibuat di v2 setelah Phase 1-9 stable.

### 10.1 Filosofi auto-execution

**3 tier transition:**

| Tier | Mode | Eksekusi | Kapan deploy |
|---|---|---|---|
| Tier 1 | Manual | User open trade sendiri di MT5 setelah liat signal | **Saat ini (Phase 1-9)** |
| Tier 2 | Semi-auto | EA jalan tapi butuh user tap "Approve" di Telegram untuk execute | Setelah 30 hari Tier 1 stable |
| Tier 3 | Full auto | EA execute langsung sesuai signal + pre-config user | Setelah 30 hari Tier 2 stable & metrics OK |

Skip-step ke Tier 3 langsung adalah cara cepat wipe akun. Wajib lewat semua tier.

### 10.2 Communication architecture

**Recommended: REST polling**

```
┌────────────────────┐         ┌────────────────────┐
│  Daemon (home PC)  │         │  MT5 Terminal      │
│  - Generate signal │         │  - DextradeEA.mq5  │
│  - Push Supabase   │         │  - Polling EA      │
│  - Serve FastAPI   │ ◄──────│                    │
│    :8001           │  HTTP   │                    │
│                    │  GET    │                    │
└────────────────────┘         └────────────────────┘
         │                              │
         │ Supabase write               │ Supabase write (after exec)
         ▼                              ▼
   ┌──────────────────────────────────────────┐
   │  Yeehee Supabase                         │
   │  - rcs_signals (indicator output)        │
   │  - rcs_executions (EA trade results)     │
   │  - rcs_ea_heartbeat (EA health)          │
   └──────────────────────────────────────────┘
                  │
                  ▼
          ┌─────────────────┐
          │  yeehee.vercel  │
          │  Read-only view │
          │  + monitoring   │
          └─────────────────┘
```

**Why REST polling over webhook/queue:**
- EA running on same PC as daemon → localhost call, ~1ms latency
- Stateless, simple to debug
- No external dependencies (no Redis/RabbitMQ)
- EA easy to control (just stop polling = stop trading)

### 10.3 FastAPI endpoints (`src/execution_api.py`)

Skeleton untuk dipersiapkan struktur sekarang (implementation kosong, return mock):

```python
from fastapi import FastAPI, HTTPException, Header
from datetime import datetime, timedelta

app = FastAPI()

# Auth: shared secret di config.yaml & EA input
EA_SECRET = "REPLACE_WITH_RANDOM_TOKEN"

def auth(token: str):
    if token != EA_SECRET:
        raise HTTPException(401, "Unauthorized")

@app.get("/api/ea/next-signal")
def get_next_signal(timeframe: str, x_ea_token: str = Header(...)):
    """
    EA polls this endpoint every 30s.
    Returns latest signal yang execution_status='PENDING_PICKUP' & confidence > threshold.
    Mark as PICKED_UP supaya gak di-pick lagi.
    """
    auth(x_ea_token)
    # Phase 10 implementation: query Supabase, claim signal, return
    # For now, return null
    return {"signal": None}

@app.post("/api/ea/report-execution")
def report_execution(payload: dict, x_ea_token: str = Header(...)):
    """
    EA report after trade executed (or rejected).
    Insert ke rcs_executions table.

    payload: {
      "signal_id": int,
      "mt5_ticket_id": int,
      "execution_price": float,
      "execution_lot": float,
      "execution_sl": float,
      "execution_tp": float,
      "executed_at": "ISO8601",
      "status": "OPEN" | "REJECTED",
      "rejected_reason": str | null,
      "account_balance": float,
      "risk_pct_used": float
    }
    """
    auth(x_ea_token)
    # Phase 10 implementation
    return {"ok": True}

@app.post("/api/ea/report-close")
def report_close(payload: dict, x_ea_token: str = Header(...)):
    """
    EA report when trade closes (TP/SL/manual/etc).
    Update rcs_executions row.
    """
    auth(x_ea_token)
    return {"ok": True}

@app.post("/api/ea/heartbeat")
def heartbeat(payload: dict, x_ea_token: str = Header(...)):
    """
    EA send heartbeat every 60s. Insert rcs_ea_heartbeat row.
    """
    auth(x_ea_token)
    return {"ok": True}

@app.get("/api/ea/should-pause")
def should_pause(x_ea_token: str = Header(...)):
    """
    EA check before each trade: any global pause flag?
    Returns: {"pause": bool, "reason": str | null}
    Trigger sources:
    - Indicator drift detected
    - News window proximity (auto-pause 30 min before high-impact)
    - Manual pause from /more/rcs-monitor dashboard
    - Daily trade limit reached
    """
    auth(x_ea_token)
    return {"pause": False, "reason": None}
```

### 10.4 EA skeleton (`ea/DextradeEA.mq5`)

⚠️ **JANGAN coding penuh sekarang**, cukup header untuk reference:

```mql5
//+------------------------------------------------------------------+
//|                                              DextradeEA.mq5     |
//|                          RCS Signal Executor for yeehee/dextrade |
//+------------------------------------------------------------------+
#property copyright "yeehee/dextrade"
#property version   "1.00"
#property strict

// User inputs (set di MT5 EA settings)
input string  ApiBaseUrl       = "http://localhost:8001";
input string  EaToken          = "REPLACE_WITH_TOKEN";
input string  Timeframe        = "M15";          // Which RCS TF to consume
input double  RiskPercent      = 1.0;            // % of balance per trade
input int     MaxOpenPositions = 1;              // Max concurrent positions
input int     MaxDailyTrades   = 5;
input int     PollIntervalSec  = 30;
input bool    UseTrailingStop  = false;
input int     SlippagePoints   = 50;
input bool    PauseOnNews      = true;

// State
datetime lastPoll = 0;
int      tradesToday = 0;
datetime tradesTodayDate = 0;

void OnInit() {
   // Validate config, send first heartbeat
}

void OnTick() {
   // Manage open positions (trailing, partial close, etc)
   // Don't decide entry here — entry decided in OnTimer
}

void OnTimer() {
   // 1. Send heartbeat
   // 2. Check should-pause
   // 3. If not paused: poll for next signal
   // 4. If signal: validate (broker constraints, risk check) → execute
   // 5. Report execution result
}

// Helpers:
// - HttpGet, HttpPost wrappers (WinHTTP)
// - CalculateLotSize(slPoints, riskPct, balance) → respect broker min/max/step
// - ExecuteOrder(direction, entry, sl, tp1, tp2)
// - Position management & trailing stop logic
```

### 10.5 Pre-execution risk validation (di EA, BUKAN di RCS daemon)

Saat EA pickup signal, EA harus validate **lokal di MT5** sebelum kirim order ke broker:

1. **Broker stop level:** SL/TP distance >= `SymbolInfoInteger(SYMBOL_TRADE_STOPS_LEVEL)`. Kalau RCS predict SL terlalu dekat dengan price (gold news event volatile), reject signal.
2. **Spread sanity:** kalau spread saat ini >2× typical, kemungkinan news event, reject.
3. **Lot size validation:** sesuai `volume_min`, `volume_max`, `volume_step`. Round down kalau perlu.
4. **Daily trade count:** kalau sudah hit `MaxDailyTrades`, reject.
5. **Open position count:** kalau sudah hit `MaxOpenPositions`, reject.
6. **Margin check:** `AccountInfoDouble(ACCOUNT_FREEMARGIN)` cukup untuk trade ini?
7. **Server time vs signal timestamp:** kalau signal >5 menit, reject (stale).

Semua reject di-report ke `/api/ea/report-execution` dengan status `REJECTED` + reason. Logged di Supabase untuk audit.

### 10.6 Money management — di EA, TIDAK di RCS

**Reminder kritis:** RCS output tetap pure indicator. Money management (lot calc, daily limit) di EA, dengan formula sederhana:

```mql5
double CalculateLotSize(int slPoints, double riskPct, double balance) {
   double riskMoney = balance * riskPct / 100.0;
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double rawLot = riskMoney / (slPoints * tickValue);

   // Round to lot_step
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   double lot = MathFloor(rawLot / step) * step;
   lot = MathMax(minLot, MathMin(maxLot, lot));
   return lot;
}
```

Note: ini sama persis dengan logic di Kalkulator yeehee. Bisa di-port langsung.

### 10.7 Frontend extension untuk Tier 2/3 (preview di /more/rcs-monitor)

Saat Phase 10 dibangun, dashboard akan punya:
- **Mode toggle:** Manual / Semi-auto / Full auto
- **EA status:** connected, last heartbeat, balance, equity, open positions
- **Live executions feed:** signal → execution → outcome
- **Daily PnL** (dari EA report, BUKAN computed by RCS)
- **Big red button:** EMERGENCY STOP (set global pause flag)

### 10.8 Yang harus disiapkan di Phase 1-9 supaya Phase 10 smooth

Checklist untuk Claude Code saat build Phase 1-9:

- [x] Schema `rcs_signals` punya `is_executable`, `execution_status` columns
- [x] Schema `rcs_executions` & `rcs_ea_heartbeat` tables sudah dibuat (kosong dulu)
- [x] `rcs_signals` punya `sl_points`, `tp1_points`, `tp2_points` (point-based, gampang dikonsumsi EA)
- [x] `rcs_signals.broker_symbol` field (ready untuk multi-broker future)
- [x] Daemon push signal sebagai JSON yang bisa langsung di-parse EA (no further transformation)
- [x] Folder `ea/` ada di repo (placeholder, Phase 10 fill)
- [x] FastAPI skeleton ada (`src/execution_api.py`), endpoint stub return null
- [x] Config.yaml ada section `api`, `mt5`, `inference`
- [x] Config.yaml `mt5.point_size`, `mt5.tick_value_per_lot`, `mt5.stops_level_points` — used by daemon untuk validate signal feasibility BEFORE push (avoid sending un-executable signal)

---

## Phase 11: Final Checklist Sebelum Live (Tier 1 Manual Mode)

- [ ] Phase 1 PASS: data quality report bersih
- [ ] Phase 2 PASS: no feature corr >0.95, no zero-variance
- [ ] Phase 3 PASS: label distribution realistic (LONG/SHORT/NEUTRAL split sesuai)
- [ ] Phase 4 PASS: CPCV implementation tested, no leakage detected
- [ ] Phase 5 PASS: LogReg baseline OOS accuracy > 50%; XGBoost OOS accuracy > LogReg + 3%
- [ ] Phase 6 PASS:
  - All metrics dalam target range (NOT in red flag)
  - Calibration curve slope dalam [0.85, 1.15]
  - Brier score < 0.22, ECE < 0.05
  - SHAP feature importance make sense (RSI, ATR, structure di top — bukan random lag)
- [ ] Phase 7 PASS: daemon stable run 24 jam tanpa crash
- [ ] Phase 8 PASS: UI render correctly, no $417 bug recurrence, indikator output clearly separated dari Kalkulator MM
- [ ] Phase 9 PASS: monitoring & auto-pause tested
- [ ] **Paper test 30 hari:** live indicator quality dalam 80% OOS metrics
- [ ] **Disclaimer di UI** sudah jelas: "RCS = pure indicator. Money management = user decision."

---

## Reference Books / Papers (kalau mau dalami)

1. **López de Prado — Advances in Financial Machine Learning** (2018). Triple barrier, CPCV, DSR, PBO semua dari sini.
2. **López de Prado — The 10 Reasons Most Machine Learning Funds Fail** (2018 paper). Wajib baca.
3. **Bailey & López de Prado — The Deflated Sharpe Ratio** (2014).
4. **Kaufman — Trading Systems and Methods** (5th ed). Untuk dasar TA solid.

---

## Catatan untuk Reyhan

1. **Estimasi total waktu (Phase 1-9, Tier 1 Manual):** 25-35 jam Claude Code execution + 2-3 minggu paper test + iterasi.
2. **Estimasi waktu Phase 10 (Tier 2/3 EA):** 15-25 jam tambahan setelah Tier 1 stable.
3. **Estimasi cost Claude Code:** ~$15-30 USD untuk Phase 1-9. Hardware home PC sudah ada.
4. **Risk:** kemungkinan hasil akhir tidak match harapan (~60% chance indicator beneran predictive). Tapi lo akan dapat **infrastruktur indikator quant proper**, **disiplin proses ML**, dan **framework reusable**. Itu sendiri investasi worth it.
5. **Setelah live:** RCS bukan "set and forget". Indikator retire seiring waktu (concept drift). Plan untuk rebuild RCS v2 dalam 6-12 bulan.
6. **Jangan klaim "akurasi tinggi" di marketing/UI.** Tampilkan apa adanya: confidence%, prob breakdown, calibration metric, directional accuracy historis. Trader experienced respect honesty.

7. **Separation of concerns yang dipegang ketat:**
   - **RCS daemon** = pure indicator engine (input data MT5 → output direction + levels)
   - **Kalkulator yeehee** = money management UI (lot size calc, profile risk)
   - **MT5 EA (Phase 10)** = execution + risk validation + position management
   - **User** = decision maker (pilih signal mana yang di-execute, profile mana yang dipakai)

8. **PROJECT ISOLATION (CRITICAL):**
   - yeehee/dextrade adalah project mandiri
   - Folder kerja: `D:\dextrade\rcs\` — NEVER mix dengan project lain
   - Supabase, Vercel, Telegram bot, GitHub repo: SEMUA dedicated yeehee
   - Codebase HARUS clean — gak boleh ada import/reference dari project lain manapun
   - Kalau Claude Code "kebawa" pattern dari elsewhere, FLAG sebagai bug

9. **Path roadmap:**
   ```
   NOW         → Phase 1-9 (Tier 1 manual signal indicator)
   +1 month    → Paper test 30 hari, validate live performance
   +2 months   → Tier 2 (semi-auto with Telegram approval)
   +3 months   → Tier 3 (full auto with EA, dengan kill switches lengkap)
   +6 months   → Multi-symbol expansion (EURUSD, BTCUSD, dll)
   +12 months  → RCS v2 rebuild dengan learnings
   ```

10. **Filosofi closing:** RCS bukan ATM machine. Even kalau infrastruktur lo perfect, market regime akan berubah, edge akan decay, dan kadang lo bakal rugi sebulan straight. Yang lo bangun di sini adalah **disiplin infrastruktur** untuk respond ke kondisi itu — bukan jaminan profit. Trader yang bertahan adalah yang punya sistem, bukan yang punya "indikator akurasi tinggi".

---

**Versi spec:** 1.2
**Tanggal:** 5 Mei 2026
**Project:** yeehee / dextrade
**Untuk:** Claude Code execution
**Repo:** github.com/proreyhanwijaya111/yeehee
