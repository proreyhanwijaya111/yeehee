-- Telegram push integration — store bot token + chat IDs + toggle in app_settings.
--
-- Why in app_settings:
--   - User configures via /more/settings/telegram UI form (already exists)
--   - Daemon reads at runtime via SettingsStore
--   - Survives daemon restart (vs env file editing)
--
-- Security note: bot token in DB. RLS not applied yet — anon can read.
-- Mitigations: (1) rotate token kalau leaked, (2) Telegram bot can only message
-- pre-authorized chat IDs (set via /BotFather + bot's privacy mode).

alter table app_settings
    add column if not exists telegram_bot_token text,
    add column if not exists telegram_chat_id   text,    -- comma-separated multi-user OK
    add column if not exists enable_telegram_push boolean default true;

-- Note: existing legacy users with TELEGRAM_BOT_TOKEN env var still work.
-- Daemon reads Supabase first, falls back to env. UI form writes to Supabase.
