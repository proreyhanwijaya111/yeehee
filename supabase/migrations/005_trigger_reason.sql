-- Opsi B: event-driven momentum trigger
--
-- Adds trigger_reason field to signal_bundles + daemon_heartbeat so the
-- web UI can show "Last update: triggered by price_spike_up_0.42pct at 13:42:05"
-- instead of static "auto-refresh 5 menit".
--
-- Possible values:
--   'scheduled'                    - regular 5-min cycle
--   'price_spike_up_0.42pct'        - real-time spot moved >0.3% within poll
--   'price_spike_down_0.51pct'
--   'atr_explosion_1.85x'           - last M5 bar range > 1.5x ATR(14)
--   'ema9_21_bullish_cross'         - EMA9 crossed above EMA21 on M5
--   'ema9_21_bearish_cross'
--   'volume_spike_3.2x'             - last bar volume > 3x rolling avg
--   'blackout_exit'                 - news blackout window just cleared
--   'manual'                        - operator forced a re-eval

alter table signal_bundles
    add column if not exists trigger_reason text default 'scheduled';

alter table daemon_heartbeat
    add column if not exists trigger_reason text;

-- Index for filtering bundles by trigger type (analytics: how often is each type fires?)
create index if not exists signal_bundles_trigger_idx
    on signal_bundles (trigger_reason, created_at desc);
