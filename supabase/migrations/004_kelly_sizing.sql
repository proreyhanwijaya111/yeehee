-- IMPROVEMENT #4: Kelly fractional position sizing.
--
-- Adds per-trade risk sizing fields to active_trades. Risk is computed at
-- open time based on:
--   1. Historical win_rate + avg_win_r for this style (from prior closed trades)
--   2. Synthesizer confidence (higher conf = larger fraction of profile cap)
--   3. Profile risk cap (konservatif=0.5%, moderat=1%, agresif=2%, bebas=5%)
--
-- Formula: risk_pct = clip(profile_cap * (kelly_fraction × confidence_multiplier), 0.001, profile_cap)
--   where kelly_fraction = max(0, win_rate - (1-win_rate)/avg_win_r) × 0.25 (quarter-Kelly)
--
-- Without enough closed trades (< 20) we fall back to: risk_pct = profile_cap × confidence
-- (small samples are too noisy for Kelly).
--
-- Stored as decimal fraction (0.01 = 1% risk per trade).

alter table active_trades
    add column if not exists risk_pct        numeric(6, 5),     -- 0.01 = 1%
    add column if not exists kelly_fraction  numeric(6, 5),     -- raw Kelly fraction (pre-confidence-scale)
    add column if not exists profile         text default 'moderat',  -- profile cap used at open
    add column if not exists prior_winrate   numeric(5, 4),     -- snapshot of historical win rate at open
    add column if not exists prior_avg_win_r numeric(6, 3),     -- snapshot of historical avg win R at open
    add column if not exists prior_n_closed  integer;           -- number of closed trades used for prior

-- Per-style portfolio stats view (used by Kelly sizing for prior estimate).
create or replace view portfolio_stats_by_style as
select
    user_id,
    style,
    count(*) filter (where status = 'OPEN')                  as open_count,
    count(*) filter (where status != 'OPEN')                 as closed_count,
    count(*) filter (where status in ('TP1','TP2','TP3'))    as wins,
    count(*) filter (where status = 'SL')                    as losses,
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
group by user_id, style;
