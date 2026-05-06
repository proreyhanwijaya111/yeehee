-- Audit log: per-cycle agent verdicts + engine metadata.
-- Powers /more/settings/agents/audit page (last 20 cycles, fallback log,
-- engine usage stats).

alter table signal_bundles
    add column if not exists agent_verdicts jsonb,
    add column if not exists engine_meta    jsonb;

comment on column signal_bundles.agent_verdicts is
    'Array of {name, verdict, confidence, reasoning, engine, latency_ms} per agent. Populated by daemon when use_local_agents=true.';
comment on column signal_bundles.engine_meta is
    '{da_engine, da_fallback_used, total_latency_ms, engine: local-12-agent|llm-9-agent} cycle metadata.';

-- Convenience view for audit page (last 20 cycles)
create or replace view agent_audit_recent as
select
    timestamp,
    debate->>'engine'    as engine,
    debate->>'final_action' as final_action,
    (debate->>'confidence')::numeric as confidence,
    engine_meta->>'da_engine' as da_engine,
    (engine_meta->>'da_fallback_used')::boolean as da_fallback_used,
    (engine_meta->>'total_latency_ms')::int as total_latency_ms,
    agent_verdicts
  from signal_bundles
 where engine_meta is not null
 order by timestamp desc
 limit 20;
