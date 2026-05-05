-- Persist RCS composite output directly on signal_bundles row.
--
-- Why: previously RCS was only written to a separate `rcs_signals` table
-- read by /more/rcs-monitor. The home / signals UI's RcsPanel however reads
-- the latest signal_bundle and expected `bundle.rcs` to be populated. With
-- no column, mapBundleRowToSignalBundle hard-coded rcs=null and the panel
-- displayed "Belum ada data" even when daemon was healthy.
--
-- Storing the same JSON on the bundle row makes the panel work as a 1-shot
-- read (no separate table fetch / no PRIMARY-only dependency for display).
-- rcs_signals stays for execution flow + history monitoring.

alter table signal_bundles
    add column if not exists rcs jsonb;

-- No index needed — we only read latest bundle which is already indexed by created_at.
