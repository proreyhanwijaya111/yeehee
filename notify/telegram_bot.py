"""Telegram bot — push alert STRONG signal + interactive commands.

Setup (one-time, ~5 menit):
  1. Open Telegram, chat ke @BotFather
  2. /newbot → kasih nama (e.g. yeehee_signal_bot)
  3. Copy token → .env: TELEGRAM_BOT_TOKEN=...
  4. Send /start ke bot lo. Then chat @userinfobot → copy your chat ID → .env: TELEGRAM_CHAT_ID=...
     (Multiple users: comma-separated, e.g. 12345678,87654321)
  5. python notify/telegram_bot.py

Interactive commands:
  /signal           — semua signal (scalper, intraday, swing)
  /signal scalper   — specific style
  /risk <eq> <side> <entry> <sl> <tp1>  — quick lot calc
  /news             — high-impact events 48h
  /regime           — current regime + session
  /debate           — full 4-agent debate
  /strong on|off    — toggle auto-push STRONG signals
  /help             — list commands

Auto-push: every 10 min, check signals. Push kalo STRONG/NEWS_STRONG dan beda dari yg sebelumnya.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

# Path setup
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HAS_TELEGRAM, DATA_CACHE,
)

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("yeehee.bot")

STATE_FILE = DATA_CACHE / "bot_state.json"
PUSH_INTERVAL_SEC = 600  # 10 min

ALLOWED_CHAT_IDS: Set[int] = {int(x.strip()) for x in TELEGRAM_CHAT_ID.split(",") if x.strip()}


# ============== SYNC HELPER (used by other modules) ==============
def send_message_sync(text: str, chat_id: int | None = None, parse_mode: str = "HTML") -> bool:
    """Plain HTTP send. Doesn't need async — useful kalau dipanggil dari script lain."""
    if not HAS_TELEGRAM:
        log.warning("Telegram not configured — skip send")
        return False
    target = chat_id or (next(iter(ALLOWED_CHAT_IDS)) if ALLOWED_CHAT_IDS else None)
    if not target:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": target,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }, timeout=10)
        return r.ok
    except Exception as e:
        log.error(f"send failed: {e}")
        return False


def broadcast(text: str, parse_mode: str = "HTML") -> int:
    """Send to all allowed chat IDs."""
    n = 0
    for cid in ALLOWED_CHAT_IDS:
        if send_message_sync(text, cid, parse_mode):
            n += 1
    return n


# ============== STATE ==============
def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_signal_hash": "", "strong_alerts_enabled": True, "last_news_hash": ""}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.error(f"save state failed: {e}")


# ============== FORMATTING ==============
def _emoji_for_action(action: str) -> str:
    return {"LONG": "🟢", "SHORT": "🔴", "FLAT": "⚪"}.get(action, "⚪")


def _emoji_for_strength(s: str) -> str:
    return {"STRONG": "🔥", "NEWS_STRONG": "📰🔥", "NORMAL": "✅", "WEAK": "💭", "FLAT": "⏸"}.get(s, "")


def fmt_signal(label: str, sig: dict) -> str:
    side = sig.get("side", "FLAT")
    if side == "FLAT":
        reasons = sig.get("reasons", [])
        return f"{_emoji_for_action(side)} <b>{label}</b>: FLAT — {reasons[0] if reasons else 'no edge'}"
    rr1 = sig.get("rr_to_tp1", 0)
    rr2 = sig.get("rr_to_tp2", 0)
    lines = [
        f"{_emoji_for_action(side)} <b>{label}: {side}</b> · conf {sig['confidence']:.0%} · {sig['confluence_count']} factors",
        f"   Entry: <code>${sig['entry']:.2f}</code>",
        f"   SL:    <code>${sig['sl']:.2f}</code>  ({abs(sig['entry']-sig['sl']):+.2f})",
        f"   TP1:   <code>${sig['tp1']:.2f}</code>  R={rr1:.2f}",
        f"   TP2:   <code>${sig['tp2']:.2f}</code>  R={rr2:.2f}",
        f"   TP3:   <code>${sig['tp3']:.2f}</code>",
    ]
    return "\n".join(lines)


