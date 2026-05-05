-- Multi-PC active-passive lock.
--
-- Problem: kalau 2 daemon (PC rumah + PC laptop) running concurrent dengan same
-- user_id, dua-duanya push signal_bundles tiap cycle → duplicate rows di DB.
-- daemon_heartbeat last-writer-wins (unique(user_id)), jadi UI cuma keliatan
-- 1 worker meskipun ada 2.
--
-- Solution:
--   1. daemon_heartbeat unique(user_id, worker_id) — biar setiap worker punya
--      row sendiri yang ga ke-overwrite.
--   2. app_settings.active_worker_id — election: ONE primary per user_id.
--   3. Daemon code skip push_signal_bundle + open_trade kalau bukan primary.
--      Standby tetap push heartbeat (visibility).
--   4. Auto-failover: kalau primary heartbeat stale > 10 menit, standby boleh
--      claim primary.
--
-- Election semantics (handled in Python, not DB):
--   active_worker_id NULL                                -> any worker claims (first-come)
--   active_worker_id = self                              -> PRIMARY (push everything)
--   active_worker_id = other AND heartbeat fresh         -> STANDBY (heartbeat only)
--   active_worker_id = other AND heartbeat stale (>10m)  -> claim FAILOVER

-- =====================================================================
-- Step 1: app_settings — election state
-- =====================================================================
alter table app_settings
    add column if not exists active_worker_id  text,
    add column if not exists active_claimed_at timestamptz;

-- =====================================================================
-- Step 2: daemon_heartbeat — multi-row per worker
-- =====================================================================
-- Backfill: any existing row with NULL worker_id gets a placeholder so the
-- new unique constraint (user_id, worker_id) doesn't reject it.
update daemon_heartbeat
   set worker_id = coalesce(worker_id, hostname || '-legacy')
 where worker_id is null;

-- Drop old unique-on-user_id (last-writer-wins behaviour we don't want anymore)
alter table daemon_heartbeat
    drop constraint if exists daemon_heartbeat_user_id_key;

-- New unique allows multiple workers per user_id, each with own row
create unique index if not exists daemon_heartbeat_user_worker_uidx
    on daemon_heartbeat (user_id, worker_id);

-- =====================================================================
-- Step 3: workers status view (for UI)
-- =====================================================================
create or replace view daemon_workers_status as
select
    user_id,
    worker_id,
    hostname,
    ip_address,
    version,
    last_signal_at,
    updated_at as last_heartbeat_at,
    extract(epoch from (now() - updated_at))::int as heartbeat_age_seconds,
    case
        when updated_at > now() - interval '2 minutes'  then 'fresh'
        when updated_at > now() - interval '10 minutes' then 'recent'
        else 'stale'
    end as status,
    error,
    cpu_percent,
    ram_percent,
    trigger_reason
from daemon_heartbeat
where worker_id is not null
order by updated_at desc;
