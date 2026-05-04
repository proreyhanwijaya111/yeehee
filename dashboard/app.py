"""yeehee — Platform Signal XAU/USD (Emas vs Dollar)
Antarmuka Bahasa Indonesia · ramah pemula · production-ready
Jalankan: streamlit run dashboard/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# tambah dashboard/ ke path agar sibling imports bisa jalan
DASH_DIR = Path(__file__).resolve().parent
if str(DASH_DIR) not in sys.path:
    sys.path.insert(0, str(DASH_DIR))

import json
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config.settings import (
    RISK_PROFILES, HAS_AI_KEY, HAS_TELEGRAM,
    DEFAULT_RISK_PROFILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
)
from signal_engine import generate_signals
from data.price_fetcher import fetch_xau, fetch_intermarket_bundle
from data.calendar_fetcher import fetch_calendar, upcoming_high_impact
from features.technical import add_all
from features.smc import add_all_smc
from features.regime import detect_regime
from risk.sizing import compute_position, kelly_fractional
from backtest.engine import run_backtest, default_swing_signal
from backtest.monte_carlo import run_monte_carlo

from humanize import (
    humanize_regime, humanize_session, humanize_action, humanize_strength,
    humanize_style, humanize_profile, humanize_agent,
    explain_flat, explain_signal_short, macro_bias_label, cot_label,
)
from glossary import GLOSSARY, search as glossary_search
from setup_wizard import test_bot_token, test_chat_id, update_env_file

# ─────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="yeehee · Signal Emas",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
#  CSS GLOBAL
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* ===== HERO CARD ===== */
.hero-buy {
    background: linear-gradient(135deg, #15803d 0%, #16a34a 50%, #22c55e 100%);
    color: white; padding: 1.5rem 2rem; border-radius: 16px;
    box-shadow: 0 4px 24px rgba(22,163,74,0.35);
}
.hero-sell {
    background: linear-gradient(135deg, #b91c1c 0%, #dc2626 50%, #ef4444 100%);
    color: white; padding: 1.5rem 2rem; border-radius: 16px;
    box-shadow: 0 4px 24px rgba(220,38,38,0.35);
}
.hero-wait {
    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
    color: #94a3b8; padding: 1.5rem 2rem; border-radius: 16px;
    border: 2px dashed #475569;
}
.hero-action {
    font-size: 3.2rem; font-weight: 900; line-height: 1; letter-spacing: -1px;
    margin: 0;
}
.hero-sub {
    font-size: 1.05rem; margin: 0.4rem 0 0; opacity: 0.92;
}
.hero-price {
    font-size: 1.8rem; font-weight: 700; margin: 0; opacity: 0.95;
}

/* ===== SIGNAL CARD ===== */
.sig-card-buy  { background:#0f2d1f; border:2px solid #22c55e; border-radius:12px; padding:1.1rem; }
.sig-card-sell { background:#2d0f0f; border:2px solid #ef4444; border-radius:12px; padding:1.1rem; }
.sig-card-wait { background:#1a1f2e; border:2px dashed #475569; border-radius:12px; padding:1.1rem; }
.sig-label     { font-size:1.5rem; font-weight:800; margin:0; }

/* ===== BERITA ===== */
.news-blackout {
    background:#fee2e2; color:#991b1b; padding:0.8rem 1.2rem;
    border-radius:10px; border-left:5px solid #ef4444;
    font-weight:700; font-size:1.05rem; margin-bottom:0.8rem;
}
.news-warn {
    background:#fefce8; color:#713f12; padding:0.7rem 1.2rem;
    border-radius:10px; border-left:5px solid #eab308;
    font-size:0.95rem; margin-bottom:0.8rem;
}

/* ===== AGENT CARD ===== */
.agent-wrap { padding:0.8rem 1rem; border-radius:10px; margin-bottom:0.5rem; }
.agent-buy  { background:#0f2d1f; border-left:4px solid #22c55e; }
.agent-sell { background:#2d0f0f; border-left:4px solid #ef4444; }
.agent-wait { background:#1a1f2e; border-left:4px solid #64748b; }
.agent-name { font-weight:700; font-size:1rem; }
.agent-reason { font-size:0.88rem; opacity:0.8; margin-top:0.2rem; }

/* ===== TABS ===== */
.stTabs [data-baseweb="tab-list"] { gap:6px; flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] {
    padding:0.5rem 1rem; border-radius:8px 8px 0 0;
    background:#1e293b; color:#94a3b8; font-size:0.92rem;
}
.stTabs [aria-selected="true"] {
    background:#0ea5e9 !important; color:white !important;
}

/* ===== MISC ===== */
div[data-testid="stMetricValue"] { font-size:1.4rem; }
.stButton>button { border-radius:8px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  CACHED LOADERS  (ttl=5 menit)
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_signal_bundle():
    return generate_signals(use_pm_narrative=HAS_AI_KEY)


@st.cache_data(ttl=300)
def load_chart_data(interval: str):
    df = fetch_xau(interval)
    df = add_all(df)
    df = add_all_smc(df)
    df = detect_regime(df)
    return df


@st.cache_data(ttl=3600)
def load_calendar():
    return fetch_calendar()


# ─────────────────────────────────────────────
#  LOAD DATA
# ─────────────────────────────────────────────
with st.spinner("⏳ Memuat data pasar & menjalankan analisis 4-agent..."):
    try:
        bundle = load_signal_bundle()
    except Exception as e:
        st.error(f"❌ Gagal memuat data: {e}")
        st.exception(e)
        st.stop()


# ─────────────────────────────────────────────
#  HEADER  (logo + status + refresh)
# ─────────────────────────────────────────────
h1, h2, h3 = st.columns([3, 3, 1])
with h1:
    st.markdown("## 🪙 yeehee")
    st.caption("Platform Signal XAU/USD (Emas) — analisis 4 AI agent")
with h2:
    if HAS_AI_KEY:
        st.success("🟢 AI PM aktif (Claude)", icon="✅")
    else:
        st.info("⚪ Mode rule-based (set ANTHROPIC_API_KEY untuk AI PM)", icon="ℹ️")
with h3:
    if st.button("🔄 Refresh", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Data terakhir: {bundle.timestamp} · Harga: **${bundle.xau_price:,.2f}**")

# ─────────────────────────────────────────────
#  NEWS ALERT BAR
# ─────────────────────────────────────────────
if bundle.in_news_blackout:
    ev = bundle.blackout_event
    st.markdown(
        f"<div class='news-blackout'>🚨 BLACKOUT BERITA — {ev['title']} ({ev['currency']}) "
        f"pukul {ev['when_utc']} UTC. Engine auto-SKIP entry sekarang.</div>",
        unsafe_allow_html=True,
    )
elif bundle.upcoming_events:
    nev = bundle.upcoming_events[0]
    st.markdown(
        f"<div class='news-warn'>⚠️ Berita berdampak tinggi segera: <b>{nev['title']}</b> "
        f"({nev['currency']}) pukul {nev['when_utc']} UTC. Hati-hati sebelum entry.</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
#  HERO SECTION — aksi utama engine sekarang
# ─────────────────────────────────────────────
debate_d   = bundle.debate
fin_action = debate_d["final_action"]          # LONG / SHORT / FLAT
fin_str    = debate_d["signal_strength"]       # STRONG / NORMAL / WEAK / FLAT
fin_conf   = debate_d["confidence"]

action_label, action_color = humanize_action(fin_action)
str_label, str_color, str_desc = humanize_strength(fin_str)

if fin_action == "LONG":
    hero_css = "hero-buy"
elif fin_action == "SHORT":
    hero_css = "hero-sell"
else:
    hero_css = "hero-wait"

# Pilih sinyal terbaik untuk hero (intraday > swing > scalper)
def _best_sig():
    for s in [bundle.intraday_signal, bundle.swing_signal, bundle.scalper_signal]:
        if s.get("side") != "FLAT":
            return s
    return bundle.intraday_signal

best_sig = _best_sig()
hero_extra = ""
if fin_action != "FLAT" and best_sig.get("side") != "FLAT":
    e, sl, tp1 = best_sig["entry"], best_sig["sl"], best_sig["tp1"]
    rr = best_sig.get("rr_to_tp1", 0)
    hero_extra = (
        f"<span style='opacity:.85'>Masuk: <b>${e:,.2f}</b> &nbsp;·&nbsp; "
        f"SL: <b>${sl:,.2f}</b> &nbsp;·&nbsp; "
        f"TP1: <b>${tp1:,.2f}</b> &nbsp;·&nbsp; "
        f"R:R = <b>{rr:.1f}×</b></span>"
    )

regime_label, _ = humanize_regime(bundle.regime)
session_label, _ = humanize_session(bundle.session)

flat_explain = ""
if fin_action == "FLAT":
    flat_explain = (
        f"<div style='margin-top:.6rem;font-size:.95rem;color:#94a3b8'>"
        f"{explain_flat(bundle.intraday_signal)}</div>"
    )

st.markdown(
    f"<div class='{hero_css}'>"
    f"<div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem'>"
    f"<div>"
    f"<p class='hero-action'>{action_label}</p>"
    f"<p class='hero-sub'>{str_label} &nbsp;·&nbsp; Keyakinan: {fin_conf:.0%} "
    f"&nbsp;·&nbsp; {regime_label} &nbsp;·&nbsp; {session_label}</p>"
    f"{flat_explain}"
    f"{'<p style=margin-top:.5rem>' + hero_extra + '</p>' if hero_extra else ''}"
    f"</div>"
    f"<div style='text-align:right'>"
    f"<p class='hero-price'>XAU/USD</p>"
    f"<p style='font-size:2.4rem;font-weight:900;margin:0'>${bundle.xau_price:,.2f}</p>"
    f"</div>"
    f"</div>"
    f"</div>",
    unsafe_allow_html=True,
)

st.markdown("")  # spacer


# ─────────────────────────────────────────────
#  TABS
# ─────────────────────────────────────────────
(
    tab_sinyal, tab_kalkulator, tab_chart,
    tab_ai, tab_berita, tab_backtest,
    tab_telegram, tab_glosarium,
) = st.tabs([
    "🎯 Sinyal Sekarang",
    "💰 Kalkulator",
    "📈 Chart",
    "🧠 Analisis AI",
    "📅 Berita Penting",
    "🔬 Test Strategi",
    "📱 Setup Telegram",
    "📖 Glosarium",
])


# ══════════════════════════════════════════════
#  TAB 1 · SINYAL SEKARANG
# ══════════════════════════════════════════════
with tab_sinyal:
    st.markdown("### 3 Gaya Trading — Pilih yang Sesuai Lo")
    st.caption(
        "**Scalper** = hold menit (M5) · **Intraday** = hold beberapa jam (M15) · **Swing** = hold 2-7 hari (H4). "
        "Engine butuh 3 dari 4 AI sepakat baru sinyal keluar."
    )

    def render_signal_card(style_name: str, sig: dict, icon: str, col):
        side    = sig.get("side", "FLAT")
        conf    = sig.get("confidence", 0.0)
        ccount  = sig.get("confluence_count", 0)
        reasons = sig.get("reasons", [])
        risks   = sig.get("risks", [])

        act_label, _ = humanize_action(side)

        if side == "LONG":
            css        = "sig-card-buy"
            conf_color = "#22c55e"
        elif side == "SHORT":
            css        = "sig-card-sell"
            conf_color = "#ef4444"
        else:
            css        = "sig-card-wait"
            conf_color = "#64748b"

        with col:
            st.markdown(f"<div class='{css}'>", unsafe_allow_html=True)
            st.markdown(
                f"<p class='sig-label'>{icon} {style_name}</p>"
                f"<p style='margin:.3rem 0;font-size:1.2rem;font-weight:700;color:{conf_color}'>{act_label}</p>",
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)

            # Progress bar keyakinan
            st.caption(f"Keyakinan: **{conf:.0%}** · Faktor sepakat: {ccount}")
            st.progress(min(conf, 1.0))

            # Level harga (kalau bukan FLAT)
            if side != "FLAT":
                e  = sig.get("entry", 0)
                sl = sig.get("sl", 0)
                t1 = sig.get("tp1", 0)
                t2 = sig.get("tp2", 0)
                t3 = sig.get("tp3", 0)
                r1 = sig.get("rr_to_tp1", 0)
                r2 = sig.get("rr_to_tp2", 0)

                lc1, lc2 = st.columns(2)
                lc1.metric("Entry", f"${e:,.2f}")
                lc2.metric("Stop Loss", f"${sl:,.2f}",
                           delta=f"−${abs(e-sl):.2f}", delta_color="inverse")

                tc1, tc2, tc3 = st.columns(3)
                tc1.metric("TP1", f"${t1:,.2f}", delta=f"R {r1:.1f}×")
                tc2.metric("TP2", f"${t2:,.2f}", delta=f"R {r2:.1f}×")
                tc3.metric("TP3", f"${t3:,.2f}")
            else:
                flat_msg = explain_flat(sig)
                st.info(flat_msg, icon="💭")

            # Detail expander
            with st.expander(f"🔍 Detail alasan & risiko"):
                if reasons:
                    st.markdown("**Kenapa sinyal ini keluar:**")
                    for r in reasons:
                        st.markdown(f"• {r}")
                if risks:
                    st.markdown("**⚠️ Risiko yang dideteksi:**")
                    for r in risks:
                        st.markdown(f"• {r}")
                if not reasons and not risks:
                    st.caption("Belum ada data detail.")

    c1, c2, c3 = st.columns(3)
    render_signal_card("Scalper (M5)",   bundle.scalper_signal,  "⚡", c1)
    render_signal_card("Intraday (M15)", bundle.intraday_signal, "🎯", c2)
    render_signal_card("Swing (H4)",     bundle.swing_signal,    "🌊", c3)

    # ── Macro snapshot bawah ──
    st.markdown("---")
    st.markdown("#### 📊 Kondisi Pasar Sekarang")

    inter      = bundle.intermarket
    score      = inter.get("score", 0)
    comps      = inter.get("components", {})
    macro_lbl, macro_clr = macro_bias_label(score)
    cot_z      = bundle.cot.get("z")
    cot_lbl, _ = cot_label(cot_z)

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Bias Makro", macro_lbl, delta=f"{score:+.2f}",
               help="Skor gabungan DXY + US10Y + VIX + SPX + Gold/Silver")
    mc2.metric("DXY (USD)", f"{comps.get('dxy', 0):+.2f}",
               help="DXY naik = USD kuat = emas cenderung turun")
    mc3.metric("US 10Y Yield", f"{comps.get('us10y', 0):+.2f}",
               help="Yield naik = emas cenderung turun (korelasi negatif)")
    mc4.metric("VIX (Ketakutan)", f"{comps.get('vix', 0):+.2f}",
               help="VIX tinggi = pasar takut = emas bisa naik (safe haven)")
    short_cot = cot_lbl[:28] + "…" if len(cot_lbl) > 28 else cot_lbl
    mc5.metric("Posisi COT", short_cot,
               help="COT = posisi trader besar di CFTC. Extreme = potensi balik arah.")


# ══════════════════════════════════════════════
#  TAB 2 · KALKULATOR
# ══════════════════════════════════════════════
with tab_kalkulator:
    st.markdown("### 💰 Kalkulator Posisi")
    st.caption("Hitung berapa lot yang harus dibuka berdasarkan modal dan toleransi risiko lo.")

    kcol1, kcol2 = st.columns([1, 1])

    with kcol1:
        st.markdown("**⚙️ Pengaturan Akun**")

        equity = st.number_input(
            "Modal Akun (USD)", min_value=100.0, value=10_000.0, step=500.0,
            help="Total uang di akun broker lo (dalam USD)",
        )

        profile_keys = list(RISK_PROFILES.keys())
        def_idx = (profile_keys.index(DEFAULT_RISK_PROFILE)
                   if DEFAULT_RISK_PROFILE in profile_keys else 1)

        profile_labels = {k: humanize_profile(k)[0] for k in profile_keys}
        profile_sel = st.selectbox(
            "Profil Risiko",
            profile_keys,
            index=def_idx,
            format_func=lambda k: profile_labels[k],
            help="Pilih seberapa agresif risk per trade",
        )
        _, prof_desc = humanize_profile(profile_sel)
        st.caption(f"*{prof_desc}*")

        broker_lev = st.number_input(
            "Leverage Broker", min_value=1.0, value=100.0, step=10.0,
            help="Leverage dari broker lo (contoh: 100 = 1:100)",
        )

        custom = st.toggle("Ubah % risk secara manual")
        if custom:
            risk_pct = st.slider(
                "Risk per trade (%)", 0.1, 20.0,
                RISK_PROFILES[profile_sel]["risk_per_trade"] * 100, 0.1,
                format="%.1f%%",
            ) / 100
        else:
            risk_pct = RISK_PROFILES[profile_sel]["risk_per_trade"]

    with kcol2:
        st.markdown("**📍 Level Harga**")

        sig_src = st.selectbox(
            "Pakai level dari sinyal mana?",
            ["intraday", "scalper", "swing", "manual"],
            format_func=lambda x: {
                "intraday": "🎯 Intraday (M15) — Rekomendasi",
                "scalper":  "⚡ Scalper (M5)",
                "swing":    "🌊 Swing (H4)",
                "manual":   "✏️ Isi manual",
            }[x],
        )

        if sig_src == "manual":
            price = bundle.xau_price
            entry = st.number_input("Entry", value=float(price), step=0.5)
            sl    = st.number_input("Stop Loss", value=float(price - 10), step=0.5)
            tp1   = st.number_input("TP1", value=float(price + 15), step=0.5)
            tp2   = st.number_input("TP2", value=float(price + 30), step=0.5)
            tp3   = st.number_input("TP3", value=float(price + 50), step=0.5)
            side  = st.radio("Arah", ["LONG", "SHORT"], horizontal=True)
        else:
            _map = {
                "scalper":  bundle.scalper_signal,
                "intraday": bundle.intraday_signal,
                "swing":    bundle.swing_signal,
            }
            sig   = _map[sig_src]
            entry = float(sig["entry"])
            sl    = float(sig["sl"])
            tp1   = float(sig["tp1"])
            tp2   = float(sig["tp2"])
            tp3   = float(sig["tp3"])
            side  = sig["side"] if sig["side"] != "FLAT" else "LONG"

            if sig["side"] == "FLAT":
                st.warning(
                    "Sinyal sedang FLAT — level yang ditampilkan adalah harga terakhir. "
                    "Tunggu sinyal aktif sebelum entry.", icon="⚠️",
                )
            else:
                act_lbl, _ = humanize_action(side)
                st.info(
                    f"Menggunakan: **{act_lbl}** @ ${entry:,.2f} · SL ${sl:,.2f} · TP1 ${tp1:,.2f}",
                    icon="📍",
                )

    # ── Hitung posisi ──
    plan = compute_position(
        equity_usd=equity, entry=entry, sl=sl,
        tp1=tp1, tp2=tp2, tp3=tp3,
        side=side, profile=profile_sel,
        broker_max_leverage=broker_lev,
        custom_risk_pct=risk_pct if custom else None,
    )

    st.markdown("---")
    st.markdown("#### 📋 Hasil Kalkulasi")

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Ukuran Lot",         f"{plan.lot_size:.2f} lot",
              delta=f"{plan.units_oz:.0f} oz")
    r2.metric("Risk Jika Kena SL",  f"${plan.risk_amount_usd:,.2f}",
              delta=f"{plan.risk_pct*100:.2f}% modal", delta_color="inverse")
    r3.metric("Leverage Terpakai",  f"{plan.leverage_used:.1f}×")
    r4.metric("Nilai Pip",          f"${plan.pip_value_usd:.2f}/pip")

    r5, r6, r7 = st.columns(3)
    r5.metric("Notional",          f"${plan.notional_value_usd:,.0f}")
    r6.metric("Margin Ditahan",    f"${plan.margin_required_usd:,.0f}")
    r7.metric("Profil",            humanize_profile(plan.profile)[0])

    st.markdown("#### 🎯 Potensi Keuntungan")
    p1, p2, p3 = st.columns(3)
    safe_risk = plan.risk_amount_usd if plan.risk_amount_usd else 1
    p1.metric("TP1 tercapai", f"${plan.expected_payoff_usd['tp1']:,.0f}",
              delta=f"R = {plan.expected_payoff_usd['tp1']/safe_risk:.1f}×")
    p2.metric("TP2 tercapai", f"${plan.expected_payoff_usd['tp2']:,.0f}",
              delta=f"R = {plan.expected_payoff_usd['tp2']/safe_risk:.1f}×")
    p3.metric("TP3 tercapai", f"${plan.expected_payoff_usd['tp3']:,.0f}",
              delta=f"R = {plan.expected_payoff_usd['tp3']/safe_risk:.1f}×")

    if plan.warnings:
        st.warning("⚠️ " + " · ".join(plan.warnings))

    with st.expander("🎲 Saran ukuran posisi pakai Kelly Criterion"):
        st.caption(
            "Formula matematis untuk ukuran posisi optimal. "
            "Kita pakai 0.25× Kelly (standar institusional — lebih aman dari Kelly penuh)."
        )
        kc1, kc2 = st.columns(2)
        wr   = kc1.slider("Estimasi win rate lo (%)", 30, 80, 55, 1) / 100
        avgr = kc2.slider("Estimasi rata-rata profit (dalam R)", 1.0, 5.0, 2.0, 0.1)
        kelly_pct = kelly_fractional(wr, avgr, fraction=0.25) * 100
        st.success(
            f"**Saran risk per trade (0.25× Kelly): {kelly_pct:.2f}%** dari modal",
            icon="💡",
        )
        st.caption(
            f"Win rate {wr:.0%} + avg R {avgr:.1f} → Kelly penuh = {kelly_pct/0.25:.2f}%, "
            f"kita pakai ¼-nya = {kelly_pct:.2f}% buat aman."
        )


# ══════════════════════════════════════════════
#  TAB 3 · CHART
# ══════════════════════════════════════════════
with tab_chart:
    ctrl1, ctrl2, ctrl3, ctrl4, ctrl5 = st.columns(5)
    interval    = ctrl1.selectbox("Timeframe", ["5m", "15m", "1h", "4h", "1d"], index=2)
    show_ema    = ctrl2.checkbox("EMA lines", value=True)
    show_bb     = ctrl3.checkbox("Bollinger Bands", value=False)
    show_smc    = ctrl4.checkbox("SMC marks", value=True)
    show_levels = ctrl5.checkbox("Level sinyal", value=True)

    with st.spinner(f"Memuat chart {interval}..."):
        df_c = load_chart_data(interval)
    df_plot = df_c.tail(300).copy()

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.65, 0.20, 0.15],
        subplot_titles=("XAU/USD", "RSI(14) / ADX(14)", "Volume"),
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df_plot.index,
        open=df_plot["open"], high=df_plot["high"],
        low=df_plot["low"],  close=df_plot["close"],
        name="XAU",
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444",
    ), row=1, col=1)

    # EMAs
    if show_ema:
        for col_name, color, w in [
            ("ema21",  "#3b82f6", 1.5),
            ("ema50",  "#a855f7", 1.5),
            ("ema200", "#f59e0b", 2.0),
        ]:
            if col_name in df_plot.columns:
                fig.add_trace(go.Scatter(
                    x=df_plot.index, y=df_plot[col_name],
                    name=col_name.upper(), line=dict(width=w, color=color),
                ), row=1, col=1)

    # Bollinger Bands
    if show_bb and "bb_up" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["bb_up"], name="BB atas",
            line=dict(width=1, dash="dot", color="#94a3b8"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["bb_low"], name="BB bawah",
            line=dict(width=1, dash="dot", color="#94a3b8"),
            fill="tonexty", fillcolor="rgba(148,163,184,0.06)",
        ), row=1, col=1)

    # SMC marks
    if show_smc:
        smc_marks = [
            ("bull_sweep", "triangle-up",   "#22c55e", "Likuiditas Tersapu ↑"),
            ("bear_sweep", "triangle-down", "#ef4444", "Likuiditas Tersapu ↓"),
            ("fvg_bull",   "circle",        "#86efac", "FVG Bullish"),
            ("fvg_bear",   "circle",        "#fca5a5", "FVG Bearish"),
            ("bos_up",     "star",          "#22d3ee", "BOS Naik"),
            ("bos_dn",     "star",          "#fb7185", "BOS Turun"),
        ]
        for col_name, sym, clr, label in smc_marks:
            if col_name in df_plot.columns:
                mask = df_plot[col_name].fillna(False).astype(bool)
                if mask.any():
                    sub = df_plot[mask]
                    is_up = "up" in col_name or "bull" in col_name
                    y_ref = sub["high"] * 1.002 if is_up else sub["low"] * 0.998
                    fig.add_trace(go.Scatter(
                        x=sub.index, y=y_ref, mode="markers", name=label,
                        marker=dict(symbol=sym, size=10, color=clr),
                        hovertemplate=f"{label}<br>%{{y:.2f}}",
                    ), row=1, col=1)

    # Signal levels
    if show_levels:
        for lname, sig, color in [
            ("Scalper",  bundle.scalper_signal,  "#06b6d4"),
            ("Intraday", bundle.intraday_signal, "#a855f7"),
            ("Swing",    bundle.swing_signal,    "#f59e0b"),
        ]:
            if sig.get("side") != "FLAT":
                for lvl_name, lvl_val, dash in [
                    (f"{lname} Entry", sig["entry"], "solid"),
                    (f"{lname} SL",    sig["sl"],    "dash"),
                    (f"{lname} TP1",   sig["tp1"],   "dot"),
                ]:
                    fig.add_hline(
                        y=lvl_val,
                        line=dict(color=color, dash=dash, width=1),
                        annotation_text=lvl_name,
                        annotation_position="right",
                        annotation_font_size=10,
                        row=1, col=1,
                    )

    # RSI + ADX
    if "rsi14" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["rsi14"], name="RSI",
            line=dict(color="#3b82f6", width=1.5),
        ), row=2, col=1)
        fig.add_hline(y=70, line=dict(color="#ef4444", dash="dot", width=1), row=2, col=1)
        fig.add_hline(y=30, line=dict(color="#22c55e", dash="dot", width=1), row=2, col=1)
    if "adx" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["adx"], name="ADX",
            line=dict(color="#a855f7", width=1.5),
        ), row=2, col=1)
        fig.add_hline(y=25, line=dict(color="#f59e0b", dash="dot", width=1), row=2, col=1)

    # Volume
    if "volume" in df_plot.columns:
        vol_colors = [
            "#22c55e" if df_plot["close"].iloc[i] >= df_plot["open"].iloc[i]
            else "#ef4444"
            for i in range(len(df_plot))
        ]
        fig.add_trace(go.Bar(
            x=df_plot.index, y=df_plot["volume"], name="Volume",
            marker_color=vol_colors,
        ), row=3, col=1)

    fig.update_layout(
        height=750,
        template="plotly_dark",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        margin=dict(t=40, b=20, l=20, r=100),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font_size=11),
    )
    st.plotly_chart(fig, width='stretch')

    rg_now = df_plot["regime"].iloc[-1] if "regime" in df_plot.columns else "?"
    rg_lbl, rg_desc = humanize_regime(rg_now)
    st.info(f"**Regime saat ini ({interval}):** {rg_lbl} — {rg_desc}", icon="📊")


# ══════════════════════════════════════════════
#  TAB 4 · ANALISIS AI  (4-agent debate)
# ══════════════════════════════════════════════
with tab_ai:
    d     = bundle.debate
    fa    = d["final_action"]
    fstr  = d["signal_strength"]
    fconf = d["confidence"]

    str_label, str_color, str_desc = humanize_strength(fstr)
    act_label, _ = humanize_action(fa)

    # Final verdict banner
    st.markdown(
        f"<div style='background:{str_color};color:white;padding:1rem 1.5rem;"
        f"border-radius:12px;margin-bottom:1.2rem'>"
        f"<h2 style='margin:0'>{act_label} &nbsp;·&nbsp; {str_label}</h2>"
        f"<p style='margin:.3rem 0 0;opacity:.9'>{str_desc}</p>"
        f"<p style='margin:.3rem 0 0;opacity:.8'>Keyakinan: {fconf:.0%}"
        f"{'  ·  Driver utama: ' + d.get('primary_driver','') if d.get('primary_driver') else ''}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### 🤖 Pendapat Masing-masing AI Agent")
    st.caption(
        "Butuh **3 dari 4** agent sepakat baru sinyal keluar. "
        "Devil's Advocate bisa VETO kalau risiko dianggap terlalu tinggi."
    )

    for ag in d.get("agents", []):
        v    = ag.get("verdict", "FLAT")
        conf = ag.get("confidence", 0.0)
        name = humanize_agent(ag.get("name", ""))
        reasons_list = ag.get("reasoning", [])

        if v == "LONG":
            ag_css, v_icon, v_color = "agent-buy",  "🟢", "#22c55e"
        elif v == "SHORT":
            ag_css, v_icon, v_color = "agent-sell", "🔴", "#ef4444"
        else:
            ag_css, v_icon, v_color = "agent-wait", "⚪", "#94a3b8"

        act_v, _ = humanize_action(v)
        reasons_str = " · ".join(reasons_list[:4]) if reasons_list else "(tidak ada detail)"

        st.markdown(
            f"<div class='agent-wrap {ag_css}'>"
            f"<span class='agent-name'>{v_icon} {name}</span>"
            f"&nbsp;&nbsp;<span style='color:{v_color};font-weight:700'>{act_v}</span>"
            f"&nbsp;<span style='color:#64748b;font-size:.9rem'>({conf:.0%})</span>"
            f"<div class='agent-reason'>{reasons_str}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if d.get("reasoning_chain"):
        with st.expander("🔗 Detail alur penalaran lengkap"):
            for line in d["reasoning_chain"]:
                st.markdown(f"• {line}")

    if d.get("risks"):
        with st.expander("⚠️ Risiko yang dideteksi engine"):
            for r in d["risks"]:
                st.markdown(f"• {r}")

    # PM narrative (Claude AI)
    if bundle.ai_pm_used and getattr(bundle, "pm_narrative", None):
        st.markdown("### 🎩 Narasi PM (Claude AI)")
        pn = bundle.pm_narrative
        if isinstance(pn, dict):
            if pn.get("summary"):
                st.markdown(f"**Ringkasan:** {pn['summary']}")
            if pn.get("trade_idea"):
                st.markdown(f"**Ide Trade:** {pn['trade_idea']}")
            if pn.get("key_risks"):
                st.markdown("**Risiko Kunci:**")
                for r in pn["key_risks"]:
                    st.markdown(f"• {r}")
        else:
            st.markdown(str(pn))
    elif not HAS_AI_KEY:
        st.caption("💡 Set `ANTHROPIC_API_KEY` di `.env` untuk mengaktifkan narasi Claude PM.")


# ══════════════════════════════════════════════
#  TAB 5 · BERITA PENTING
# ══════════════════════════════════════════════
with tab_berita:
    st.markdown("### 📅 Kalender Berita Ekonomi (7 Hari Ke Depan)")
    st.caption(
        "Event **HIGH** (merah) = dampak besar ke emas. "
        "Engine auto-skip entry 30 menit sebelum & sesudah event ini."
    )

    with st.spinner("Memuat kalender..."):
        cal = load_calendar()

    if not cal:
        st.warning("Kalender tidak bisa dimuat — ForexFactory mungkin sedang down.", icon="⚠️")
    else:
        now = datetime.now(timezone.utc)
        rows = []
        for e in cal:
            try:
                t = datetime.fromisoformat(e.when_utc.replace("Z", "+00:00"))
            except Exception:
                continue
            if t < now - timedelta(hours=3) or t > now + timedelta(days=7):
                continue
            t_wib = t + timedelta(hours=7)
            rows.append({
                "Waktu WIB":   t_wib.strftime("%a %d %b %H:%M"),
                "Mata Uang":   e.currency,
                "Dampak":      e.impact.upper(),
                "Event":       e.title,
                "Perkiraan":   e.forecast or "—",
                "Sebelumnya":  e.previous or "—",
            })

        if rows:
            df_cal = pd.DataFrame(rows)

            def _impact_style(val):
                if val == "HIGH":
                    return "background-color:#fee2e2;color:#991b1b;font-weight:700"
                if val == "MEDIUM":
                    return "background-color:#fefce8;color:#713f12"
                return "color:#64748b"

            st.dataframe(
                df_cal.style.map(_impact_style, subset=["Dampak"]),
                width='stretch',
                hide_index=True,
            )

            high_events = [r for r in rows if r["Dampak"] == "HIGH"]
            if high_events:
                st.markdown("#### 🚨 Sorotan — Event High Impact")
                for ev in high_events[:6]:
                    st.error(
                        f"**{ev['Event']}** ({ev['Mata Uang']}) — {ev['Waktu WIB']} WIB"
                        f"  ·  Perkiraan: {ev['Perkiraan']}  ·  Sebelumnya: {ev['Sebelumnya']}",
                        icon="🚨",
                    )
        else:
            st.info("Tidak ada event dalam 7 hari ke depan.", icon="✅")

    st.markdown("---")
    if bundle.in_news_blackout:
        st.error("🚨 SEKARANG DALAM BLACKOUT! Engine tidak akan fire sinyal baru.", icon="🚨")
    else:
        st.success("✅ Tidak ada blackout news sekarang. Engine bebas fire sinyal.", icon="✅")


# ══════════════════════════════════════════════
#  TAB 6 · TEST STRATEGI  (backtest + MC)
# ══════════════════════════════════════════════
with tab_backtest:
    st.markdown("### 🔬 Test Strategi (Backtest + Monte Carlo)")
    st.caption(
        "Simulasi performa strategi EMA cross + ADX filter di data historis. "
        "Monte Carlo = ribuan skenario alternatif buat lihat seberapa robust hasilnya."
    )

    bc1, bc2, bc3, bc4 = st.columns(4)
    bt_tf   = bc1.selectbox("Timeframe", ["1h", "4h", "1d"], index=1, key="bt_tf")
    bt_eq   = bc2.number_input("Modal Awal (USD)", value=10_000.0, step=1000.0, key="bt_eq")
    bt_risk = bc3.slider("Risk per trade (%)", 0.1, 5.0, 1.0, 0.1, key="bt_risk") / 100
    bt_mc   = bc4.selectbox("Simulasi MC", [10_000, 50_000, 100_000], index=2, key="bt_mc")

    if st.button("🚀 Jalankan Backtest + Monte Carlo", type="primary", use_container_width=True):
        with st.spinner(f"Memuat data {bt_tf}..."):
            df_bt = load_chart_data(bt_tf)
        with st.spinner("Menjalankan backtest bar-per-bar..."):
            bt = run_backtest(df_bt, default_swing_signal,
                              starting_equity=bt_eq, risk_per_trade=bt_risk)
        with st.spinner(f"Menjalankan {bt_mc:,} simulasi Monte Carlo..."):
            mc_res = run_monte_carlo(bt, n_runs=bt_mc, risk_per_trade=bt_risk)

        stats = bt.stats()
        st.success(f"✅ Selesai! {stats['n_trades']} trade dalam {len(df_bt)} bar data.", icon="✅")

        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Win Rate",     f"{stats['win_rate']*100:.1f}%",
                  help="Persen trade yang profit")
        s2.metric("Expectancy",   f"{stats['expectancy_r']:.2f} R",
                  help="Rata-rata profit per trade (dalam kelipatan risk)")
        s3.metric("Total Return", f"{stats['total_return_pct']:.1f}%")
        s4.metric("Max Drawdown", f"{stats['max_drawdown_pct']:.1f}%", delta_color="inverse")
        s5.metric("Sharpe",       f"{stats['sharpe']:.2f}",
                  help=">1 bagus, >2 sangat bagus, >3 excellent")

        # Equity curve
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            y=bt.equity_curve, mode="lines", name="Equity",
            line=dict(color="#22d3ee", width=2),
            fill="tozeroy", fillcolor="rgba(34,211,238,0.08)",
        ))
        fig_eq.update_layout(
            title="Kurva Equity",
            template="plotly_dark", height=300,
            margin=dict(t=40, b=20, l=20, r=20),
            xaxis_title="Trade ke-", yaxis_title="Equity (USD)",
        )
        st.plotly_chart(fig_eq, width='stretch')

        # Monte Carlo
        st.markdown("### 🎲 Hasil Monte Carlo")
        st.caption("P5 = skenario terburuk 5% · P95 = skenario terbaik 5%")
        mc_d = mc_res.to_dict()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Median Akhir",   f"${mc_d['final_equity_p50']:,.0f}",
                  delta=f"+{(mc_d['final_equity_p50']/mc_d['starting_equity']-1)*100:.1f}%")
        m2.metric("P5 (Terburuk)",  f"${mc_d['final_equity_p5']:,.0f}")
        m3.metric("P95 (Terbaik)",  f"${mc_d['final_equity_p95']:,.0f}")
        m4.metric("Prob Profit",    f"{mc_d['prob_profit']*100:.1f}%")

        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Median Max DD",       f"{mc_d['max_dd_p50']:.1f}%")
        m6.metric("DD Terparah (P5)",    f"{mc_d['max_dd_p5']:.1f}%")
        m7.metric("Prob DD >30%",        f"{mc_d['prob_30pct_dd']*100:.1f}%")
        m8.metric("Prob Blowup (>50%DD)",f"{mc_d['prob_blowup']*100:.1f}%")

        if bt.trades:
            r_arr = np.array([t.pnl_r for t in bt.trades])
            fig_hist = go.Figure(go.Histogram(
                x=r_arr, nbinsx=40, marker_color="#0ea5e9",
                marker_line_color="#0c4a6e", marker_line_width=0.5,
            ))
            fig_hist.update_layout(
                title="Distribusi R-multiple per Trade",
                template="plotly_dark", height=260,
                margin=dict(t=40, b=20, l=20, r=20),
                xaxis_title="R-multiple", yaxis_title="Jumlah trade",
            )
            st.plotly_chart(fig_hist, width='stretch')

        st.caption(
            "⚠️ Past performance ≠ future result. "
            "Backtest sudah termasuk spread + slippage, tapi tidak mencakup gap, requote, dan kondisi ekstrem."
        )


# ══════════════════════════════════════════════
#  TAB 7 · SETUP TELEGRAM
# ══════════════════════════════════════════════
with tab_telegram:
    st.markdown("### 📱 Setup Notifikasi Telegram")
    st.caption("Terima sinyal langsung ke HP lo via Telegram bot. Gratis, real-time, otomatis.")

    if HAS_TELEGRAM:
        st.success(
            f"✅ Telegram AKTIF  ·  Token: {TELEGRAM_BOT_TOKEN[:14]}...  ·  Chat ID: {TELEGRAM_CHAT_ID}",
            icon="✅",
        )
    else:
        st.warning("⚠️ Telegram belum dikonfigurasi. Ikuti 3 langkah di bawah ini.", icon="📱")

    st.markdown("---")

    with st.expander("📌 Langkah 1 — Buat bot Telegram (gratis)", expanded=not HAS_TELEGRAM):
        st.markdown("""
