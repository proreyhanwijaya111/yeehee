"""Push daemon heartbeat to Supabase. Called periodically from main loop."""
from __future__ import annotations

import os
import platform
import socket
from datetime import datetime, timezone

try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


VERSION = "1.0.0"


def get_worker_id() -> str:
    """Multi-PC ready: returns the daemon's unique worker_id.

    Source of truth (in priority order):
      1. DAEMON_WORKER_ID env var (set by installer in .env)
      2. Auto-generated from hostname (first 8 chars sanitized)
      3. Fallback: 'unknown-worker'

    Different PCs running the daemon will have different worker_ids,
    so heartbeat history can attribute pushes to the right machine.
    """
    explicit = os.environ.get("DAEMON_WORKER_ID", "").strip()
    if explicit:
        return explicit
    try:
        host = socket.gethostname()
        clean = "".join(c.lower() for c in host if c.isalnum())[:8]
        return f"{clean}-auto" if clean else "unknown-worker"
    except Exception:
        return "unknown-worker"


def gather_health() -> dict:
    """Collect host info + resource usage. Tolerant to missing psutil."""
    hostname = socket.gethostname()
    info = {
        "hostname": hostname,
        "ip_address": _local_ip(),
        "version": VERSION,
        "worker_id": get_worker_id(),
        "cpu_percent": None,
        "ram_percent": None,
    }
    if HAS_PSUTIL:
        try:
            info["cpu_percent"] = round(psutil.cpu_percent(interval=0.5), 1)
            info["ram_percent"] = round(psutil.virtual_memory().percent, 1)
        except Exception:
            pass
    return info


def _local_ip() -> str | None:
    """Get local IP without making an actual connection (UDP socket trick)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return None


def push_heartbeat(store, last_signal_at: str | None = None,
                   last_mira_job_at: str | None = None,
                   error: str | None = None,
                   trigger_reason: str | None = None) -> None:
    """Opsi B: trigger_reason indicates why the last cycle ran
    ('scheduled', 'price_spike_up_0.42pct', 'ema9_21_bullish_cross', etc).
    Surfaces in UI so user knows real-time vs schedule cadence."""
    fields = gather_health()
    if last_signal_at:
        fields["last_signal_at"] = last_signal_at
    if last_mira_job_at:
        fields["last_mira_job_at"] = last_mira_job_at
    if trigger_reason:
        fields["trigger_reason"] = trigger_reason
    if error:
        fields["error"] = error[:500]
    else:
        fields["error"] = None
    store.push_heartbeat(**fields)
