"""yeehee daemon — main entrypoint.

Run with:    python -m daemon.main

Loops:
- Signal worker: every N minutes (refresh_interval_minutes), runs run_once
- Mira worker:   every 5 seconds, polls mira_jobs queue
- Heartbeat:     every 30 seconds, pushes status to Supabase

All loops share a single SettingsStore so config can be hot-updated from the UI.
"""
from __future__ import annotations

import os
import sys
import time
import signal
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

# .env support — try-import dotenv, fall back to manual parse
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# Add project root to sys.path so `from ai_agent...` works when running -m daemon.main
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


from ai_agent.orchestrator import SettingsStore  # noqa: E402
from daemon.runner import run_once  # noqa: E402
from daemon.mira import MiraConsumer  # noqa: E402
from daemon.heartbeat import push_heartbeat, VERSION  # noqa: E402
from daemon.momentum_detector import MomentumWatcher, TriggerEvent  # noqa: E402

# Telegram interactive bot (optional; only spawns thread if creds set).
try:
    from notify.telegram_bot import run_telegram_bot  # noqa: E402
    TELEGRAM_BOT_AVAILABLE = True
except Exception as _e:
    TELEGRAM_BOT_AVAILABLE = False

# Opsi B: poll cadence for the momentum watcher (seconds).
# Twelve Data free tier = 800 req/day. 15s poll = 5,760 req/day → exceeds free.
# Use 30s poll = 2,880 req/day → still over but with the price cache + yfinance
# fallback we can avoid hitting Twelve Data every cycle. Adjust if hit quota.
WATCHER_POLL_SECONDS = 30

# Min seconds between any full-pipeline runs (prevent trigger storms from blowing
# LLM token budget). Even if 5 triggers fire in 5 minutes, we cap at 1 per minute.
MIN_FULL_EVAL_INTERVAL_S = 60


_SHUTDOWN = threading.Event()


def banner():
    print("=" * 56)
    print(f"  yeehee daemon v{VERSION}")
    print("  XAU/USD signal worker + Mira chatbot consumer")
    print("=" * 56)


def signal_loop(store: SettingsStore, log=print):
    """Generate signals — Opsi B: scheduled cycle + event-driven momentum trigger.

    Flow:
      Every WATCHER_POLL_SECONDS:
        1. Quick price + 5m feature poll (cheap)
        2. MomentumWatcher.evaluate(...) checks trigger conditions
        3. If trigger fires AND last_full_eval > MIN_FULL_EVAL_INTERVAL_S ago:
             → run_once() with trigger_reason
        4. Else if scheduled interval passed:
             → run_once() with trigger_reason='scheduled'
        5. Else: sleep until next poll
    """
    from data.price_fetcher import fetch_realtime_xau_spot, fetch_xau
    from data.calendar_fetcher import in_news_blackout
    from features.technical import add_all

    last_signal_at: str | None = None
    watcher = MomentumWatcher(log=log)

    def _run_full(reason: str) -> None:
        """Execute a full run_once and update watcher state. Catches errors."""
        nonlocal last_signal_at
        log(f"[signal] starting cycle (reason={reason})")
        try:
            settings_local = store.app_settings()
            bundle = run_once(store, settings_local, log=log, trigger_reason=reason)
            last_signal_at = bundle.get("timestamp")
            watcher.mark_full_eval()
            push_heartbeat(store, last_signal_at=last_signal_at, error=None,
                           trigger_reason=reason)
        except Exception as e:
            log(f"[signal] cycle error ({reason}): {e!r}")
            traceback.print_exc()
            push_heartbeat(store, last_signal_at=last_signal_at,
                           error=f"signal cycle ({reason}): {e}",
                           trigger_reason=reason)

    while not _SHUTDOWN.is_set():
        try:
            settings = store.app_settings()
            interval_min = max(1, int(settings.get("refresh_interval_minutes", 5)))

            if not settings.get("daemon_active", True):
                log("[signal] daemon paused via settings — sleeping 60s")
                _wait_or_shutdown(60)
                continue

            now = time.time()
            scheduled_due = (now - watcher.last_full_eval_at) >= interval_min * 60
            min_interval_ok = (now - watcher.last_full_eval_at) >= MIN_FULL_EVAL_INTERVAL_S

            # Quick poll for momentum detection. Failures here = skip this poll, don't crash.
            trigger: TriggerEvent | None = None
            try:
                # Cheap poll: real-time price + cached 5m bars (use_cache=True)
                rt = fetch_realtime_xau_spot()
                price_now = float(rt.get("price") or 0)
                if price_now > 0:
                    df_5m_quick = add_all(fetch_xau("5m"))
                    in_blk_now, _ = in_news_blackout(datetime.now(timezone.utc)) \
                        if settings.get("enable_news_blackout", True) else (False, None)
                    trigger = watcher.evaluate(
                        price_now=price_now,
                        df_5m=df_5m_quick,
                        in_blackout_now=bool(in_blk_now),
                    )
            except Exception as e:
                # Don't break the loop on poll failure — just log and proceed
                log(f"[signal] poll error: {e!r}")

            # Decide what to run
            if trigger and min_interval_ok:
                _run_full(reason=trigger.reason)
            elif scheduled_due:
                _run_full(reason="scheduled")
            # else: just continue polling

            _wait_or_shutdown(WATCHER_POLL_SECONDS)
        except Exception as e:
            log(f"[signal] outer error: {e!r}")
            traceback.print_exc()
            _wait_or_shutdown(30)


