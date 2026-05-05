-- EA (Expert Advisor) safety config — controllable via UI without restarting EA.
--
-- EA polls /api/ea/config?ea=ID every cycle. Updates here take effect
-- immediately on next poll (no EA restart needed).
--
-- Defaults are SAFE:
--   ea_enable_execution = false   (no real orders)
--   ea_enable_paper     = true    (logs only)
--   ea_max_open_positions = 1
--   ea_daily_loss_pct = 5.0
--   ea_min_confidence_pct = 65
--
-- User must explicitly flip ea_enable_execution=true via UI to go live.

alter table app_settings
    add column if not exists ea_enable_execution    boolean default false,
    add column if not exists ea_enable_paper        boolean default true,
    add column if not exists ea_max_open_positions  integer default 1,
    add column if not exists ea_daily_loss_pct      numeric(5,2) default 5.0,
    add column if not exists ea_min_confidence_pct  integer default 65;

-- Index for EA queue endpoint (PENDING_PICKUP signals ordered by generated_at)
-- Already created in migration 008 as idx_rcs_signals_pickup; verify it exists.
create index if not exists idx_rcs_signals_pickup
    on rcs_signals (execution_status, generated_at desc)
    where execution_status = 'PENDING_PICKUP';
