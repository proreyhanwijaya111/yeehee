"""FastAPI service for MT5 Expert Advisor polling.

Runs on home PC (port 8001 default). EA pulls signals via HTTP, executes orders
in MT5, then reports back execution result.

Endpoints:
    GET  /healthz                       — quick liveness check
    GET  /api/ea/next-signal?ea=ID      — get next PENDING_PICKUP signal (claims it)
    POST /api/ea/report                 — EA reports execution result back
    POST /api/ea/heartbeat              — EA periodic heartbeat (every 60s)
    GET  /api/ea/config?ea=ID           — return safety + risk config for EA

Run:
    cd D:\\dextrade\\rcs
    uvicorn src.execution_api:app --host 0.0.0.0 --port 8001

Phase 10 (auto-execute) — currently STUB-real:
    - Endpoints work end-to-end
    - State managed via rcs_signals.execution_status field
    - But: NO signals get marked PENDING_PICKUP automatically yet.
      Daemon side need to flip status when:
        confidence_pct >= TELEGRAM_PUSH_THRESHOLD AND
        is_executable=true (manual user enable per signal OR auto-rule)
      That logic intentionally deferred — gives user time to validate v0.1
      composite indicator quality before letting EA execute live.

To enable auto-promote-to-PENDING-PICKUP for a signal:
    UPDATE rcs_signals SET execution_status='PENDING_PICKUP', is_executable=true
    WHERE id=N;

EA polls /next-signal, gets signal, executes, calls /report.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Path setup: allow running from rcs/ folder
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env from project root (yeehee-daemon/.env) — same approach as daemon/main.py
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    # Manual parse fallback (dotenv not installed)
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

try:
    from fastapi import FastAPI, HTTPException, Query
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Run: pip install -r rcs/requirements.txt")
    sys.exit(1)

# Supabase client (reuse from main daemon)
try:
    from supabase import create_client
except ImportError:
    print("supabase-py not installed. Run: pip install supabase")
    sys.exit(1)


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print(f"[execution_api] SUPABASE_URL + SUPABASE_*_KEY required.")
    print(f"[execution_api] Looked at: {ROOT}\\.env")
    print(f"[execution_api] Verify .env contains SUPABASE_URL=https://... and SUPABASE_ANON_KEY (or SERVICE_KEY)")
    # Don't exit — allow startup, fail per-request instead

_supa = None
def _get_supabase():
    global _supa
    if _supa is None and SUPABASE_URL and SUPABASE_KEY:
        _supa = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supa


app = FastAPI(
    title="yeehee RCS — EA Execution API",
    description="HTTP service for MT5 Expert Advisor polling.",
    version="0.1.0",
)


# ─── Request/Response models ────────────────────────────────────────────────────

class ExecutionReport(BaseModel):
    # signal_id Optional: for CLOSED_* reports from EA v0.2.2+, EA only knows
    # mt5_ticket_id. Server looks up signal_id by ticket. Open reports still
    # require signal_id (set by EA when executing).
    signal_id:           Optional[int] = None
    ea_instance_id:      str
    mt5_ticket_id:       Optional[int] = None
    mt5_account_login:   Optional[int] = None
    status:              str           # PENDING_BROKER | OPEN | REJECTED | CLOSED_*
    execution_price:     Optional[float] = None
    execution_lot:       float
    execution_sl:        Optional[float] = None
    execution_tp:        Optional[float] = None
    slippage_points:     Optional[int] = None
    rejected_reason:     Optional[str] = None
    pnl_money:           Optional[float] = None
    pnl_points:          Optional[int]   = None
    closed_at:           Optional[str]   = None
    close_price:         Optional[float] = None
    close_reason:        Optional[str]   = None
    account_balance_at_open: Optional[float] = None
    risk_pct_used:       Optional[float] = None


class HeartbeatPayload(BaseModel):
    ea_instance_id:   str
    account_login:    int
    account_balance:  Optional[float] = None
    account_equity:   Optional[float] = None
    open_positions:   Optional[int] = None
    is_paused:        bool = False
    # 2026-05-07: dynamic leverage display (migration 012). Legacy EAs (v0.2.0
    # and earlier) don't send this -> Optional. AccountInfoInteger(ACCOUNT_LEVERAGE)
    # returns int (e.g. 500 means 1:500). 0 means unlimited / undefined.
    account_leverage: Optional[int] = None


# ─── Endpoints ───────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Liveness check. Returns 200 if FastAPI alive + Supabase reachable."""
    supa = _get_supabase()
    if not supa:
        return {"status": "degraded", "reason": "supabase not configured"}
    try:
        r = supa.from_("app_settings").select("user_id").limit(1).execute()
        return {
            "status":   "ok",
            "supabase": "connected",
            "version":  "0.1.0",
            "ts":       datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"status": "degraded", "reason": str(e)[:100]}