1. Buka Telegram di HP atau PC
2. Cari **@BotFather** → klik Start
3. Ketik `/newbot`
4. Ikuti instruksi: masukkan nama bot (bebas), lalu username yang diakhiri `bot`
   - Contoh username: `YeeheeGoldBot`
5. BotFather akan memberikan **token** — contohnya:
   ```
   1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ-example
   ```
6. **Copy token tersebut**, lalu buka bot lo di Telegram dan klik **Start**

> ✅ Bot lo sudah aktif dan siap menerima koneksi dari yeehee.
""")

    with st.expander("🔑 Langkah 2 — Dapatkan Chat ID & test koneksi", expanded=not HAS_TELEGRAM):
        st.markdown("""
**Chat ID** adalah nomor unik Telegram lo. Cara mendapatkannya:
1. Buka bot lo → kirim pesan `/start`
2. Buka URL ini di browser (ganti `<TOKEN>` dengan token lo):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Cari bagian `"chat": {"id": 123456789}` — angka `id` itu adalah Chat ID lo
""")

        tok_input = st.text_input(
            "Masukkan Bot Token",
            value=TELEGRAM_BOT_TOKEN,
            type="password" if TELEGRAM_BOT_TOKEN else "default",
            placeholder="1234567890:ABCdef...",
            key="wz_tok",
        )
        cid_input = st.text_input(
            "Masukkan Chat ID",
            value=TELEGRAM_CHAT_ID,
            placeholder="contoh: 123456789",
            key="wz_cid",
        )

        wz1, wz2 = st.columns(2)

        if wz1.button("🔍 Verifikasi Token", use_container_width=True, key="btn_tok"):
            if tok_input:
                with st.spinner("Memeriksa token ke Telegram..."):
                    res = test_bot_token(tok_input)
                if res["ok"]:
                    st.success(
                        f"✅ Token valid!\n\nBot: **@{res['username']}** "
                        f"(ID: {res['id']}, Nama: {res['name']})",
                        icon="✅",
                    )
                    st.session_state["wz_token_ok"] = True
                else:
                    st.error(f"❌ {res['error']}", icon="❌")
                    st.session_state["wz_token_ok"] = False
            else:
                st.warning("Masukkan token dulu.", icon="⚠️")

        if wz2.button("📤 Kirim Pesan Test", use_container_width=True, key="btn_cid"):
            if tok_input and cid_input:
                with st.spinner("Mengirim pesan test ke Telegram lo..."):
                    res = test_chat_id(tok_input, cid_input)
                if res["ok"]:
                    st.success(f"✅ {res['msg']}", icon="✅")
                    st.session_state["wz_chat_ok"] = True
                else:
                    st.error(f"❌ {res['error']}", icon="❌")
                    st.session_state["wz_chat_ok"] = False
            else:
                st.warning("Masukkan token dan chat ID dulu.", icon="⚠️")

    with st.expander("💾 Langkah 3 — Simpan & aktifkan", expanded=not HAS_TELEGRAM):
        env_path = ROOT / ".env"
        st.caption(f"Konfigurasi akan disimpan ke: `{env_path}`")

        sv_tok = st.text_input(
            "Bot Token (untuk disimpan)",
            value=TELEGRAM_BOT_TOKEN or st.session_state.get("wz_tok", ""),
            placeholder="Bot token dari langkah 2",
            key="sv_tok",
        )
        sv_cid = st.text_input(
            "Chat ID (untuk disimpan)",
            value=TELEGRAM_CHAT_ID or st.session_state.get("wz_cid", ""),
            placeholder="Chat ID dari langkah 2",
            key="sv_cid",
        )

        if st.button("💾 Simpan ke .env & Aktifkan", type="primary",
                     use_container_width=True, key="btn_save"):
            if sv_tok and sv_cid:
                ok = update_env_file(str(env_path), sv_tok, sv_cid)
                if ok:
                    st.success(
                        "✅ Berhasil disimpan!\n\n"
                        "**Restart dashboard** agar perubahan aktif:\n"
                        "1. Tutup dashboard (Ctrl+C di CMD)\n"
                        "2. Jalankan lagi: `run.bat`",
                        icon="✅",
                    )
                else:
                    st.error("❌ Gagal menyimpan ke .env. Cek permission file.", icon="❌")
            else:
                st.warning("Token dan Chat ID tidak boleh kosong.", icon="⚠️")

    st.markdown("---")
    st.markdown("#### ⌨️ Perintah Bot Telegram")
    bot_cmds = [
        ("/signal",  "Sinyal terbaru (scalper/intraday/swing)"),
        ("/risk",    "Hitung ukuran posisi & lot"),
        ("/news",    "Berita high-impact hari ini"),
        ("/regime",  "Kondisi pasar sekarang (trend/ranging/volatile)"),
        ("/debate",  "Hasil debat 4 AI agent"),
        ("/strong",  "Hanya tampilkan sinyal STRONG / NEWS_STRONG"),
    ]
    for cmd, desc in bot_cmds:
        st.markdown(f"- **`{cmd}`** — {desc}")

    st.info(
        "💡 Sinyal di-push otomatis setiap **10 menit** (hanya kalau ada sinyal baru). "
        "Jalankan bot dengan perintah: `run.bat bot` di CMD.",
        icon="📱",
    )


# ══════════════════════════════════════════════
#  TAB 8 · GLOSARIUM
# ══════════════════════════════════════════════
with tab_glosarium:
    st.markdown("### 📖 Glosarium Trading — Bahasa Indonesia")
    st.caption(
        "Kamus istilah trading untuk yang baru mulai. "
        "Semua dijelaskan dalam bahasa sehari-hari tanpa jargon berlebihan."
    )

    gq = st.text_input(
        "🔍 Cari istilah...",
        placeholder="contoh: RSI, spread, lot, FVG, COT...",
        key="gloss_q",
    )

    results = glossary_search(gq) if gq else GLOSSARY

    if not results:
        st.info("Istilah tidak ditemukan. Coba kata kunci lain.", icon="🔍")
    else:
        # Tampilkan 2 kolom
        for i in range(0, len(results), 2):
            gc1, gc2 = st.columns(2)
            for col, idx in [(gc1, i), (gc2, i + 1)]:
                if idx < len(results):
                    term, definition = results[idx]
                    with col.expander(f"**{term}**"):
                        st.markdown(definition)

    st.caption(
        f"Total: **{len(GLOSSARY)}** istilah terdaftar · "
        f"{'Filter aktif: ' + repr(gq) if gq else 'Menampilkan semua istilah'}"
    )


# ──────────────────────────────────────────────
#  FOOTER
# ──────────────────────────────────────────────
st.markdown("---")
fc1, fc2 = st.columns([4, 1])
with fc1:
    engine_mode = "Claude PM + rule debate" if bundle.ai_pm_used else "Rule-based debate"
    st.caption(
        f"🪙 yeehee XAU/USD Signal Platform · Engine: {engine_mode} · "
        f"Update terakhir: {bundle.timestamp} · Hanya untuk penggunaan pribadi"
    )
with fc2:
    if st.button("🗑️ Clear Cache", use_container_width=True, help="Paksa reload semua data"):
        st.cache_data.clear()
        st.rerun()
