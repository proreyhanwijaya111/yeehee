"""Telegram interactive bot — bidirectional command handler.

Distinct from notify/push.py (one-way alerts only). This module runs as a
daemon thread that polls Telegram getUpdates() and dispatches commands from
the authorized chat_id:

    /start        — welcome + list commands
    /signal       — show latest 12-agent signal (action, conf, levels)
    /portfolio    — current open trades + total %
    /rcs          — latest RCS composite score (M5/M15/H1)
    /pause        — set ea_enable_execution=false in app_settings
    /resume       — set ea_enable_execution=true in app_settings
    /chat <q>     — free-form question to LLM, grounded with current context
    /help         — same as /start

Security: only messages from telegram_chat_id (configured in app_settings or
env) are honored. Anyone else gets a polite refusal.

Config priority:
    1. app_settings.telegram_bot_token + telegram_chat_id (UI form)
    2. env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID

Setup (one-time, ~5 menit):
    1. Open Telegram, chat @BotFather
    2. /newbot → kasih nama (e.g. yeehee_signal_bot)
    3. Copy token → /more/settings/telegram di HP, paste
    4. Send /start ke bot lo. Then chat @userinfobot → copy your chat ID, paste juga
    5. Tunggu daemon next refresh (60s) → bot listener nyala
"""
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

import requests


TELEGRAM_API = "https://api.telegram.org"
POLL_INTERVAL_S = 3
LONG_POLL_TIMEOUT_S = 25     # Telegram long polling window (saves quota)


def _resolve_credentials(store) -> tuple[Optional[str], Optional[str], bool]:
    """Returns (token, chat_id, enabled). Same source priority as notify/push.py."""
    token   = None
    chat_id = None
    enabled = True

    # Supabase first (UI form)
    try:
        s = store.app_settings() if store else {}
        token   = s.get("telegram_bot_token") or None
        chat_id = s.get("telegram_chat_id") or None
        if "enable_telegram_push" in s:
            enabled = bool(s.get("enable_telegram_push", True))
    except Exception:
        pass

    # Env fallback
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    return (token, str(chat_id) if chat_id else None, enabled)


