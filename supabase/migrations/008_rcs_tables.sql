-- RCS — REY Composite Signal (Multi-TF ML Edition) — schema scaffolding.
--
-- Per RCS_MULTI_TF_ML_SPEC.md v1.2. Tables for the ML-based pure indicator
-- pipeline: candle ingestion (MT5), live signals, executions (Phase 10), models,
-- daily performance.
--
-- IMPORTANT: this migration ONLY creates tables. Actual model training + signal
-- generation requires the Python pipeline at rcs/ folder + MT5 client on user's
-- PC. Tables are empty until daemon runs.
--
-- Naming: prefixed `rcs_` to keep separate from existing yeehee tables
-- (signal_bundles, signals, active_trades — which are the LLM-debate pipeline).

-- =====================================================================
-- 1. Candle data (cache from MT5 — optional, daemon can keep local parquet)
-- =====================================================================
create table if not exists rcs_candles (
    id           bigserial primary key,
    symbol       text not null default 'XAUUSD',
    timeframe    text not null check (timeframe in ('M5', 'M15', 'H1')),
    "timestamp"  timestamptz not null,
    open         numeric(10,3) not null,
    high         numeric(10,3) not null,
    low          numeric(10,3) not null,
    close        numeric(10,3) not null,
    volume       bigint,
    spread       integer,
    created_at   timestamptz default now(),
    unique (symbol, timeframe, "timestamp")
);

create index if not exists idx_rcs_candles_lookup
    on rcs_candles (symbol, timeframe, "timestamp" desc);

-- =====================================================================
-- 2. Live RCS signals (output of inference daemon)
-- =====================================================================
create table if not exists rcs_signals (
    id              bigserial primary key,
    generated_at    timestamptz not null default now(),
    timeframe       text not null check (timeframe in ('M5', 'M15', 'H1')),
    broker_symbol   text not null,

    spot_price      numeric(10,3) not null,
    atr_14          numeric(10,3) not null,

    -- Model probabilities (3-class: short, neutral, long) + composite score
    prob_long       numeric(5,4) not null,
    prob_short      numeric(5,4) not null,
    prob_neutral    numeric(5,4) not null,
    rcs_score       numeric(5,4) not null,
    direction       text not null check (direction in ('LONG', 'SHORT', 'WAIT')),

    -- Predicted price levels (PURE INDICATOR — user decides lot via Kalkulator)
    entry           numeric(10,3),
    sl              numeric(10,3),
    tp1             numeric(10,3),
    tp2             numeric(10,3),

    -- Distance in points (for EA easy consumption — Phase 10)
    sl_points       integer,
    tp1_points      integer,
    tp2_points      integer,

    confidence_pct  integer not null check (confidence_pct between 0 and 95),
    feature_snapshot jsonb,
    shap_top_5       jsonb,
    model_version    text not null,

    -- Phase 10 readiness
    is_executable    boolean default false,
    execution_status text default 'NOT_FOR_EXECUTION' check (execution_status in (
        'NOT_FOR_EXECUTION','PENDING_PICKUP','PICKED_UP','EXECUTED','REJECTED','EXPIRED'
    )),

    -- Outcome tracking (for indicator quality eval, NOT trading PnL)
    outcome           text check (outcome in ('TP1_HIT','TP2_HIT','SL_HIT','EXPIRED','PENDING')),
    outcome_price     numeric(10,3),
    outcome_at        timestamptz,
    prediction_correct boolean
);

create index if not exists idx_rcs_signals_recent
    on rcs_signals (generated_at desc, timeframe);
create index if not exists idx_rcs_signals_pending_outcome
    on rcs_signals (outcome, generated_at desc) where outcome is null or outcome = 'PENDING';
create index if not exists idx_rcs_signals_pickup
    on rcs_signals (execution_status, generated_at desc)
    where execution_status = 'PENDING_PICKUP';

