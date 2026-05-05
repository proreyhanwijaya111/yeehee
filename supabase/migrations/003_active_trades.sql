-- Active Trades — paper trading / forward test layer.
--
-- Solves: signal flip-flop UX — every cycle daemon could output LONG/FLAT/SHORT
-- with shifting confidence. User can't actually trade ambiguous signals.
--
-- Solution: when daemon generates LONG/SHORT signal (per style), CREATE a row
-- here. Lock in entry/sl/tp. Subsequent cycles MONITOR the trade (track price
-- against levels), don't override side. Close when TP/SL hit or expiry passed.
-- Then real win rate emerges from actual outcomes, not hypothetical.

create table if not exists active_trades (
    id            uuid primary key default gen_random_uuid(),
    user_id       text default 'default',
    bundle_id     uuid references signal_bundles(id) on delete set null,

    -- Signal at open
    style          text not null,             -- 'scalper' | 'intraday' | 'swing'
    side           text not null,             -- 'LONG' | 'SHORT'
    signal_strength text,
    confidence     numeric(5, 4),

    -- Levels at entry (immutable for lifetime of trade)
    entry          numeric(12, 2) not null,
    sl             numeric(12, 2) not null,
    tp1            numeric(12, 2),
    tp2            numeric(12, 2),
    tp3            numeric(12, 2),

    -- Status tracking
    status         text default 'OPEN',       -- 'OPEN' | 'TP1' | 'TP2' | 'TP3' | 'SL' | 'EXPIRED' | 'MANUAL'
    hit_tp1        boolean default false,
    hit_tp2        boolean default false,
    hit_tp3        boolean default false,
    hit_sl         boolean default false,

    -- Tracking metrics (updated each cycle)
    high_after_open numeric(12, 2),
    low_after_open  numeric(12, 2),
    last_check_at   timestamptz,

    -- Lifecycle timestamps
    opened_at      timestamptz not null default now(),
    expiry_at      timestamptz not null,        -- daemon closes if past this
    closed_at      timestamptz,

    -- Outcome
    exit_price     numeric(12, 2),
    exit_reason    text,                        -- 'tp_hit' | 'sl_hit' | 'expired' | 'manual_close'
    pnl_r          numeric(6, 3),               -- R-multiple, +2 if TP2 hit, -1 if SL, etc
    pnl_pct        numeric(8, 4),               -- % of entry price (for $-equivalent)

    -- Context (snapshot at open, for forensics)
    reasons        jsonb,
    risks          jsonb,
    regime         text,
    session        text
);

-- Indexes
create index if not exists active_trades_user_status_idx
    on active_trades (user_id, status, opened_at desc);

create index if not exists active_trades_opened_at_idx
    on active_trades (opened_at desc);

-- Critical constraint: at most ONE OPEN trade per (user_id, style).
-- This is THE locking mechanism that prevents signal flip-flop from
-- duplicating positions. Daemon must check this before INSERT.
create unique index if not exists active_trades_one_open_per_style
    on active_trades (user_id, style)
    where status = 'OPEN';

-- View: portfolio stats (read-only aggregation)
create or replace view portfolio_stats as
select
    user_id,
    count(*) filter (where status = 'OPEN')                  as open_count,
    count(*) filter (where status != 'OPEN')                 as closed_count,
    count(*) filter (where status in ('TP1','TP2','TP3'))    as wins,
    count(*) filter (where status = 'SL')                    as losses,
    count(*) filter (where status = 'EXPIRED')               as expired,
    coalesce(avg(pnl_r) filter (where status != 'OPEN'), 0)  as avg_pnl_r,
    coalesce(sum(pnl_r) filter (where status != 'OPEN'), 0)  as total_pnl_r,
    coalesce(avg(pnl_r) filter (where pnl_r > 0), 0)         as avg_win_r,
    coalesce(avg(pnl_r) filter (where pnl_r <= 0), 0)        as avg_loss_r,
    case
        when count(*) filter (where status != 'OPEN') > 0
        then count(*) filter (where status in ('TP1','TP2','TP3'))::numeric
            / count(*) filter (where status != 'OPEN')
        else 0
    end as win_rate
from active_trades
group by user_id;
