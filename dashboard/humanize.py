"""Translate engine jargon → plain Bahasa Indonesia. Centralized biar konsisten."""
from __future__ import annotations
from typing import Optional


REGIME_ID = {
    "trending_up":  ("📈 Naik kuat",         "Pasar lagi tren naik. Strategi ikut arus (LONG) jalan, lawan arus (SHORT) bahaya."),
    "trending_dn":  ("📉 Turun kuat",         "Pasar lagi tren turun. Strategi SHORT jalan, LONG lawan arus."),
    "ranging":      ("↔️ Sideways (datar)",  "Pasar nggak ada arah jelas. Strategi trend-following bakal sering kena false signal."),
    "volatile":     ("⚡ Bergerak liar",      "Volatility tinggi tanpa arah jelas. Bahaya. Cocok scalper berpengalaman doang."),
    "quiet":        ("😴 Sepi (low vol)",     "Pasar diem-diem aja. Sulit dapat profit signifikan. Tunggu volatility kembali."),
}

SESSION_ID = {
    "asia":             ("🌏 Sesi Asia",        "Volatility rendah. Range-bound. Setup buat London open."),
    "london":           ("🇬🇧 Sesi London",     "Volatility tinggi. Trend day biasanya kebentuk di sini."),
    "ny":               ("🇺🇸 Sesi New York",   "Volatility tinggi. News US release di sini."),
    "lon_ny_overlap":   ("🌐 Overlap London-NY", "PEAK liquidity. Best buat momentum trading."),
    "off_hours":        ("🌙 Off hours",         "Liquidity rendah. Spread bisa lebar. Hindari entry baru."),
}

ACTION_ID = {
    "LONG":  ("🟢 BELI",   "#16a34a"),
    "SHORT": ("🔴 JUAL",   "#dc2626"),
    "FLAT":  ("⚪ TUNGGU", "#737373"),
}

STRENGTH_ID = {
    "STRONG":       ("🔥 KUAT",            "#16a34a", "Sinyal premium — semua faktor align. Eksekusi paling confident."),
    "NEWS_STRONG":  ("📰🔥 NEWS KUAT",     "#9333ea", "Sinyal post-news dengan arah jelas. High momentum."),
    "NORMAL":       ("✅ NORMAL",          "#0ea5e9", "Sinyal valid, confidence cukup. Eksekusi dengan disiplin."),
    "WEAK":         ("💭 LEMAH",           "#737373", "Confidence rendah. Pertimbangkan skip atau pakai size lebih kecil."),
    "FLAT":         ("⏸ TUNGGU",           "#475569", "Belum ada konsensus. Tunggu setup yang lebih jelas."),
}

STYLE_ID = {
    "scalper":  "⚡ Scalper (M5)",
    "intraday": "🎯 Intraday (M15)",
    "swing":    "🌊 Swing (H4)",
}

PROFILE_ID = {
    "konservatif":  ("🛡 Konservatif",   "Risk 0.5% per trade · max 2% loss harian"),
    "moderat":      ("⚖️ Moderat",       "Risk 1% per trade · max 4% loss harian (default)"),
    "agresif":      ("🔥 Agresif",       "Risk 2% per trade · max 6% loss harian"),
    "bebas":        ("⚠️ Bebas",         "Risk 5% per trade · max 20% loss harian (BAHAYA)"),
}

AGENT_ID = {
    "TechnicalAnalyst": "📊 Analis Teknikal",
    "MacroStrategist":  "🌍 Ahli Makro",
    "OrderFlowReader":  "🔍 Pembaca Order Flow",
    "DevilsAdvocate":   "😈 Pengkritik (Devil's Advocate)",
}


def humanize_regime(code: str) -> tuple[str, str]:
    return REGIME_ID.get(code, (code.upper(), ""))


def humanize_session(code: str) -> tuple[str, str]:
    return SESSION_ID.get(code, (code.upper(), ""))


def humanize_action(code: str) -> tuple[str, str]:
    return ACTION_ID.get(code, (code, "#737373"))


def humanize_strength(code: str) -> tuple[str, str, str]:
    return STRENGTH_ID.get(code, (code, "#737373", ""))


def humanize_style(code: str) -> str:
    return STYLE_ID.get(code, code)


def humanize_profile(code: str) -> tuple[str, str]:
    return PROFILE_ID.get(code, (code.title(), ""))


def humanize_agent(code: str) -> str:
    return AGENT_ID.get(code, code)


def explain_flat(sig: dict) -> str:
    """Plain Bahasa: kenapa signal FLAT?"""
    reasons = sig.get("reasons", [])
    if not reasons:
        return "Belum ada konfirmasi cukup. Engine masih monitor."
    first = reasons[0]
    if "confluence" in first.lower():
        # e.g. "intraday: confluence L=1/S=2 <4"
        try:
            stat = first.split(":")[1].strip()
            return f"Belum waktunya entry — faktor pendukung belum cukup ({stat}). Tunggu sampai 4+ faktor agree."
        except Exception:
            return first
    if "insufficient data" in first.lower():
        return "Data belum cukup. Tunggu beberapa candle lagi."
    if "news blackout" in first.lower():
        return "🚨 Lagi blackout news. Engine auto-skip 30 menit sebelum/sesudah event berdampak tinggi."
    return first


def explain_signal_short(sig: dict, max_reasons: int = 3) -> str:
    """Top reasons in plain language."""
    if sig.get("side") == "FLAT":
        return explain_flat(sig)
    reasons = sig.get("reasons", [])[:max_reasons]
    if not reasons:
        return "Lihat detail di tab Analisis AI"
    return " · ".join(reasons)


def macro_bias_label(score: float) -> tuple[str, str]:
    """+0.30 → 'Bullish ringan'. Returns (label, color)."""
    if score > 0.5:
        return ("Sangat bullish", "#16a34a")
    if score > 0.2:
        return ("Bullish", "#16a34a")
    if score > 0.05:
        return ("Sedikit bullish", "#22c55e")
    if score < -0.5:
        return ("Sangat bearish", "#dc2626")
    if score < -0.2:
        return ("Bearish", "#dc2626")
    if score < -0.05:
        return ("Sedikit bearish", "#ef4444")
    return ("Netral", "#737373")


def cot_label(z: float | None) -> tuple[str, str]:
    if z is None:
        return ("data nggak ada", "#737373")
    if z > 1.5:
        return (f"Long extreme (z={z:+.2f}) — bias mean-revert SHORT", "#dc2626")
    if z < -1.5:
        return (f"Short extreme (z={z:+.2f}) — bias mean-revert LONG", "#16a34a")
    if z > 0.8:
        return (f"Long crowded (z={z:+.2f})", "#f59e0b")
    if z < -0.8:
        return (f"Short crowded (z={z:+.2f})", "#f59e0b")
    return (f"Posisi normal (z={z:+.2f})", "#737373")
