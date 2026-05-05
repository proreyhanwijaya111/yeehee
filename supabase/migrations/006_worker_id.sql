-- Multi-PC support: unique worker_id per daemon installation.
--
-- Use case: user runs daemon on PC rumah + PC laptop sebagai backup. Each daemon
-- installer auto-generates DAEMON_WORKER_ID=<hostname>-<uuid6> di .env. Heartbeat
-- table now records which worker pushed the latest beat.
--
-- For now: workers compete on user_id (last writer wins for daemon_heartbeat
-- via existing unique(user_id) constraint). Foundation laid; active-passive
-- failover lock can be built on top later (via app_settings.active_worker_id
-- column + skip-push logic in daemon/runner.py).
--
-- Backward compat: column nullable, daemon writes "unknown-worker" if env var
-- absent, so old installers don't break.

alter table daemon_heartbeat
    add column if not exists worker_id text;

-- Optional index for filtering heartbeats by worker (analytics + future failover)
create index if not exists daemon_heartbeat_worker_idx
    on daemon_heartbeat (worker_id);