def _send(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Best-effort message send. Truncates >4000 chars (Telegram cap 4096)."""
    if not token or not chat_id:
        return False
    if len(text) > 4000:
        text = text[:3990] + "\n\n…(truncated)"
    try:
        r = requests.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _read_latest_bundle(store) -> Optional[dict]:
    """Pull most recent signal_bundles row."""
    if not store or not getattr(store, "_client", None):
        return None
    try:
        r = (
            store._client.from_("signal_bundles")
            .select("*")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _read_open_trades(store) -> list[dict]:
    if not store or not getattr(store, "_client", None):
        return []
    try:
        r = (
            store._client.from_("active_trades")
            .select("style,side,entry,sl,tp1,tp2,opened_at,confidence,risk_pct,high_after_open,low_after_open,hit_tp1,hit_tp2")
            .eq("user_id", "default")
            .eq("status", "OPEN")
            .execute()
        )
        return r.data or []
    except Exception:
        return []


def _read_latest_rcs(store) -> list[dict]:
    """Latest RCS row per timeframe (M5/M15/H1)."""
    if not store or not getattr(store, "_client", None):
        return []
    out = []
    for tf in ("M5", "M15", "H1"):
        try:
            r = (
                store._client.from_("rcs_signals")
                .select("timeframe,direction,rcs_score,confidence_pct,generated_at")
                .eq("timeframe", tf)
                .order("generated_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if rows:
                out.append(rows[0])
        except Exception:
            continue
    return out


# ─── Command handlers ────────────────────────────────────────────────────────

def _cmd_start() -> str:
    return (
        "<b>yeehee bot</b> — interaktif via Telegram.\n\n"
        "Perintah tersedia:\n"
        "/signal — sinyal terbaru (action + conf + levels)\n"
        "/portfolio — open trades + status\n"
        "/rcs — RCS composite per timeframe\n"
        "/pause — pause auto-execute (EA)\n"
        "/resume — resume auto-execute\n"
        "/chat &lt;pertanyaan&gt; — tanya ke LLM agent\n"
        "/help — tampilkan menu ini\n\n"
        "Pesan tanpa / dianggap free-form chat ke LLM."
    )


def _cmd_signal(store) -> str:
    b = _read_latest_bundle(store)
    if not b:
        return "Belum ada signal. Daemon mungkin baru start."
    debate = b.get("debate") or {}
    action = debate.get("final_action", "?")
    conf   = float(debate.get("confidence", 0)) * 100
    spot   = b.get("xau_price", "?")
    sess   = b.get("session", "?")
    rcs    = b.get("rcs") or {}
    rcs_dir = rcs.get("direction", "—") if rcs else "—"
    rcs_score = rcs.get("rcs_score") if rcs else None
    ts = (b.get("timestamp") or "")[:16].replace("T", " ")

    scalper  = b.get("scalper")  or {}
    intraday = b.get("intraday") or {}
    swing    = b.get("swing")    or {}

    def _row(name: str, sig: dict) -> str:
        side = sig.get("side", "FLAT")
        c    = float(sig.get("confidence", 0)) * 100
        if side == "FLAT":
            return f"  • <b>{name}</b>: TUNGGU"
        ent = sig.get("entry"); sl = sig.get("sl"); tp1 = sig.get("tp1")
        return f"  • <b>{name}</b>: {side} {c:.0f}% — entry {ent} sl {sl} tp1 {tp1}"

    rcs_line = ""
    if rcs_score is not None:
        rcs_line = f"\n<b>RCS</b>: {rcs_dir} {float(rcs_score):+.2f}"

    return (
        f"<b>Sinyal {ts}Z</b>\n"
        f"XAU spot: ${spot}  ·  sesi: {sess}\n"
        f"<b>12-agent</b>: {action} {conf:.0f}%"
        f"{rcs_line}\n\n"
        f"<b>Per gaya:</b>\n"
        f"{_row('Scalper M5', scalper)}\n"
        f"{_row('Intraday M15', intraday)}\n"
        f"{_row('Swing H1', swing)}"
    )


def _cmd_portfolio(store) -> str:
    open_trades = _read_open_trades(store)
    if not open_trades:
        return "Tidak ada open trade saat ini."
    lines = [f"<b>Open trades</b> ({len(open_trades)}):"]
    for t in open_trades:
        side  = t.get("side", "?")
        style = t.get("style", "?")
        ent   = t.get("entry"); sl = t.get("sl"); tp1 = t.get("tp1")
        opened = (t.get("opened_at") or "")[:16].replace("T", " ")
        flags = []
        if t.get("hit_tp1"): flags.append("TP1✓")
        if t.get("hit_tp2"): flags.append("TP2✓")
        flag_str = " " + " ".join(flags) if flags else ""
        lines.append(
            f"• <b>{style.upper()} {side}</b> @ {ent} → SL {sl} / TP1 {tp1}{flag_str}\n"
            f"  opened {opened}Z"
        )
    return "\n".join(lines)


def _cmd_rcs(store) -> str:
    rows = _read_latest_rcs(store)
    if not rows:
        return "Belum ada RCS data."
    lines = ["<b>RCS Composite</b>:"]
    for r in rows:
        tf = r.get("timeframe", "?")
        direction = r.get("direction", "—")
        score = r.get("rcs_score", 0)
        conf  = r.get("confidence_pct", 0)
        lines.append(f"  • {tf}: {direction} score={float(score):+.3f} conf={conf}%")
    return "\n".join(lines)


def _cmd_pause(store) -> str:
    try:
        store._client.from_("app_settings").update({
            "ea_enable_execution": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", "default").execute()
        return "🛑 EA execution PAUSED. Lo bisa /resume kapan aja."
    except Exception as e:
        return f"❌ Gagal pause: {str(e)[:120]}"


def _cmd_resume(store) -> str:
    try:
        store._client.from_("app_settings").update({
            "ea_enable_execution": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", "default").execute()
        return "▶️ EA execution RESUMED. Order auto-execute lagi."
    except Exception as e:
        return f"❌ Gagal resume: {str(e)[:120]}"


def _cmd_chat(store, question: str) -> str:
    """Free-form Q&A via LLM. Uses default provider + model from settings."""
    if not question.strip():
        return "Format: /chat &lt;pertanyaan lo&gt;"
    try:
        from ai_agent.llm_router import LLMRouter
        s = store.app_settings()
        provider_keys = store.provider_keys()
        if not provider_keys:
            return "❌ Belum ada API key LLM. Setup di /more/settings/llm dulu."
        router = LLMRouter()
        for prov, cred in provider_keys.items():
            router.set_credential(prov, api_key=cred.get("api_key"), base_url=cred.get("base_url"))
        prov  = s.get("default_llm_provider") or "openrouter"
        model = s.get("default_llm_model") or "openai/gpt-oss-20b:free"

        bundle = _read_latest_bundle(store) or {}
        rcs = bundle.get("rcs") or {}
        ctx_lines = [
            f"User asked: {question.strip()}",
            "",
            "Current market context:",
            f"  XAU spot: {bundle.get('xau_price', '?')}",
            f"  Session: {bundle.get('session', '?')}",
            f"  Regime: {bundle.get('regime', '?')}",
        ]
        if rcs:
            ctx_lines.append(f"  RCS: {rcs.get('direction', '?')} score={rcs.get('rcs_score', '?')}")
        debate = bundle.get("debate") or {}
        if debate:
            ctx_lines.append(f"  12-agent debate: {debate.get('final_action', '?')} conf={float(debate.get('confidence', 0)):.2f}")

        sys_prompt = (
            "You are a XAU/USD trading analyst assistant. Reply in Bahasa Indonesia (informal). "
            "Be concise — max 200 words. If user asks for trade advice, ground in the provided "
            "market context. Never recommend specific entry/SL without checking context. "
            "If unsure, say so."
        )
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": "\n".join(ctx_lines)},
        ]
        resp = router.chat(provider=prov, model=model, messages=msgs, temperature=0.4, max_tokens=500)
        return resp.content[:3500] if resp and resp.content else "🤔 LLM gak balas. Coba lagi."
    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"


# ─── Main bot loop ───────────────────────────────────────────────────────────

class TelegramBot:
    """Long-poll Telegram bot. Dispatches commands to handlers."""

    def __init__(self, store, log=print):
        self.store = store
        self.log = log
        self.last_update_id = 0
        self.token: Optional[str] = None
        self.chat_id: Optional[str] = None

    def _refresh_creds(self) -> tuple[Optional[str], Optional[str], bool]:
        return _resolve_credentials(self.store)

    def poll_once(self) -> int:
        """One getUpdates pass. Returns # messages processed."""
        token, chat_id, enabled = self._refresh_creds()
        if not token or not chat_id or not enabled:
            return 0
        # Send a one-shot welcome ping if creds just appeared
        if token != self.token or chat_id != self.chat_id:
            if self.token is None:
                _send(token, chat_id, "🪙 <b>yeehee bot online</b>. Kirim /help buat liat command.")
            self.token = token
            self.chat_id = chat_id

        try:
            r = requests.get(
                f"{TELEGRAM_API}/bot{token}/getUpdates",
                params={
                    "offset":  self.last_update_id + 1,
                    "timeout": LONG_POLL_TIMEOUT_S,
                    "allowed_updates": '["message"]',
                },
                timeout=LONG_POLL_TIMEOUT_S + 5,
            )
            if r.status_code != 200:
                return 0
            data = r.json()
        except Exception as e:
            self.log(f"[telegram-bot] getUpdates error: {e!r}")
            return 0

        updates = data.get("result", [])
        n = 0
        for upd in updates:
            self.last_update_id = max(self.last_update_id, upd.get("update_id", 0))
            msg = upd.get("message") or {}
            chat_id_msg = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if chat_id_msg != chat_id:
                _send(token, chat_id_msg, "Bot ini private. Akses ditolak.")
                continue
            try:
                reply = self._dispatch(text)
                if reply:
                    _send(token, chat_id, reply)
                n += 1
            except Exception as e:
                self.log(f"[telegram-bot] handler error: {e!r}")
                traceback.print_exc()
                _send(token, chat_id, f"❌ Error: {str(e)[:200]}")
        return n

    def _dispatch(self, text: str) -> str:
        """Return reply string for a message."""
        cmd, _, rest = text.partition(" ")
        cmd_low = cmd.lower()

        if cmd_low in ("/start", "/help"):
            return _cmd_start()
        if cmd_low == "/signal":
            return _cmd_signal(self.store)
        if cmd_low == "/portfolio":
            return _cmd_portfolio(self.store)
        if cmd_low == "/rcs":
            return _cmd_rcs(self.store)
        if cmd_low == "/pause":
            return _cmd_pause(self.store)
        if cmd_low == "/resume":
            return _cmd_resume(self.store)
        if cmd_low == "/chat":
            return _cmd_chat(self.store, rest)

        if not text.startswith("/"):
            return _cmd_chat(self.store, text)

        return f"Perintah {cmd} tidak dikenali. /help untuk daftar."


def run_telegram_bot(store, log=print, shutdown_flag=None) -> None:
    """Long-running loop: poll Telegram every POLL_INTERVAL_S until shutdown."""
    bot = TelegramBot(store, log=log)
    log("[telegram-bot] starting interactive listener")
    while shutdown_flag is None or not shutdown_flag.is_set():
        try:
            bot.poll_once()
        except Exception as e:
            log(f"[telegram-bot] outer error: {e!r}")
            time.sleep(10)
        # Long polling already burned ~25s. Brief sleep before next poll.
        time.sleep(POLL_INTERVAL_S)
