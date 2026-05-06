-- Local-agent toggle + Devil's Advocate engine selector.
-- See ai_agent/local_agents.py for the deterministic 12-agent pipeline.

alter table app_settings
    add column if not exists use_local_agents boolean      default true,
    add column if not exists da_engine        text         default 'local'
        check (da_engine in ('local', 'llm')),
    add column if not exists da_llm_provider  text         default null,
    add column if not exists da_llm_model     text         default null;

comment on column app_settings.use_local_agents is
    'true (default): run deterministic 12-agent local pipeline. false: legacy LLM 12-agent debate.';
comment on column app_settings.da_engine is
    'Devil''s Advocate engine. local = rule-based (free, fast). llm = call provider+model. Falls back to local on failure.';
comment on column app_settings.da_llm_provider is
    'When da_engine=llm: provider key (openrouter/anthropic/groq/etc). Falls back to default_llm_provider if null.';
comment on column app_settings.da_llm_model is
    'When da_engine=llm: model id. Falls back to default_llm_model if null.';