# ─── MT5 spot mirror (broker-grade real-time spot) ─────────────────────────
# DextradeEA.mq5 POSTs current Bid+Ask every 5s; daemon GETs latest as Tier 0
# spot source. Cached in-memory (no Supabase round-trip needed — sub-ms latency).

_SPOT_CACHE: dict = {"bid": None, "ask": None, "ts": None, "ts_unix": 0.0}


class SpotPost(BaseModel):
    bid: float
    ask: float
    symbol: Optional[str] = "XAUUSD"
    ea_id:  Optional[str] = None


@app.post("/api/spot/post")
def post_spot(payload: SpotPost):
    """EA POSTs current broker spot. No auth (localhost-only network)."""
    if payload.bid <= 0 or payload.ask <= 0:
        raise HTTPException(status_code=400, detail="bid/ask must be > 0")
    if payload.ask < payload.bid:
        raise HTTPException(status_code=400, detail="ask < bid invalid")
    import time as _time
    _SPOT_CACHE["bid"] = payload.bid
    _SPOT_CACHE["ask"] = payload.ask
    _SPOT_CACHE["mid"] = (payload.bid + payload.ask) / 2.0
    _SPOT_CACHE["ts"]  = datetime.now(timezone.utc).isoformat()
    _SPOT_CACHE["ts_unix"] = _time.time()
    return {"ok": True, "received": {"bid": payload.bid, "ask": payload.ask}}


@app.get("/api/spot/latest")
def get_spot():
    """Daemon polls this. Returns broker spot if posted within 60s, else stale."""
    import time as _time
    if not _SPOT_CACHE.get("ts_unix"):
        return {"ok": False, "reason": "no spot posted yet"}
    age_s = _time.time() - _SPOT_CACHE["ts_unix"]
    if age_s > 60:
        return {"ok": False, "reason": "spot stale", "age_s": round(age_s, 1)}
    return {
        "ok":     True,
        "bid":    _SPOT_CACHE["bid"],
        "ask":    _SPOT_CACHE["ask"],
        "mid":    _SPOT_CACHE["mid"],
        "ts":     _SPOT_CACHE["ts"],
        "age_s":  round(age_s, 1),
    }