def mira_loop(store: SettingsStore, log=print):
    """Process Mira chatbot jobs every 5 seconds."""
    settings = store.app_settings()
    consumer = MiraConsumer(store, settings)
    last_refresh = 0.0
    last_job_at: str | None = None

    while not _SHUTDOWN.is_set():
        try:
            # Refresh creds + settings every 60s (so UI changes take effect quickly)
            now = time.time()
            if now - last_refresh > 60:
                consumer._refresh_credentials()
                last_refresh = now

            if not consumer.enabled:
                _wait_or_shutdown(15)
                continue

            n = consumer.poll_once(max_jobs=5)
            if n > 0:
                log(f"[mira] processed {n} job(s)")
                last_job_at = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            log(f"[mira] loop error: {e!r}")
        finally:
            _wait_or_shutdown(5)


def heartbeat_loop(store: SettingsStore, log=print):
    """Push heartbeat every 30s."""
    while not _SHUTDOWN.is_set():
        try:
            push_heartbeat(store)
        except Exception as e:
            log(f"[heartbeat] {e!r}")
        _wait_or_shutdown(30)


def _wait_or_shutdown(seconds: float) -> None:
    """Sleep that wakes early on SIGINT."""
    _SHUTDOWN.wait(timeout=seconds)


def main():
    banner()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        print("[fatal] SUPABASE_URL + SUPABASE_ANON_KEY/SUPABASE_SERVICE_KEY harus di-set di .env")
        sys.exit(1)

    print(f"[boot] Supabase: {supabase_url}")
    store = SettingsStore(supabase_url=supabase_url, supabase_key=supabase_key)
    if not store.has_db:
        print("[fatal] could not connect to Supabase")
        sys.exit(2)

    settings = store.app_settings()
    print(f"[boot] settings: refresh={settings.get('refresh_interval_minutes')}min "
          f"focus={settings.get('timeframe_focus')} "
          f"llm_agents={settings.get('use_llm_agents')} "
          f"mira={settings.get('enable_mira_worker')}")

    # Initial heartbeat
    push_heartbeat(store)

    threads = [
        threading.Thread(target=signal_loop,    args=(store,), name="signal-loop",    daemon=True),
        threading.Thread(target=mira_loop,      args=(store,), name="mira-loop",      daemon=True),
        threading.Thread(target=heartbeat_loop, args=(store,), name="heartbeat-loop", daemon=True),
    ]
    if TELEGRAM_BOT_AVAILABLE:
        threads.append(threading.Thread(
            target=run_telegram_bot,
            args=(store,),
            kwargs={"log": print, "shutdown_flag": _SHUTDOWN},
            name="telegram-bot",
            daemon=True,
        ))
    for t in threads:
        t.start()
    print(f"[boot] {len(threads)} loops started (telegram_bot={'on' if TELEGRAM_BOT_AVAILABLE else 'off'})")

    # Graceful shutdown on Ctrl+C
    def _handle_sigint(_sig, _frm):
        print("\n[shutdown] received SIGINT")
        _SHUTDOWN.set()

    signal.signal(signal.SIGINT, _handle_sigint)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_sigint)

    try:
        while not _SHUTDOWN.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        _SHUTDOWN.set()

    print("[shutdown] waiting for loops to finish...")
    for t in threads:
        t.join(timeout=10)
    print("[shutdown] done")


if __name__ == "__main__":
    main()
