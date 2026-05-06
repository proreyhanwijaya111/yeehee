"""Telegram push integration — called from daemon/runner.py after each cycle.

Pushes alert ke Telegram saat:
    - 12-agent debate signal_strength = STRONG dengan confidence >= threshold
    - OR RCS confidence_pct >= 70% AND direction != WAIT
    - AND not duplicate of last push (dedupe via simple state file + signal hash)
    - AND user hasn't disabled push (app_settings.enable_telegram_push)

Config sources (priority):
    1. Supabase app_settings.telegram_bot_token + telegram_chat_id (UI form)
    2. Env vars TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (legacy / installer)

Output:
    Compact HTML message with:
    - Direction + strength + confidence
    - Entry/SL/TP1/TP2 levels (from primary signal)
    - 12-agent primary driver
    - RCS score + top driver (if available)
    - Disclaimer: indikator only, lot size lewat Kalkulator
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests


PUSH_STATE_FILE = Path(__file__).resolve().parent.parent / "data_cache" / "rcs_push_state.json"
PUSH_DEBOUNCE_MIN = 30   # don't push same signal twice within 30 min

# Default thresholds (can be overridden via app_settings)
DEFAULT_MIN_CONFIDENCE_DEBATE = 0.65
DEFAULT_MIN_CONFIDENCE_RCS    = 70


def _load_state() -> dict:
    if PUSH_STATE_FILE.exists():
        try:
            return json.loads(PUSH_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_hash": "", "last_push_at": ""}


def _save_state(state: dict) -> None:
    try:
        PUSH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PUSH_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _resolve_credentials(store) -> tuple[Optional[str], list[int]]:
    """Returns (bot_token, [chat_ids]). Empty if not configured.
    Priority: Supabase app_settings > env vars.
    """
    token: Optional[str] = None
    chat_ids: list[int] = []

    # Try Supabase app_settings first
    if store and getattr(store, "has_db", False):
        try:
            r = (
                store._client.from_("app_settings")
                .select("telegram_bot_token, telegram_chat_id, enable_telegram_push")
                .eq("user_id", "default")
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if rows:
                row = rows[0]
                if row.get("enable_telegram_push") is False:
                    return None, []   # explicitly disabled
                if row.get("telegram_bot_token"):
                    token = str(row["telegram_bot_token"]).strip()
                if row.get("telegram_chat_id"):
                    cid_raw = str(row["telegram_chat_id"]).strip()
                    chat_ids = [int(x.strip()) for x in cid_raw.split(",") if x.strip().lstrip("-").isdigit()]
        except Exception:
            pass  # column may not exist yet (migration 009)

    # Fallback to env
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None
    if not chat_ids:
        cid_env = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if cid_env:
            chat_ids = [int(x.strip()) for x in cid_env.split(",") if x.strip().lstrip("-").isdigit()]

    return token, chat_ids


def _signal_hash(bundle: dict) -> str:
    """Hash to dedupe pushes. Same direction + strength + price band = same."""
    d = bundle.get("debate") or {}
    rcs = bundle.get("rcs") or {}
    price = bundle.get("xau_price") or 0
    band = round(price / 5) * 5  # 5-USD buckets
    key = f"{d.get('final_action','?')}|{d.get('signal_strength','?')}|{int((d.get('confidence') or 0)*10)}|{rcs.get('direction','?')}|{int(rcs.get('confidence_pct') or 0) // 10}|{band}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _emoji_action(action: str) -> str:
    return {"LONG": "🟢", "SHORT": "🔴", "FLAT": "⚪", "WAIT": "⚪"}.get(action, "⚪")


def _format_alert(bundle: dict) -> str:
    """Compact HTML alert message. ≤4096 chars (Telegram limit)."""
    d = bundle.get("debate") or {}
    rcs = bundle.get("rcs")
    action = d.get("final_action", "FLAT")
    strength = d.get("signal_strength", "FLAT")
    conf = float(d.get("confidence") or 0)
    price = bundle.get("xau_price", 0)
    regime = bundle.get("regime", "?")

    # Find a directional signal with concrete levels.
    # Priority 1: per-style matching debate.action (if debate is directional)
    # Priority 2: ANY per-style with side != FLAT (debate FLAT but style hot)
    sig_for_levels = None
    sig_style_label = None
    if action in ("LONG", "SHORT"):
        for key in ("intraday", "scalper", "swing"):
            s = bundle.get(key) or {}
            if s.get("side") == action and s.get("entry"):
                sig_for_levels = s
                sig_style_label = key
                break
    if sig_for_levels is None:
        # Fallback: any non-FLAT per-style (debate may be FLAT but style strong)
        for key in ("intraday", "scalper", "swing"):
            s = bundle.get(key) or {}
            if s.get("side") in ("LONG", "SHORT") and s.get("entry"):
                sig_for_levels = s
                sig_style_label = key
                break

    # Header: prefer per-style direction if debate is FLAT (more actionable)
    header_action = action if action in ("LONG", "SHORT") else (
        sig_for_levels.get("side") if sig_for_levels else action
    )
    header_conf = conf if action in ("LONG", "SHORT") else (
        float(sig_for_levels.get("confidence") or 0) if sig_for_levels else 0
    )

    parts = [
        f"<b>🪙 yeehee signal alert</b>",
        f"{_emoji_action(header_action)} <b>XAU {header_action}</b> · {strength} · conf {header_conf:.0%}"
        + (f" ({sig_style_label})" if sig_style_label and action == 'FLAT' else ""),
        f"💰 ${price:.2f}  ·  Regime: <b>{regime}</b>",
    ]

    if sig_for_levels:
        parts.append("")
        parts.append("<b>Levels:</b>")
        parts.append(f"  Entry: <code>${sig_for_levels.get('entry', 0):.2f}</code>")
        parts.append(f"  SL:    <code>${sig_for_levels.get('sl', 0):.2f}</code>")
        parts.append(f"  TP1:   <code>${sig_for_levels.get('tp1', 0):.2f}</code> (R {sig_for_levels.get('rr_to_tp1', 0):.1f})")
        parts.append(f"  TP2:   <code>${sig_for_levels.get('tp2', 0):.2f}</code> (R {sig_for_levels.get('rr_to_tp2', 0):.1f})")

    parts.append("")
    parts.append(f"<b>Driver:</b> {d.get('primary_driver', 'mixed')}")

    # RCS reference
    if rcs:
        parts.append("")
        rcs_dir = rcs.get("direction", "WAIT")
        rcs_score = float(rcs.get("rcs_score") or 0)
        parts.append(f"<b>RCS Composite:</b> {_emoji_action(rcs_dir)} {rcs_dir} ({rcs_score:+.2f}, conf {rcs.get('confidence_pct', 0)}%)")
        for drv in (rcs.get("top_drivers") or [])[:2]:
            parts.append(f"  · {drv[:80]}")

    parts.append("")
    parts.append("<i>⚠ Indikator only. Lot size & risk → Kalkulator.</i>")
    parts.append("<i>📊 yeehee.vercel.app/signals</i>")

    return "\n".join(parts)


def _send_message(token: str, chat_id: int, text: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


def maybe_push_signal(store, bundle: dict, log=print) -> dict:
    """Decide + push alert if conditions met.

    Returns dict {pushed: bool, reason: str, recipients: int}.
    Caller should not block on this — fire-and-log.

    Eligibility (any one):
      A) Debate STRONG with conf ≥ DEFAULT_MIN_CONFIDENCE_DEBATE (0.65)
      B) RCS direction with conf_pct ≥ DEFAULT_MIN_CONFIDENCE_RCS (70)
      C) ANY per-style signal (scalper/intraday/swing) with side != FLAT
         AND confidence ≥ ea_min_confidence_pct (default 0.55) — same gate
         that promotes signal to EA. If EA executes, user wants notif.
    """
    out = {"pushed": False, "reason": "", "recipients": 0}

    debate = bundle.get("debate") or {}
    rcs    = bundle.get("rcs") or {}
    action = debate.get("final_action") or "FLAT"
    strength = debate.get("signal_strength") or "FLAT"
    conf = float(debate.get("confidence") or 0)
    rcs_conf_pct = int(rcs.get("confidence_pct") or 0)
    rcs_dir = rcs.get("direction") or "WAIT"

    eligible_debate = strength in ("STRONG", "NEWS_STRONG") and conf >= DEFAULT_MIN_CONFIDENCE_DEBATE
    eligible_rcs    = rcs_dir in ("LONG", "SHORT") and rcs_conf_pct >= DEFAULT_MIN_CONFIDENCE_RCS

    # Per-style gate — same threshold as EA promote so notif tracks executions
    eligible_style = False
    style_signal_for_alert = None
    try:
        ea_min_conf = float(
            (store.app_settings() if store else {}).get("ea_min_confidence_pct") or 55
        ) / 100.0
    except Exception:
        ea_min_conf = 0.55
    for key in ("scalper", "intraday", "swing"):
        s = bundle.get(key) or {}
        side = s.get("side", "FLAT")
        conf_s = float(s.get("confidence") or 0)
        if side in ("LONG", "SHORT") and conf_s >= ea_min_conf:
            eligible_style = True
            style_signal_for_alert = (key, s, conf_s)
            break  # first qualifying style wins

    if not (eligible_debate or eligible_rcs or eligible_style):
        out["reason"] = (
            f"not eligible: debate={strength}/{conf:.2f}, "
            f"rcs={rcs_dir}/{rcs_conf_pct}, no per-style ≥ {ea_min_conf*100:.0f}%"
        )
        return out

    # Resolve credentials
    token, chat_ids = _resolve_credentials(store)
    if not token or not chat_ids:
        out["reason"] = "telegram not configured (no token/chat_id)"
        return out

    # Dedupe via state file
    state = _load_state()
    h = _signal_hash(bundle)
    if h == state.get("last_hash"):
        # Check time-based debounce
        last_at = state.get("last_push_at")
        try:
            if last_at:
                from datetime import datetime as dt
                age_min = (datetime.now(timezone.utc) - dt.fromisoformat(last_at).replace(tzinfo=timezone.utc)).total_seconds() / 60.0
                if age_min < PUSH_DEBOUNCE_MIN:
                    out["reason"] = f"duplicate (last push {age_min:.0f}min ago)"
                    return out
        except Exception:
            pass

    # Build message + send
    msg = _format_alert(bundle)
    sent = 0
    for cid in chat_ids:
        if _send_message(token, cid, msg):
            sent += 1

    # Update state
    state["last_hash"] = h
    state["last_push_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    out["pushed"] = sent > 0
    out["recipients"] = sent
    out["reason"] = f"sent to {sent}/{len(chat_ids)}"
    return out
