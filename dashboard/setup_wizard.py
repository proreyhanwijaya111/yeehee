"""Telegram setup wizard — render-only helpers (UI logic inline di app.py)."""
from __future__ import annotations
import requests


def test_bot_token(token: str) -> dict:
    """Try getMe; returns {ok, username, error}."""
    if not token or len(token) < 30:
        return {"ok": False, "error": "Token format salah (terlalu pendek)"}
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        if r.status_code == 401:
            return {"ok": False, "error": "Token salah / dicabut. Bikin baru di @BotFather."}
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        data = r.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", "unknown")}
        info = data["result"]
        return {
            "ok": True,
            "username": info.get("username", "?"),
            "id": info.get("id"),
            "name": info.get("first_name", "?"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_chat_id(token: str, chat_id: str) -> dict:
    """Send a test message; returns {ok, error}."""
    try:
        cid = int(chat_id)
    except Exception:
        return {"ok": False, "error": f"Chat ID harus angka (bukan: {chat_id!r})"}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": "✅ yeehee test — koneksi OK!", "parse_mode": "HTML"},
            timeout=8,
        )
        data = r.json()
        if data.get("ok"):
            return {"ok": True, "msg": "Test message terkirim. Cek Telegram lo."}
        desc = data.get("description", "unknown")
        if "chat not found" in desc.lower():
            return {"ok": False, "error": "Chat ID salah, atau lo belum kirim /start ke bot lo."}
        return {"ok": False, "error": desc}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_env_file(env_path, token: str, chat_id: str) -> bool:
    """Patch .env with provided values."""
    try:
        from pathlib import Path
        p = Path(env_path)
        existing = p.read_text(encoding="utf-8") if p.exists() else ""
        lines = existing.splitlines()
        out_lines = []
        seen_token = seen_chat = False
        for line in lines:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                out_lines.append(f"TELEGRAM_BOT_TOKEN={token}")
                seen_token = True
            elif line.startswith("TELEGRAM_CHAT_ID="):
                out_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
                seen_chat = True
            else:
                out_lines.append(line)
        if not seen_token:
            out_lines.append(f"TELEGRAM_BOT_TOKEN={token}")
        if not seen_chat:
            out_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
        p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return True
    except Exception as e:
        print(f"env update failed: {e}")
        return False
