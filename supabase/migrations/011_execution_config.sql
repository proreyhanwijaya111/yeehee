-- Execution config — controls EA behavior + daily cap.
--
-- All controllable via UI form at /more/settings/execution.
-- EA polls /api/ea/config every cycle (30s) → no EA restart needed when user
-- changes settings. Hard caps in CHECK constraints prevent dangerous configs.
--
-- Defaults are SAFE for demo paper test:
--   ea_enable_execution = false   (must explicitly turn on)
--   ea_enable_paper     = true    (logs only, no real orders)
--   ea_max_open_positions = 1
--   ea_max_trades_per_day = 5
--   ea_risk_per_trade_pct = 1.0%  (user can raise to max 3%)
--   ea_daily_loss_pct = 5.0%
--   ea_min_confidence_pct = 65
--   ea_enable_break_even = true
--   ea_break_even_trigger_pips = 50
--   ea_break_even_lock_pips = 5
--   ea_enable_trailing = true
--   ea_trailing_trigger_pips = 100
--   ea_trailing_distance_pips = 30

alter table app_settings
    -- Daily cap (anti over-trading)
    add column if not exists ea_max_trades_per_day integer default 5
        check (ea_max_trades_per_day between 1 and 10),

    -- Risk per trade (with hard cap)
    add column if not exists ea_risk_per_trade_pct numeric(4,2) default 1.0
        check (ea_risk_per_trade_pct between 0.1 and 3.0),

    -- Break-even SL (auto move SL to entry+lock when profit reaches trigger)
    add column if not exists ea_enable_break_even boolean default true,
    add column if not exists ea_break_even_trigger_pips integer default 50
        check (ea_break_even_trigger_pips between 10 and 500),
    add column if not exists ea_break_even_lock_pips integer default 5
        check (ea_break_even_lock_pips between 0 and 50),

    -- Trailing stop (move SL with price, distance behind)
    add column if not exists ea_enable_trailing boolean default true,
    add column if not exists ea_trailing_trigger_pips integer default 100
        check (ea_trailing_trigger_pips between 20 and 1000),
    add column if not exists ea_trailing_distance_pips integer default 30
        check (ea_trailing_distance_pips between 10 and 200);

-- Existing columns from migration 010 (kept for reference):
--   ea_enable_execution    boolean default false
--   ea_enable_paper        boolean default true
--   ea_max_open_positions  integer default 1
--   ea_daily_loss_pct      numeric(5,2) default 5.0
--   ea_min_confidence_pct  integer default 65

-- View: count today's executed trades per worker (used by daemon for daily cap check)
create or replace view rcs_executions_today as
select
    e.mt5_account_login,
    count(*) as trades_today,
    coalesce(sum(case when e.status like 'CLOSED_TP%' then 1 else 0 end), 0) as wins_today,
    coalesce(sum(case when e.status like 'CLOSED_SL%' then 1 else 0 end), 0) as losses_today,
    coalesce(sum(e.pnl_money), 0) as pnl_money_today
from rcs_executions e
where e.executed_at >= date_trunc('day', now() at time zone 'UTC')
group by e.mt5_account_login;
