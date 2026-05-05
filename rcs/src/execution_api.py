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
    print("[execution_api] SUPABASE_URL + SUPABASE_*_KEY required in env. Check rcs/.env")
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
    signal_id:           int
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


@app.get("/api/ea/next-signal")
def get_next_signal(ea: str = Query(..., description="EA instance ID")):
    """EA polling endpoint. Returns oldest PENDING_PICKUP signal + claims it.

    Behavior:
      - Query rcs_signals WHERE execution_status='PENDING_PICKUP' AND is_executable=true
      - Pick oldest, mark as PICKED_UP atomically
      - Return signal payload with all order fields

    EA must call /api/ea/report after attempting execution (success or fail).
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")

    try:
        r = (
            supa.from_("rcs_signals")
            .select("*")
            .eq("execution_status", "PENDING_PICKUP")
            .eq("is_executable", True)
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


@app.post("/api/ea/report")
def report_execution(report: ExecutionReport):
    """EA reports execution outcome. Inserts to rcs_executions, updates rcs_signals.

    Report scenarios:
      - status=OPEN          → trade filled at execution_price, signal.execution_status=EXECUTED
      - status=REJECTED      → broker rejected, signal.execution_status=REJECTED
      - status=CLOSED_*      → trade closed, update execution row + close_price
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")

    try:
        # Insert into rcs_executions
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

        # Update rcs_signals.execution_status
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

        supa.from_("rcs_signals").update({
            "execution_status": new_signal_status,
        }).eq("id", report.signal_id).execute()

        return {"ok": True, "signal_id": report.signal_id, "execution_status": new_signal_status}
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.post("/api/ea/heartbeat")
def heartbeat(payload: HeartbeatPayload):
    """EA periodic alive ping + account status."""
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")
    try:
        supa.from_("rcs_ea_heartbeat").insert({
            "ea_instance_id":  payload.ea_instance_id,
            "account_login":   payload.account_login,
            "ts":              datetime.now(timezone.utc).isoformat(),
            "account_balance": payload.account_balance,
            "account_equity":  payload.account_equity,
            "open_positions":  payload.open_positions,
            "is_paused":       payload.is_paused,
        }).execute()
        return {"ok": True, "received_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.get("/api/ea/config")
def get_ea_config(ea: str = Query(..., description="EA instance ID")):
    """Returns safety config for EA (read from app_settings).

    EA can use this to dynamically toggle paper mode, enable execution, etc.
    without restarting EA.
    """
    supa = _get_supabase()
    if not supa:
        raise HTTPException(503, "Supabase not configured")
    try:
        r = (
            supa.from_("app_settings")
            .select("ea_enable_execution, ea_enable_paper, ea_max_open_positions, ea_daily_loss_pct, ea_min_confidence_pct")
            .eq("user_id", "default")
            .limit(1)
            .execute()
        )
        rows = r.data or []
        row = rows[0] if rows else {}
        return {
            "ea_instance_id":      ea,
            "enable_execution":    bool(row.get("ea_enable_execution") or False),
            "enable_paper":        bool(row.get("ea_enable_paper") or True),
            "max_open_positions":  int(row.get("ea_max_open_positions") or 1),
            "daily_loss_pct":      float(row.get("ea_daily_loss_pct") or 5.0),
            "min_confidence_pct":  int(row.get("ea_min_confidence_pct") or 65),
            "received_at":         datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        # Migration may not be applied — return safe defaults
        return {
            "ea_instance_id":      ea,
            "enable_execution":    False,
            "enable_paper":        True,
            "max_open_positions":  1,
            "daily_loss_pct":      5.0,
            "min_confidence_pct":  65,
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
