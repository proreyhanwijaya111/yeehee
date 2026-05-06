"""Native Web Push delivery — daemon-side companion to the frontend
/more/settings/notifications subscription flow.

When daemon detects a STRONG signal (in maybe_push_signal hook), this module
reads all rows from Supabase push_subscriptions and posts an encrypted Web
Push message to each endpoint via pywebpush.

Env required (set in PC rumah .env via /more/settings/daemon installer or
manually):
    VAPID_PUBLIC_KEY    — same as web NEXT_PUBLIC_VAPID_PUBLIC_KEY
    VAPID_PRIVATE_KEY   — server private key (32 bytes b64url)
    VAPID_SUBJECT       — mailto:lo@email.com (push providers require contact)

Subscription rows that return HTTP 410 Gone or 404 are deleted (stale).

This is the COMPLEMENT to notify/push.py (Telegram). Both fire on the same
maybe_push hook — daemon decides which channels are configured.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

try:
    from pywebpush import webpush, WebPushException  # type: ignore
    PYWEBPUSH_AVAILABLE = True
except ImportError:
    PYWEBPUSH_AVAILABLE = False
    WebPushException = Exception  # type: ignore


# Subset of bundle fields the SW push handler renders
def _format_payload(bundle: dict) -> dict:
    """Compact JSON payload — Telegram has 4096 char limit, browser push ~4kB."""
    debate = bundle.get("debate") or {}
    rcs    = bundle.get("rcs") or {}
    action = debate.get("final_action", "?")
    strength = debate.get("signal_strength", "?")
    conf = float(debate.get("confidence") or 0)
    price = bundle.get("xau_price", 0)
    regime = bundle.get("regime", "?")

    # Find directional per-style with levels. Priority: matching debate dir,
    # else any non-FLAT per-style (so push fires when debate FLAT but style hot).
    sig_for_levels = None
    sig_style = None
    if action in ("LONG", "SHORT"):
        for k in ("intraday", "scalper", "swing"):
            s = bundle.get(k) or {}
            if s.get("side") == action and s.get("entry"):
                sig_for_levels = s; sig_style = k
                break
    if sig_for_levels is None:
        for k in ("intraday", "scalper", "swing"):
            s = bundle.get(k) or {}
            if s.get("side") in ("LONG", "SHORT") and s.get("entry"):
                sig_for_levels = s; sig_style = k
                break

    header_action = action if action in ("LONG", "SHORT") else (
        sig_for_levels.get("side") if sig_for_levels else action
    )

    title_suffix = f" · {sig_style}" if sig_style and action == "FLAT" else ""
    title = f"{header_action} XAU · {strength}{title_suffix}"
    body_parts = [f"${price:.2f} · conf {int(conf*100)}% · regime {regime}"]
    if sig_for_levels:
        body_parts.append(
            f"Entry {sig_for_levels.get('entry'):.2f} → SL {sig_for_levels.get('sl'):.2f} → TP1 {sig_for_levels.get('tp1'):.2f}"
        )
    if rcs:
        body_parts.append(
            f"RCS {rcs.get('direction', '?')} score {float(rcs.get('rcs_score') or 0):+.2f}"
        )
    return {
        "title": title,
        "body":  "\n".join(body_parts),
        "tag":   f"sig-{header_action}-{int(price)}",
        "url":   "/portfolio",
        "requireInteraction": False,
    }


def _read_subscriptions(store) -> list[dict]:
    """Returns [{id, endpoint, p256dh, auth}] for active user."""
    if not store or not getattr(store, "_client", None):
        return []
    try:
        r = (
            store._client.from_("push_subscriptions")
            .select("id, endpoint, p256dh, auth")
            .eq("user_id", "default")
            .execute()
        )
        return r.data or []
    except Exception:
        return []


def _delete_subscription(store, sub_id: str, log=print) -> None:
    if not store or not getattr(store, "_client", None):
        return
    try:
        store._client.from_("push_subscriptions").delete().eq("id", sub_id).execute()
        log(f"[web-push] deleted stale subscription {sub_id}")
    except Exception as e:
        log(f"[web-push] delete failed {sub_id}: {e!r}")


def maybe_push_web_signal(store, bundle: dict, log=print) -> dict:
    """Fire-and-log web push to all subscribed devices for a signal.

    Returns {pushed: bool, sent: int, failed: int, reason: str}.
    Should be called AFTER eligibility check (same threshold as Telegram).
    Caller (daemon/runner.py) wraps this in try/except.
    """
    out = {"pushed": False, "sent": 0, "failed": 0, "reason": ""}

    if not PYWEBPUSH_AVAILABLE:
        out["reason"] = "pywebpush not installed (pip install pywebpush)"
        return out

    public  = os.environ.get("VAPID_PUBLIC_KEY")  or os.environ.get("NEXT_PUBLIC_VAPID_PUBLIC_KEY")
    private = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_SUBJECT", "mailto:admin@yeehee.local")

    if not public or not private:
        out["reason"] = "VAPID keys not set in env"
        return out

    subs = _read_subscriptions(store)
    if not subs:
        out["reason"] = "no subscriptions"
        return out

    payload_obj = _format_payload(bundle)
    payload_json = json.dumps(payload_obj, ensure_ascii=False)

    sent = 0
    failed = 0
    for sub in subs:
        endpoint = sub.get("endpoint")
        p256dh   = sub.get("p256dh")
        auth     = sub.get("auth")
        if not endpoint or not p256dh or not auth:
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys":     {"p256dh": p256dh, "auth": auth},
                },
                data=payload_json,
                vapid_private_key=private,
                vapid_claims={"sub": subject},
                ttl=300,
            )
            sent += 1
        except WebPushException as e:
            failed += 1
            status = getattr(getattr(e, "response", None), "status_code", None)
            log(f"[web-push] failed {endpoint[:60]}... HTTP {status}: {str(e)[:120]}")
            if status in (404, 410):
                _delete_subscription(store, sub.get("id"), log=log)
        except Exception as e:
            failed += 1
            log(f"[web-push] err {endpoint[:60]}...: {e!r}")

    out["sent"] = sent
    out["failed"] = failed
    out["pushed"] = sent > 0
    out["reason"] = f"{sent}/{len(subs)} sent" + (f", {failed} failed" if failed else "")
    return out