def fmt_bundle(bundle: dict) -> str:
    """Full bundle (used for /signal command)."""
    parts = [
        f"💰 <b>XAU/USD</b> @ ${bundle['xau_price']:.2f}",
        f"🌐 Regime: <b>{bundle['regime']}</b>  ·  Session: <b>{bundle['session']}</b>",
        f"📊 Macro: {bundle['intermarket'].get('score', 0):+.2f}  ·  COT z: {bundle['cot'].get('z', 0):+.2f}" if bundle['cot'].get('z') is not None else f"📊 Macro: {bundle['intermarket'].get('score', 0):+.2f}",
    ]
    if bundle.get("in_news_blackout"):
        ev = bundle["blackout_event"]
        parts.append(f"🚨 <b>NEWS BLACKOUT</b>: {ev['title']} ({ev['currency']})")
    elif bundle.get("upcoming_events"):
        ev = bundle["upcoming_events"][0]
        parts.append(f"⚠️ Upcoming: {ev['title']} ({ev['currency']}) at {ev['when_utc'][:16]}Z")

    parts.append("")
    parts.append("━━━ <b>4-Agent Debate</b> ━━━")
    d = bundle["debate"]
    parts.append(f"{_emoji_for_strength(d['signal_strength'])} <b>{d['final_action']}</b> · {d['signal_strength']} · conf {d['confidence']:.0%}")
    parts.append(f"<i>Driver: {d.get('primary_driver', 'mixed')}</i>")
    for ag in d["agents"]:
        v = ag["verdict"]
        parts.append(f"  {_emoji_for_action(v)} {ag['name']}: <b>{v}</b> ({ag['confidence']:.0%})")

    parts.append("")
    parts.append("━━━ <b>Signals by Style</b> ━━━")
    parts.append(fmt_signal("⚡ Scalper (M5)", bundle["scalper"]))
    parts.append("")
    parts.append(fmt_signal("🎯 Intraday (M15)", bundle["intraday"]))
    parts.append("")
    parts.append(fmt_signal("🌊 Swing (H4)", bundle["swing"]))

    return "\n".join(parts)


def fmt_strong_alert(bundle: dict) -> str:
    """Compact alert untuk auto-push. Cuma info penting."""
    d = bundle["debate"]
    sig_for_action = None
    for s in (bundle["intraday"], bundle["scalper"], bundle["swing"]):
        if s["side"] == d["final_action"]:
            sig_for_action = s
            break

    head = f"🔥 <b>STRONG SIGNAL</b> 🔥\n"
    head += f"{_emoji_for_action(d['final_action'])} <b>XAU {d['final_action']}</b> · conf {d['confidence']:.0%}\n"
    head += f"💰 Price: ${bundle['xau_price']:.2f}  ·  Regime: {bundle['regime']}\n\n"

    if sig_for_action and sig_for_action["side"] != "FLAT":
        head += f"<b>Levels (from {sig_for_action.get('style','intraday')}):</b>\n"
        head += f"  Entry: <code>${sig_for_action['entry']:.2f}</code>\n"
        head += f"  SL:    <code>${sig_for_action['sl']:.2f}</code>\n"
        head += f"  TP1:   <code>${sig_for_action['tp1']:.2f}</code> (R {sig_for_action.get('rr_to_tp1',0):.1f})\n"
        head += f"  TP2:   <code>${sig_for_action['tp2']:.2f}</code> (R {sig_for_action.get('rr_to_tp2',0):.1f})\n\n"

    head += "<b>Why:</b>\n"
    for line in d.get("reasoning_chain", [])[:4]:
        head += f"• {line}\n"
    return head


def signal_hash(bundle: dict) -> str:
    """Hash final action + confidence + price band — used to dedupe push."""
    d = bundle["debate"]
    price_band = round(bundle["xau_price"] / 5) * 5  # 5-dollar buckets
    key = f"{d['final_action']}|{d['signal_strength']}|{int(d['confidence']*10)}|{price_band}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ============== CHECK + PUSH (called from scheduler) ==============