@app.get("/api/ea/next-signal")
def get_next_signal(ea: str = Query(..., description="EA instance ID")):
    """EA polling endpoint. Returns FRESH PENDING_PICKUP signal + claims it.

    Behavior:
      1. SWEEP stale signals: PENDING_PICKUP older than 180s -> EXPIRED.
         Prevents executing outdated entry levels (user spec 2026-05-07).
      2. Query rcs_signals WHERE execution_status='PENDING_PICKUP' AND is_executable=true
         AND generated_at >= now-180s
      3. Pick oldest fresh, mark as PICKED_UP atomically
      4. Return signal payload with all order fields

    EA must call /api/ea/report after attempting execution (success or fail).
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")

    try:
        # 1. Stale sweeper: any PENDING_PICKUP older than 180s -> EXPIRED.
        # Without this, after a position closes the EA picks up a stale
        # signal at outdated entry. User spec: queue is fresh-only.
        from datetime import timedelta as _td
        stale_cutoff = (datetime.now(timezone.utc) - _td(seconds=180)).isoformat()
        try:
            sweep = (
                supa.from_("rcs_signals")
                .update({"execution_status": "EXPIRED"})
                .eq("execution_status", "PENDING_PICKUP")
                .lt("generated_at", stale_cutoff)
                .execute()
            )
            # don't fail-loud if sweep returns empty / errors — best-effort
        except Exception:
            pass

        # 2. Claim oldest FRESH (within 180s) pending DIRECTIONAL signal.
        # Defense-in-depth: even if promote_signal_for_ea forgot to update
        # direction (legacy bug fixed 2026-05-07), reject WAIT signals here.
        # EA must NEVER execute a WAIT-direction signal — it's ambiguous.
        r = (
            supa.from_("rcs_signals")
            .select("*")
            .eq("execution_status", "PENDING_PICKUP")
            .eq("is_executable", True)
            .in_("direction", ["LONG", "SHORT"])
            .gte("generated_at", stale_cutoff)
            .order("generated_at", desc=False)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            return {"signal": None, "reason": "no pending signals"}

        sig = rows[0]
        # Claim it: update status to PICKED_UP (race-tolerant — Postgres UPDATE atomic per row)
        supa.from_("rcs_signals").update({
            "execution_status": "PICKED_UP",
        }).eq("id", sig["id"]).execute()

        # Build EA-friendly payload (only what EA needs)
        return {
            "signal": {
                "id":             sig["id"],
                "timeframe":      sig["timeframe"],
                "broker_symbol":  sig["broker_symbol"],
                "direction":      sig["direction"],
                "entry":          sig.get("entry"),
                "sl":             sig.get("sl"),
                "tp1":            sig.get("tp1"),
                "tp2":            sig.get("tp2"),
                "sl_points":      sig.get("sl_points"),
                "tp1_points":     sig.get("tp1_points"),
                "tp2_points":     sig.get("tp2_points"),
                "confidence_pct": sig["confidence_pct"],
                "rcs_score":      sig["rcs_score"],
                "spot_at_signal": sig["spot_price"],
                "model_version":  sig["model_version"],
                "generated_at":   sig["generated_at"],
            },
            "ea_instance_id": ea,
            "claimed_at":     datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


_TF_TO_STYLE = {"M5": "scalper", "M15": "intraday", "H1": "swing"}
_EXEC_TO_TRADE_STATUS = {
    "OPEN":            "OPEN",
    "PENDING_BROKER":  "OPEN",
    "CLOSED_TP":       "TP1",
    "CLOSED_SL":       "SL",
    "CLOSED_TRAILING": "SL",  # trailing exit reuses SL slot per existing UI mapping
    "CLOSED_MANUAL":   "MANUAL",
    "CLOSED_NEWS":     "EXPIRED",
}


def _mirror_to_active_trades(supa, report, signal_lookup: dict | None = None) -> None:
    """Mirror broker execution into active_trades (paper sim table).

    User spec 2026-05-07: paper bot = SHADOW of broker bot. Every broker
    execute → corresponding active_trades row. Same params (entry, sl, tp1,
    lot translates to risk_pct) and lifecycle (OPEN → TP/SL/MANUAL).

    Lookup signal_id → timeframe + direction (cached if signal_lookup passed,
    else queried fresh). Returns silently on any error — broker reporting
    must not be blocked by paper-mirror failures.
    """
    try:
        sid = report.signal_id
        ticket = report.mt5_ticket_id

        # Resolve style + side. For close-by-ticket flow we need to find the
        # original signal_id from the existing rcs_executions row.
        if not sid and ticket:
            existing = (
                supa.from_("rcs_executions")
                .select("signal_id")
                .eq("mt5_ticket_id", ticket)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows and rows[0].get("signal_id"):
                sid = rows[0]["signal_id"]
        if not sid:
            return  # cannot mirror without signal context

        # Lookup timeframe + direction
        sig = (signal_lookup or {}).get(sid)
        if not sig:
            r = (
                supa.from_("rcs_signals")
                .select("id, timeframe, direction")
                .eq("id", sid)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                return
            sig = rows[0]
        tf = sig.get("timeframe")
        side = sig.get("direction")
        style = _TF_TO_STYLE.get(tf)
        if not style or side not in ("LONG", "SHORT"):
            return

        # Map status. REJECTED is not mirrored (no paper row for failed orders).
        is_close = report.status.startswith("CLOSED_") if report.status else False
        if report.status == "REJECTED":
            return
        target_status = _EXEC_TO_TRADE_STATUS.get(report.status)
        if not target_status:
            return

        # Compute risk_pct from EA's reported risk_pct_used (% → fraction).
        # For close events, preserve risk_pct from existing row (0.01 fallback).
        risk_pct_frac = 0.01
        if report.risk_pct_used is not None:
            risk_pct_frac = float(report.risk_pct_used) / 100.0

        # Compute pnl_r for closed trades (PnL in money / risk in money).
        pnl_r = None
        pnl_pct = None
        if is_close and report.pnl_money is not None and report.account_balance_at_open:
            risk_dollar = report.account_balance_at_open * risk_pct_frac
            if risk_dollar > 0:
                pnl_r = float(report.pnl_money) / risk_dollar
            pnl_pct = (float(report.pnl_money) / report.account_balance_at_open) * 100.0

        # Find existing BROKER-MIRROR active_trades row. Fetch recent OPENs of
        # this style, filter "broker_mirror" tag in Python (avoids brittle
        # PostgREST jsonb operator syntax that may differ across supabase-py
        # versions). Only mirror-tagged OPEN rows are matched — daemon-strategy
        # paper rows are left untouched.
        existing = (
            supa.from_("active_trades")
            .select("id, status, reasons")
            .eq("user_id", "default")
            .eq("style", style)
            .eq("status", "OPEN")
            .order("opened_at", desc=True)
            .limit(5)
            .execute()
        )
        match_id = None
        for row in (existing.data or []):
            tags = row.get("reasons") or []
            if "broker_mirror" in tags:
                match_id = row["id"]
                break

        if report.status == "OPEN" and not match_id:
            # INSERT new mirror row
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            expiry = now + timedelta(hours={"scalper": 4, "intraday": 24, "swing": 72}[style])
            payload = {
                "user_id":     "default",
                "style":       style,
                "side":        side,
                "entry":       report.execution_price,
                "sl":          report.execution_sl,
                "tp1":         report.execution_tp,
                "original_sl": report.execution_sl,
                "status":      "OPEN",
                "opened_at":   now.isoformat(),
                "expiry_at":   expiry.isoformat(),
                "risk_pct":    risk_pct_frac,
                "confidence":  None,
                "regime":      None,
                "session":     None,
                # Marker for daemon update_open_trades to skip — broker
                # /api/ea/report drives this row's lifecycle, not candle bars.
                "reasons":     ["broker_mirror"],
                "risks":       [],
            }
            supa.from_("active_trades").insert(payload).execute()

        elif is_close and match_id:
            # UPDATE existing OPEN row to closed
            patch = {
                "status":      target_status,
                "closed_at":   report.closed_at or datetime.now(timezone.utc).isoformat(),
                "exit_price":  report.close_price,
                "exit_reason": report.close_reason,
                "pnl_r":       pnl_r,
                "pnl_pct":     pnl_pct,
            }
            supa.from_("active_trades").update(patch).eq("id", match_id).execute()
    except Exception as e:
        # Best-effort mirror — never break broker reporting. But LOG so we see.
        import traceback
        print(f"[mirror] FAIL {type(e).__name__}: {e}")
        traceback.print_exc()


@app.post("/api/ea/report")
def report_execution(report: ExecutionReport):
    """EA reports execution outcome. Inserts to rcs_executions, updates rcs_signals.
    ALSO mirrors to active_trades (paper sim) per user spec — bot paper shadows
    bot broker exactly.

    Report scenarios:
      - status=OPEN          → trade filled at execution_price, signal.execution_status=EXECUTED
      - status=REJECTED      → broker rejected, signal.execution_status=REJECTED
      - status=CLOSED_*      → trade closed, update execution row + close_price
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")

    try:
        is_close = report.status.startswith("CLOSED_") if report.status else False

        # CLOSE FLOW (EA v0.2.2+): UPDATE existing rcs_executions row by ticket
        # rather than INSERT new row. Eliminates duplicate-row pollution + stuck
        # OPEN orphans. EA only knows ticket on close (signal_id mapping
        # forgotten if EA restarted between open & close).
        if is_close and report.mt5_ticket_id and not report.signal_id:
            existing = (
                supa.from_("rcs_executions")
                .select("id, signal_id")
                .eq("mt5_ticket_id", report.mt5_ticket_id)
                .order("requested_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if not rows:
                # No matching ticket -- log warning, INSERT anyway as orphan
                # (server-side reconciliation can match later)
                pass
            else:
                row = rows[0]
                exec_id = row["id"]
                resolved_signal_id = row.get("signal_id")
                update_payload = {
                    "status":          report.status,
                    "closed_at":       report.closed_at or datetime.now(timezone.utc).isoformat(),
                    "close_price":     report.close_price,
                    "close_reason":    report.close_reason,
                    "pnl_money":       report.pnl_money,
                    "pnl_points":      report.pnl_points,
                }
                supa.from_("rcs_executions").update(update_payload).eq("id", exec_id).execute()
                # Also flip rcs_signals to EXECUTED (terminal state)
                if resolved_signal_id:
                    supa.from_("rcs_signals").update({
                        "execution_status": "EXECUTED",
                    }).eq("id", resolved_signal_id).execute()
                # 2026-05-08: removed _mirror_to_active_trades call. User
                # reverted spec: paper drives, broker mirrors via promote
                # signal flow (not via report mirror). Paper sim now
                # independent again.
                return {"ok": True, "execution_id": exec_id, "signal_id": resolved_signal_id,
                        "execution_status": "EXECUTED", "mode": "close-by-ticket"}

        # OPEN / REJECTED / legacy CLOSE flow: INSERT row
        exec_payload = {
            "signal_id":            report.signal_id,
            "mt5_ticket_id":        report.mt5_ticket_id,
            "mt5_symbol":           "XAUUSD",  # TODO read from rcs_signals
            "mt5_account_login":    report.mt5_account_login,
            "requested_at":         datetime.now(timezone.utc).isoformat(),
            "executed_at":          datetime.now(timezone.utc).isoformat() if report.status == "OPEN" else None,
            "execution_price":      report.execution_price,
            "execution_lot":        report.execution_lot,
            "execution_sl":         report.execution_sl,
            "execution_tp":         report.execution_tp,
            "slippage_points":      report.slippage_points,
            "status":               report.status,
            "rejected_reason":      report.rejected_reason,
            "pnl_money":            report.pnl_money,
            "pnl_points":           report.pnl_points,
            "closed_at":            report.closed_at,
            "close_price":          report.close_price,
            "close_reason":         report.close_reason,
            "account_balance_at_open": report.account_balance_at_open,
            "risk_pct_used":        report.risk_pct_used,
        }
        supa.from_("rcs_executions").insert(exec_payload).execute()

        # Update rcs_signals.execution_status (only when signal_id provided)
        new_signal_status = {
            "OPEN":            "EXECUTED",
            "PENDING_BROKER":  "EXECUTED",
            "REJECTED":        "REJECTED",
            "CLOSED_TP":       "EXECUTED",
            "CLOSED_SL":       "EXECUTED",
            "CLOSED_MANUAL":   "EXECUTED",
            "CLOSED_TRAILING": "EXECUTED",
            "CLOSED_NEWS":     "EXECUTED",
        }.get(report.status, "PICKED_UP")

        if report.signal_id:
            supa.from_("rcs_signals").update({
                "execution_status": new_signal_status,
            }).eq("id", report.signal_id).execute()

        # 2026-05-08: paper not shadow anymore (user reversed spec). Mirror
        # call removed. Paper sim opens via daemon's open_trade_if_eligible
        # independent of broker EA reports.
        return {"ok": True, "signal_id": report.signal_id, "execution_status": new_signal_status}
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.post("/api/ea/heartbeat")
def heartbeat(payload: HeartbeatPayload):
    """EA periodic alive ping + account status."""
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")
    payload_dict = {
        "ea_instance_id":  payload.ea_instance_id,
        "account_login":   payload.account_login,
        "ts":              datetime.now(timezone.utc).isoformat(),
        "account_balance": payload.account_balance,
        "account_equity":  payload.account_equity,
        "open_positions":  payload.open_positions,
        "is_paused":       payload.is_paused,
    }
    # account_leverage requires migration 012. Try with, fallback without
    # if column doesn't exist yet (graceful degradation).
    if payload.account_leverage is not None:
        payload_dict["account_leverage"] = payload.account_leverage
    try:
        supa.from_("rcs_ea_heartbeat").insert(payload_dict).execute()
        return {"ok": True, "received_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        # Retry without account_leverage if migration 012 not yet applied
        msg = str(e).lower()
        if payload.account_leverage is not None and ("account_leverage" in msg or "column" in msg):
            payload_dict.pop("account_leverage", None)
            try:
                supa.from_("rcs_ea_heartbeat").insert(payload_dict).execute()
                return {"ok": True, "received_at": datetime.now(timezone.utc).isoformat(),
                        "warning": "account_leverage dropped (migration 012 not applied)"}
            except Exception as e2:
                raise HTTPException(500, f"DB error (retry): {e2}")
        raise HTTPException(500, f"DB error: {e}")


@app.get("/api/ea/config")
def get_ea_config(ea: str = Query(..., description="EA instance ID")):
    """Returns safety + execution config for EA (read from app_settings).

    EA polls this every cycle → no EA restart needed when user changes
    settings via /more/settings/execution UI page.

    Includes BEP + trailing + daily cap (migration 011).
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")
    try:
        r = (
            supa.from_("app_settings")
            .select(
                "ea_enable_execution, ea_enable_paper, ea_max_open_positions, "
                "ea_daily_loss_pct, ea_min_confidence_pct, "
                "ea_max_trades_per_day, ea_risk_per_trade_pct, "
                "ea_enable_break_even, ea_break_even_trigger_pips, ea_break_even_lock_pips, "
                "ea_enable_trailing, ea_trailing_trigger_pips, ea_trailing_distance_pips"
            )
            .eq("user_id", "default")
            .limit(1)
            .execute()
        )
        rows = r.data or []
        row = rows[0] if rows else {}

        # Count today's trades for this EA's account (for cap enforcement)
        trades_today = 0
        try:
            tr = supa.from_("rcs_executions_today").select("trades_today").limit(1).execute()
            if tr.data:
                trades_today = int(tr.data[0].get("trades_today") or 0)
        except Exception:
            pass  # view may not exist yet

        max_trades_per_day = int(row.get("ea_max_trades_per_day") or 5)

        # NOTE: do NOT use `bool(x or default)` for fields where True is the
        # safe default — Python `False or True = True` flips a user's explicit
        # False back to True. Use `dict.get(key, default)` directly so stored
        # False is honored. Discovered 2026-05-07: ea_enable_paper stayed True
        # in API response after user PATCH set it to False.
        def _bool(field, default):
            v = row.get(field)
            if v is None:
                return default
            return bool(v)

        return {
            "ea_instance_id":      ea,
            # Safety flags
            "enable_execution":    _bool("ea_enable_execution", False),
            "enable_paper":        _bool("ea_enable_paper", True),
            # Limits
            "max_open_positions":  int(row.get("ea_max_open_positions") or 1),
            "max_trades_per_day":  max_trades_per_day,
            "trades_today":        trades_today,
            "trades_remaining":    max(0, max_trades_per_day - trades_today),
            "daily_loss_pct":      float(row.get("ea_daily_loss_pct") or 5.0),
            "min_confidence_pct":  int(row.get("ea_min_confidence_pct") or 65),
            # Risk per trade
            "risk_per_trade_pct":  float(row.get("ea_risk_per_trade_pct") or 1.0),
            # Break-even
            "enable_break_even":         _bool("ea_enable_break_even", True),
            "break_even_trigger_pips":   int(row.get("ea_break_even_trigger_pips") or 50),
            "break_even_lock_pips":      int(row.get("ea_break_even_lock_pips") or 5),
            # Trailing stop
            "enable_trailing":           _bool("ea_enable_trailing", True),
            "trailing_trigger_pips":     int(row.get("ea_trailing_trigger_pips") or 100),
            "trailing_distance_pips":    int(row.get("ea_trailing_distance_pips") or 30),
            "received_at":               datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        # Migration may not be applied — return safe defaults
        return {
            "ea_instance_id":      ea,
            "enable_execution":    False,
            "enable_paper":        True,
            "max_open_positions":  1,
            "max_trades_per_day":  5,
            "trades_today":        0,
            "trades_remaining":    5,
            "daily_loss_pct":      5.0,
            "min_confidence_pct":  65,
            "risk_per_trade_pct":  1.0,
            "enable_break_even":         True,
            "break_even_trigger_pips":   50,
            "break_even_lock_pips":      5,
            "enable_trailing":           True,
            "trailing_trigger_pips":     100,
            "trailing_distance_pips":    30,
            "received_at":         datetime.now(timezone.utc).isoformat(),
            "_warning":            f"using defaults: {str(e)[:80]}",
        }


# ─── Run ─────────────────────────────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.environ.get("RCS_API_PORT", "8001"))
    print(f"[execution_api] starting on port {port}")
    print(f"[execution_api] Supabase: {SUPABASE_URL}")
    print(f"[execution_api] EA polling: GET /api/ea/next-signal?ea=<EA_ID>")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
