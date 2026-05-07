-- Add account_leverage column to rcs_ea_heartbeat.
--
-- WHY: user wants /portfolio panel "Leverage" row to reflect actual Exness
-- demo account leverage setting (1:500 / 1:1000 / 1:Unlimited / etc), not
-- a hardcoded "1:Unlimited" label. Audit 2026-05-07: "kalau setting di
-- exness saya ubah leverage jadi 500 ikut berubah juga gak".
--
-- DextradeEA.mq5 v0.2.1+ sends account_leverage = AccountInfoInteger(ACCOUNT_LEVERAGE)
-- in heartbeat payload. /api/ea/heartbeat persists. UI reads.
--
-- Backward compat: column NULLABLE. Legacy EAs (v0.2.0 and earlier) that
-- don't send leverage just leave it NULL — UI displays fallback string.
--
-- APPLY VIA: Supabase dashboard SQL Editor, or `supabase db push` if CLI
-- linked. Idempotent (IF NOT EXISTS).

alter table rcs_ea_heartbeat
  add column if not exists account_leverage integer;

comment on column rcs_ea_heartbeat.account_leverage is
  'Broker leverage from MT5 AccountInfoInteger(ACCOUNT_LEVERAGE). E.g. 500 means 1:500 leverage. -1 or NULL = unlimited / unset. Sent by DextradeEA v0.2.1+ in /api/ea/heartbeat payload.';