def check_and_push() -> dict:
    """Run signal engine, push if STRONG and not duplicate."""
    from signal_engine import generate_signals

    state = _load_state()
    if not state.get("strong_alerts_enabled", True):
        return {"pushed": False, "reason": "alerts disabled"}

    try:
        bundle = generate_signals(use_pm_narrative=False)
    except Exception as e:
        log.error(f"generate_signals failed: {e}")
        return {"pushed": False, "reason": f"engine error: {e}"}

    bundle_d = bundle.to_dict()
    d = bundle_d["debate"]
    strength = d["signal_strength"]

    if strength not in ("STRONG", "NEWS_STRONG"):
        return {"pushed": False, "reason": f"strength={strength} not strong enough"}

    h = signal_hash(bundle_d)
    if h == state.get("last_signal_hash", ""):
        return {"pushed": False, "reason": "duplicate of last push"}

    msg = fmt_strong_alert(bundle_d)
    n = broadcast(msg)

    state["last_signal_hash"] = h
    state["last_push_time"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    log.info(f"pushed STRONG signal to {n} chat(s)")
    return {"pushed": True, "recipients": n, "hash": h}


# ============== INTERACTIVE BOT ==============
def _build_application():
    """Build telegram Application with handlers + scheduled job. Returns Application."""
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    from telegram.constants import ParseMode

    def auth(update: Update) -> bool:
        cid = update.effective_chat.id if update.effective_chat else 0
        return cid in ALLOWED_CHAT_IDS

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            await update.message.reply_text(f"Unauthorized. Your chat_id: {update.effective_chat.id}")
            return
        await update.message.reply_text(
            "yeehee bot ready 🪙\n\n"
            "Commands:\n"
            "/signal — all 3 styles + debate\n"
            "/signal scalper|intraday|swing — specific\n"
            "/risk <equity> <side> <entry> <sl> <tp1> — lot calc\n"
            "/news — high-impact 48h\n"
            "/regime — current regime\n"
            "/debate — full 4-agent debate\n"
            "/strong on|off — toggle auto-push\n"
            "/help"
        )

    async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await cmd_start(update, ctx)

    async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        from signal_engine import generate_signals
        await update.message.reply_text("⏳ Computing...")
        try:
            bundle = generate_signals(use_pm_narrative=False).to_dict()
        except Exception as e:
            await update.message.reply_text(f"❌ Engine error: {e}")
            return

        if ctx.args:
            style = ctx.args[0].lower()
            if style in ("scalper", "intraday", "swing"):
                msg = fmt_signal(style.upper(), bundle[style])
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                return
        msg = fmt_bundle(bundle)
        # Telegram limit 4096 chars — truncate if needed
        for chunk in [msg[i:i+3800] for i in range(0, len(msg), 3800)]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        if len(ctx.args) < 5:
            await update.message.reply_text(
                "Usage: /risk <equity> <LONG|SHORT> <entry> <sl> <tp1>\n"
                "Example: /risk 5000 LONG 2030 2025 2040"
            )
            return
        try:
            equity = float(ctx.args[0])
            side = ctx.args[1].upper()
            entry = float(ctx.args[2])
            sl = float(ctx.args[3])
            tp1 = float(ctx.args[4])
            tp2 = entry + (tp1 - entry) * 2 if side == "LONG" else entry - (entry - tp1) * 2
            tp3 = entry + (tp1 - entry) * 3 if side == "LONG" else entry - (entry - tp1) * 3
        except ValueError as e:
            await update.message.reply_text(f"Parse error: {e}")
            return

        from risk.sizing import compute_position
        rows = []
        for prof in ("konservatif", "moderat", "agresif", "bebas"):
            plan = compute_position(equity, entry, sl, tp1, tp2, tp3, side, prof)
            rows.append(
                f"<b>{prof.upper()}</b>: lot {plan.lot_size:.2f} · risk ${plan.risk_amount_usd:.0f} · lev {plan.leverage_used:.1f}x · TP1 win ${plan.expected_payoff_usd['tp1']:.0f}"
            )
        await update.message.reply_text("\n".join(rows), parse_mode=ParseMode.HTML)

    async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        from data.calendar_fetcher import upcoming_high_impact
        events = upcoming_high_impact(48)
        if not events:
            await update.message.reply_text("No high-impact events in next 48h.")
            return
        lines = ["<b>High-impact (48h)</b>"]
        for e in events[:15]:
            lines.append(f"  {e.when_utc[:16]}Z [{e.currency}] {e.title}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_regime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        from data.price_fetcher import fetch_xau
        from features.technical import add_all
        from features.regime import current_regime
        from features.session import session_at
        try:
            df = add_all(fetch_xau("4h"))
            r = current_regime(df)
            sess = session_at(datetime.now(timezone.utc))
            adx_str = f"{r['adx']:.1f}" if r.get('adx') is not None else "n/a"
            atr_str = f"{r['atr_pct_rank']:.0%}" if r.get('atr_pct_rank') is not None else "n/a"
            msg = (
                f"<b>Regime (H4):</b> {r['regime']}\n"
                f"<b>ADX:</b> {adx_str}\n"
                f"<b>ATR pct rank:</b> {atr_str}\n"
                f"<b>Session:</b> {sess}"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def cmd_debate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        from signal_engine import generate_signals
        await update.message.reply_text("⏳ Running debate...")
        try:
            bundle = generate_signals(use_pm_narrative=False).to_dict()
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return
        d = bundle["debate"]
        lines = [
            f"<b>{_emoji_for_strength(d['signal_strength'])} {d['final_action']} · {d['signal_strength']}</b>",
            f"Confidence: {d['confidence']:.0%}",
            f"Driver: {d.get('primary_driver','mixed')}",
            "",
            "<b>Agents:</b>",
        ]
        for ag in d["agents"]:
            lines.append(f"  {_emoji_for_action(ag['verdict'])} <b>{ag['name']}</b>: {ag['verdict']} ({ag['confidence']:.0%})")
            for r in ag.get("reasoning", [])[:3]:
                lines.append(f"     · {r}")
        if d.get("risks"):
            lines.append("\n<b>⚠️ Risks:</b>")
            for r in d["risks"]:
                lines.append(f"  · {r}")
        msg = "\n".join(lines)
        for chunk in [msg[i:i+3800] for i in range(0, len(msg), 3800)]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    async def cmd_strong(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not auth(update):
            return
        state = _load_state()
        if ctx.args and ctx.args[0].lower() in ("on", "off"):
            state["strong_alerts_enabled"] = (ctx.args[0].lower() == "on")
            _save_state(state)
        status = "ON ✅" if state.get("strong_alerts_enabled", True) else "OFF ❌"
        await update.message.reply_text(f"Auto-push STRONG signals: {status}")

    async def scheduled_check(ctx: ContextTypes.DEFAULT_TYPE):
        log.info("scheduled signal check")
        try:
            result = check_and_push()
            log.info(f"check result: {result}")
        except Exception as e:
            log.error(f"scheduled check failed: {e}")

    if not HAS_TELEGRAM:
        log.error("TELEGRAM_BOT_TOKEN/CHAT_ID not set in .env")
        return None

    async def post_init(application):
        for cid in ALLOWED_CHAT_IDS:
            try:
                await application.bot.send_message(
                    cid, "🪙 <b>yeehee bot online</b>\nUse /help untuk commands.",
                    parse_mode="HTML",
                )
            except Exception as e:
                log.error(f"welcome broadcast to {cid} failed: {e}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("regime", cmd_regime))
    app.add_handler(CommandHandler("debate", cmd_debate))
    app.add_handler(CommandHandler("strong", cmd_strong))

    if app.job_queue is not None:
        app.job_queue.run_repeating(scheduled_check, interval=PUSH_INTERVAL_SEC, first=30)
        log.info(f"scheduled signal check every {PUSH_INTERVAL_SEC}s")
    else:
        log.warning("JobQueue not available — install: pip install \"python-telegram-bot[job-queue]\"")

    return app


def run() -> None:
    """Entry point — synchronous, run_polling is blocking."""
    if not HAS_TELEGRAM:
        print("[bot] Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.")
        print("Setup: chat @BotFather → /newbot → copy token. Then chat @userinfobot → copy your ID.")
        return

    try:
        app = _build_application()
        if app is None:
            return
        log.info(f"bot starting for chat_ids: {ALLOWED_CHAT_IDS}")
        app.run_polling()  # blocking
    except KeyboardInterrupt:
        print("\n[bot] stopped")
    except Exception as e:
        log.error(f"bot error: {e}", exc_info=True)


if __name__ == "__main__":
    run()
