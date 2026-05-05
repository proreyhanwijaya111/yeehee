-- Forward-test trade tracker: align with EA BEP/trailing behavior.
--
-- Before this migration, TP1/TP2 were "soft hits" — flagged but didn't move
-- SL or close trade. Result: trade reaches TP2 (+1.7R floating profit) then
-- reverses to SL (-1R loss) and gets recorded as -1R. That's NOT what the EA
-- does (EA moves SL to entry on BEP trigger), so portfolio winrate
-- understates what live trading would yield.
--
-- Adds:
--   original_sl  : frozen at trade open. Used for pnl_r normalization so 1R
--                  is always = original_risk (not moved-up SL).
--   sl_moved_at  : timestamp when SL was last moved by BEP/lock-TP1 logic.
--                  null = SL never moved from original.
--
-- After migration:
--   - TP1 hit  → SL = entry (BEP, lock 0R)
--   - TP2 hit  → SL = TP1   (lock +1R)
--   - SL hit   → pnl_r = (current_sl - entry) / |entry - original_sl|
--                so BEP exits show +0R, lock-TP1 exits show +1R.

alter table active_trades
    add column if not exists original_sl numeric(10, 2),
    add column if not exists sl_moved_at timestamptz;

-- Backfill: existing trades use their current sl as original_sl
update active_trades
   set original_sl = sl
 where original_sl is null;