-- =====================================================================
-- 3. Executions (Phase 10 — empty for now, EA will populate)
-- =====================================================================
create table if not exists rcs_executions (
    id                  bigserial primary key,
    signal_id           bigint references rcs_signals(id),

    mt5_ticket_id       bigint unique,
    mt5_symbol          text not null,
    mt5_account_login   bigint,

    requested_at        timestamptz not null,
    executed_at         timestamptz,
    execution_price     numeric(10,3),
    execution_lot       numeric(8,2) not null,
    execution_sl        numeric(10,3),
    execution_tp        numeric(10,3),
    slippage_points     integer,

    status              text not null check (status in (
        'PENDING_BROKER','OPEN','CLOSED_TP','CLOSED_SL','CLOSED_MANUAL',
        'CLOSED_TRAILING','CLOSED_NEWS','REJECTED'
    )),

    closed_at           timestamptz,
    close_price         numeric(10,3),
    close_reason        text,

    pnl_money           numeric(12,2),
    pnl_points          integer,
    commission          numeric(8,2),
    swap                numeric(8,2),

    account_balance_at_open numeric(12,2),
    risk_pct_used       numeric(5,3),
    rejected_reason     text,

    created_at          timestamptz default now()
);

create index if not exists idx_rcs_executions_signal on rcs_executions(signal_id);
create index if not exists idx_rcs_executions_open on rcs_executions(status) where status = 'OPEN';
create index if not exists idx_rcs_executions_recent on rcs_executions(executed_at desc);

-- =====================================================================
-- 4. EA heartbeat (Phase 10 — empty for now)
-- =====================================================================
create table if not exists rcs_ea_heartbeat (
    id                bigserial primary key,
    ea_instance_id    text not null,
    account_login     bigint not null,
    ts                timestamptz default now(),
    account_balance   numeric(12,2),
    account_equity    numeric(12,2),
    open_positions    integer,
    is_paused         boolean default false
);

create index if not exists idx_ea_heartbeat_recent on rcs_ea_heartbeat(ts desc);

-- =====================================================================
-- 5. Model registry & training metadata
-- =====================================================================
create table if not exists rcs_models (
    id                       bigserial primary key,
    version                  text unique not null,
    timeframe                text not null,
    model_type               text not null,
    trained_at               timestamptz not null,
    training_window_start    date,
    training_window_end      date,

    -- Performance metrics — INDICATOR QUALITY, not PnL
    oos_accuracy             numeric(5,4),
    oos_precision_long       numeric(5,4),
    oos_precision_short      numeric(5,4),
    oos_recall_long          numeric(5,4),
    oos_recall_short         numeric(5,4),
    oos_f1_macro             numeric(5,4),
    oos_log_loss             numeric(6,4),
    oos_calibration_error    numeric(5,4),
    oos_tp_hit_rate          numeric(5,4),
    num_features             integer,

    storage_path             text,
    feature_list             jsonb,
    hyperparameters          jsonb,

    is_active                boolean default false,
    notes                    text
);

create index if not exists idx_rcs_models_active on rcs_models(timeframe, is_active) where is_active = true;

-- =====================================================================
-- 6. Daily performance aggregation (for monitoring page)
-- =====================================================================
create table if not exists rcs_performance_daily (
    id                        bigserial primary key,
    "date"                    date not null,
    timeframe                 text not null,
    num_signals               integer not null default 0,
    num_correct               integer not null default 0,
    num_tp_hit                integer not null default 0,
    num_sl_hit                integer not null default 0,
    num_expired               integer not null default 0,
    directional_accuracy      numeric(5,4),
    tp_hit_rate               numeric(5,4),
    avg_confidence            numeric(5,4),
    unique ("date", timeframe)
);

-- Convenience view: latest signal per timeframe (for /signals page UI)
create or replace view rcs_signals_latest as
select distinct on (timeframe)
    timeframe, generated_at, broker_symbol, spot_price, direction, confidence_pct,
    prob_long, prob_short, prob_neutral, entry, sl, tp1, tp2,
    sl_points, tp1_points, tp2_points, model_version, shap_top_5, outcome
from rcs_signals
order by timeframe, generated_at desc;
