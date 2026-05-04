-- yeehee XAU/USD Signal Platform — Supabase Schema
-- Jalankan di Supabase SQL Editor: https://supabase.com/dashboard

-- ─── Signal Bundles (satu row per refresh engine) ───────────────────────────
create table if not exists signal_bundles (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz not null default now(),

    xau_price       numeric(12, 2),
    regime          text,
    session         text,
    in_news_blackout boolean default false,

    -- Final debate verdict
    final_action    text,   -- LONG / SHORT / FLAT
    signal_strength text,   -- STRONG / NORMAL / WEAK / FLAT / NEWS_STRONG
    confidence      numeric(5, 4),
    primary_driver  text,

    -- Per-style signals (JSON)
    scalper_signal  jsonb,
    intraday_signal jsonb,
    swing_signal    jsonb,

    -- Supporting data
    debate          jsonb,
    intermarket     jsonb,
    cot             jsonb,
    blackout_event  jsonb,
    upcoming_events jsonb,
    ai_pm_used      boolean default false
);

-- Index for time-series queries
create index if not exists signal_bundles_created_at_idx
    on signal_bundles (created_at desc);

-- ─── Individual Signals (flat, easy to query history) ────────────────────────
create table if not exists signals (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    bundle_id   uuid references signal_bundles(id) on delete cascade,

    style       text not null,  -- scalper / intraday / swing
    action      text not null,  -- LONG / SHORT / FLAT
    confidence  numeric(5, 4),
    confluence  integer,
    entry       numeric(12, 2),
    sl          numeric(12, 2),
    tp1         numeric(12, 2),
    tp2         numeric(12, 2),
    tp3         numeric(12, 2),
    rr_to_tp1   numeric(6, 3),
    rr_to_tp2   numeric(6, 3),
    regime      text,
    session     text,
    reasons     jsonb,
    risks       jsonb,
    xau_price   numeric(12, 2)
);

create index if not exists signals_created_at_idx  on signals (created_at desc);
create index if not exists signals_style_idx        on signals (style);
create index if not exists signals_action_idx       on signals (action);

-- ─── Alert Log (Telegram push history) ──────────────────────────────────────
create table if not exists alert_log (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    bundle_id   uuid references signal_bundles(id) on delete set null,
    channel     text default 'telegram',
    message     text,
    sent        boolean default false,
    error       text
);

-- ─── RLS Policies (enable after setup) ──────────────────────────────────────
-- alter table signal_bundles enable row level security;
-- alter table signals         enable row level security;
-- alter table alert_log       enable row level security;

-- Public read-only policy (adjust as needed)
-- create policy "allow_public_read" on signal_bundles for select using (true);
-- create policy "allow_public_read" on signals         for select using (true);

-- ─── Realtime (enable for live push to Next.js frontend) ─────────────────────
-- Di Supabase Dashboard → Database → Replication → pilih tabel signal_bundles

-- ─── Helper view: latest signal per style ────────────────────────────────────
create or replace view latest_signals as
select distinct on (style)
    id, created_at, style, action, confidence, entry, sl,
    tp1, tp2, tp3, rr_to_tp1, regime, session, xau_price
from signals
order by style, created_at desc;
