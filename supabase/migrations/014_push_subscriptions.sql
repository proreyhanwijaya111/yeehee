-- Web Push subscriptions table.
--
-- One row per browser/device that subscribed to push notifications. The
-- daemon reads from this table after each cycle that produces a STRONG
-- signal and posts an encrypted push message to each endpoint.
--
-- Endpoint is unique — same browser re-subscribing UPSERTs to update keys.
-- Stale subscriptions (returning HTTP 410 Gone) should be deleted by the
-- daemon push helper.

create table if not exists push_subscriptions (
    id           uuid          primary key default gen_random_uuid(),
    user_id      text          not null default 'default',
    endpoint     text          not null unique,
    p256dh       text          not null,    -- public key for encryption (browser)
    auth         text          not null,    -- auth secret for encryption (browser)
    user_agent   text,
    label        text,                       -- optional friendly name (e.g. "Pixel HP")
    created_at   timestamptz   not null default now(),
    last_used_at timestamptz,
    last_error   text                        -- last delivery error, null if OK
);

create index if not exists idx_push_subscriptions_user
    on push_subscriptions(user_id);

-- Optional convenience: count subscriptions per user
create or replace view push_subscriptions_count as
select user_id, count(*) as n
  from push_subscriptions
 group by user_id;
