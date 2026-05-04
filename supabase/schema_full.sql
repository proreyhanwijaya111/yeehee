-- yeehee FULL schema (signal_bundles + signals + alert_log + app_settings +
-- provider_keys + agent_configs + mira_jobs + daemon_heartbeat) plus seeds.
--
-- Cara apply:
--   Buka Supabase Dashboard project lo -> SQL Editor -> New query
--   Paste isi file ini -> Run.
--
-- Idempotent: pakai 'if not exists' / 'on conflict do nothing'.
-- Aman di-run berkali-kali.

-- =====================================================================
-- 1. Signal bundles + flat signals + alert log
-- =====================================================================

create table if not exists signal_bundles (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz not null default now(),
    xau_price       numeric(12, 2),
    regime          text,
    session         text,
    in_news_blackout boolean default false,
    final_action    text,
    signal_strength text,
    confidence      numeric(5, 4),
    primary_driver  text,
    scalper_signal  jsonb,
    intraday_signal jsonb,
    swing_signal    jsonb,
    debate          jsonb,
    intermarket     jsonb,
    cot             jsonb,
    blackout_event  jsonb,
    upcoming_events jsonb,
    ai_pm_used      boolean default false
);
create index if not exists signal_bundles_created_at_idx on signal_bundles (created_at desc);

create table if not exists signals (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    bundle_id   uuid references signal_bundles(id) on delete cascade,
    style       text not null,
    action      text not null,
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
create index if not exists signals_created_at_idx on signals (created_at desc);
create index if not exists signals_style_idx       on signals (style);
create index if not exists signals_action_idx      on signals (action);

create table if not exists alert_log (
    id          uuid primary key default gen_random_uuid(),
    created_at  timestamptz not null default now(),
    bundle_id   uuid references signal_bundles(id) on delete set null,
    channel     text default 'telegram',
    message     text,
    sent        boolean default false,
    error       text
);

create or replace view latest_signals as
select distinct on (style)
    id, created_at, style, action, confidence, entry, sl,
    tp1, tp2, tp3, rr_to_tp1, regime, session, xau_price
from signals
order by style, created_at desc;

-- =====================================================================
-- 2. Multi-LLM Settings + Provider Keys + Agent Configs + Mira Queue
-- =====================================================================

create table if not exists app_settings (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    refresh_interval_minutes integer default 5,
    default_llm_provider text default 'openrouter',
    default_llm_model text default 'openai/gpt-oss-20b:free',
    use_per_agent_models boolean default false,
    use_llm_agents boolean default true,
    timezone text default 'Asia/Jakarta',
    daemon_active boolean default true,
    daemon_last_seen timestamptz,
    enable_news_blackout boolean default true,
    enable_mira_worker boolean default true,
    timeframe_focus text default 'all',
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id)
);

create table if not exists provider_keys (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    provider text not null,
    api_key text,
    base_url text,
    enabled boolean default true,
    last_validated_at timestamptz,
    last_error text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, provider)
);

create table if not exists agent_configs (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    agent_name text not null,
    enabled boolean default true,
    llm_provider text,
    llm_model text,
    temperature numeric default 0.4,
    max_tokens integer default 800,
    weight numeric default 1.0,
    timeframes text[] default array['scalping','intraday','swing'],
    custom_prompt text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, agent_name)
);

create table if not exists mira_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    chat_id text,
    role text not null,
    content text not null,
    status text default 'pending',
    response text,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz default now(),
    started_at timestamptz,
    completed_at timestamptz,
    error text
);
create index if not exists mira_jobs_status_created_idx on mira_jobs (status, created_at);
create index if not exists mira_jobs_chat_idx           on mira_jobs (chat_id, created_at);

create table if not exists daemon_heartbeat (
    id uuid primary key default gen_random_uuid(),
    user_id text default 'default',
    hostname text,
    ip_address text,
    version text,
    last_signal_at timestamptz,
    last_mira_job_at timestamptz,
    cpu_percent numeric,
    ram_percent numeric,
    error text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id)
);

-- =====================================================================
-- 3. Seed data: default settings + 9 agent configs
-- =====================================================================

insert into app_settings (user_id) values ('default')
on conflict (user_id) do nothing;

insert into agent_configs (user_id, agent_name, weight, timeframes) values
  ('default', 'htf_bias',          1.0, array['scalping','intraday','swing']),
  ('default', 'session_phase',     0.8, array['scalping','intraday']),
  ('default', 'ltf_technical',     1.0, array['scalping','intraday','swing']),
  ('default', 'liquidity_smc',     1.2, array['scalping','intraday']),
  ('default', 'order_flow',        1.0, array['intraday','swing']),
  ('default', 'news_proximity',    1.5, array['scalping','intraday','swing']),
  ('default', 'volatility',        0.7, array['scalping','intraday','swing']),
  ('default', 'devils_advocate',   1.5, array['scalping','intraday','swing']),
  ('default', 'synthesizer',       1.0, array['scalping','intraday','swing'])
on conflict (user_id, agent_name) do nothing;

-- =====================================================================
-- DONE. Verify with:
--   select count(*) from app_settings;       -- expect 1
--   select count(*) from agent_configs;      -- expect 9
--   select count(*) from signal_bundles;     -- expect 0 (will fill once daemon runs)
-- =====================================================================
