"""Orphan execution sweeper — reconciles rcs_executions with MT5 broker history.

Why this exists:
  EA (DextradeEA.mq5) reports trade close via HTTP POST to /api/ea/report.
  When that POST fails silently (network blip, server slow, EA hung in modal,
  MT5 disconnect mid-call) the rcs_executions row stays status=OPEN forever.
  UI shows phantom "OPEN trade" + manual SQL reconciliation needed.

  Sweeper runs each daemon cycle (~3min):
    1. Query rcs_executions WHERE status='OPEN' AND opened_at < now-5min
    2. For each orphan, query MT5 history_deals_get(ticket=mt5_ticket_id)
    3. If broker shows position closed, PATCH rcs_executions row with close info
    4. Log reconciliation event

  Cost: 1 supabase SELECT + 1 UPDATE per orphan per cycle. Typical zero
  orphans = 1 SELECT/cycle = ~480 reads/day = trivial Supabase budget impact.

Author: 2026-05-07 (claude assist) — addresses recurring orphan #9 + #13.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any

try:
    import MetaTrader5 as mt5  # type: ignore
    HAS_MT5 = True
except ImportError:
    mt5 = None  # type: ignore
    HAS_MT5 = False


# Trades older than this without close-report = orphan candidate.
# 5 min = 300s grace. Genuine OPEN trades stay open hours; orphans hang because
# EA never reported. Closing within 5min before sweep = unlikely false positive.
ORPHAN_GRACE_SECONDS = 300


def _map_deal_reason_to_close(deal_reason: int, magic_modified: bool) -> tuple[str, str]:
    """Map MT5 DEAL_REASON_* to (status, close_reason) — mirrors EA logic.

    magic_modified hint = True if SL was modified post-open (BEP/trail).
    Without that hint we can't distinguish bep_hit vs trailing_sl_hit, so
    fall back to generic "trailing_or_bep" when SL deal reason fires.
    """
    if not HAS_MT5:
        return ("CLOSED_MANUAL", "no_mt5")
    if deal_reason == mt5.DEAL_REASON_TP:
        return ("CLOSED_TP", "tp_hit")
    if deal_reason == mt5.DEAL_REASON_SL:
        # Without per-ticket SL-modify tracker (lives in EA memory, gone on
        # disconnect), assume it could be bep/trail. Conservative: "sl_hit"
        # unless we add server-side SL-history scan later.
        return ("CLOSED_SL", "sl_hit_orphan")
    if deal_reason == mt5.DEAL_REASON_SO:
        return ("CLOSED_SL", "stop_out")
    if deal_reason in (mt5.DEAL_REASON_CLIENT, mt5.DEAL_REASON_MOBILE, mt5.DEAL_REASON_WEB):
        return ("CLOSED_MANUAL", "manual_orphan")
    if deal_reason == mt5.DEAL_REASON_EXPERT:
        return ("CLOSED_TRAILING", "expert_orphan")
    return ("CLOSED_MANUAL", f"reason_{deal_reason}_orphan")


def sweep_orphans(store, log=print) -> dict[str, int]:
    """Scan rcs_executions for orphan OPEN rows + reconcile with MT5 history.

    Returns: {'scanned': N, 'reconciled': N, 'still_open': N, 'errors': N}
    """
    if not HAS_MT5:
        return {"scanned": 0, "reconciled": 0, "still_open": 0, "errors": 0, "skipped": 1}
    if not getattr(store, "has_db", False):
        return {"scanned": 0, "reconciled": 0, "still_open": 0, "errors": 0, "skipped": 1}

    threshold = (datetime.now(timezone.utc) - timedelta(seconds=ORPHAN_GRACE_SECONDS)).isoformat()
    try:
        r = (
            store._client.from_("rcs_executions")
            .select("id, mt5_ticket_id, signal_id, executed_at, status")
            .eq("status", "OPEN")
            .lt("executed_at", threshold)
            .execute()
        )
        orphans = r.data or []
    except Exception as e:
        log(f"[orphan_sweeper] supabase query failed: {type(e).__name__}: {e}")
        return {"scanned": 0, "reconciled": 0, "still_open": 0, "errors": 1}

    out = {"scanned": len(orphans), "reconciled": 0, "still_open": 0, "errors": 0}
    if not orphans:
        return out

    # Ensure MT5 connected. If not, treat as skip (NOT error) — daemon may
    # init mt5 lazily when fetching candles. Sweeper just defers reconcile to
    # next cycle when mt5 is connected. errors=0 = no false alarm.
    if not mt5.terminal_info():
        return {"scanned": len(orphans), "reconciled": 0, "still_open": 0, "errors": 0, "skipped_no_mt5": 1}

    for row in orphans:
        ticket = row.get("mt5_ticket_id")
        if not ticket:
            continue
        try:
            # Check if position still open in broker
            positions = mt5.positions_get(ticket=int(ticket))
            if positions and len(positions) > 0:
                # Genuinely still open — not an orphan, just long-running trade
                out["still_open"] += 1
                continue

            # Position closed at broker — fetch close deal from history.
            # NOTE 2026-05-07: mt5.history_deals_get(position=...) kwarg does NOT
            # reliably filter on Exness MT5 builds — returns all deals in window.
            # Must filter manually by `d.position_id == ticket`.
            from_dt = datetime.now(timezone.utc) - timedelta(days=7)
            deals = mt5.history_deals_get(from_dt, datetime.now(timezone.utc))
            if not deals:
                log(f"[orphan_sweeper] ticket {ticket}: no deals in 7d window")
                out["errors"] += 1
                continue

            # Filter deals matching this position (open + close pair).
            position_deals = [d for d in deals if d.position_id == int(ticket)]
            if not position_deals:
                log(f"[orphan_sweeper] ticket {ticket}: no deals match position_id "
                    f"(position not found in 7d history)")
                out["errors"] += 1
                continue

            # Find the closing deal (DEAL_ENTRY_OUT or INOUT for reversal).
            close_deal = None
            for d in position_deals:
                if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                    close_deal = d
                    break
            if not close_deal:
                log(f"[orphan_sweeper] ticket {ticket}: position has open deal but no close "
                    f"deal — position may be partial or fresh open")
                out["errors"] += 1
                continue

            status, close_reason = _map_deal_reason_to_close(close_deal.reason, magic_modified=False)
            close_price = float(close_deal.price)
            pnl_money = float(close_deal.profit + close_deal.commission + close_deal.swap)
            closed_at = datetime.fromtimestamp(close_deal.time, tz=timezone.utc).isoformat()

            store._client.from_("rcs_executions").update({
                "status":       status,
                "closed_at":    closed_at,
                "close_price":  close_price,
                "close_reason": close_reason,
                "pnl_money":    round(pnl_money, 4),
            }).eq("id", row["id"]).execute()

            # Sync rcs_signals.execution_status terminal
            sig_id = row.get("signal_id")
            if sig_id:
                store._client.from_("rcs_signals").update({
                    "execution_status": "EXECUTED",
                }).eq("id", sig_id).execute()

            log(f"[orphan_sweeper] reconciled exec_id={row['id']} ticket={ticket} "
                f"-> {status} {close_reason} close={close_price:.2f} pnl=${pnl_money:.2f}")
            out["reconciled"] += 1
        except Exception as e:
            log(f"[orphan_sweeper] error reconciling ticket {ticket}: {type(e).__name__}: {e}")
            out["errors"] += 1

    return out
