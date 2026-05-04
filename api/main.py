"""yeehee FastAPI Backend
Wraps the Python signal engine dan expose ke Next.js frontend.
Jalankan: uvicorn api.main:app --reload --port 8000
Atau via: run.bat api
"""
from __future__ import annotations
import os, sys, time, json, logging
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import RISK_PROFILES, HAS_AI_KEY, HAS_TELEGRAM, DEFAULT_RISK_PROFILE

log = logging.getLogger("yeehee.api")

app = FastAPI(
    title="yeehee API",
    description="XAU/USD Signal Platform — REST API",
    version="1.0.0",
)

# CORS — izinkan semua origin (Vercel + local dev)
# Di production: ganti allow_origins dengan domain Vercel lo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Simple in-memory cache ────────────────────────────────────────────────────
_cache: dict = {}

def _cached(key: str, factory, ttl: int = 300):
    """Return cached value if fresh, else call factory() and cache."""
    now = time.monotonic()
    if key in _cache and (now - _cache[key]["ts"]) < ttl:
        return _cache[key]["data"]
    data = factory()
    _cache[key] = {"data": data, "ts": now}
    return data


def _invalidate(key: str):
    _cache.pop(key, None)


# ─── Supabase writer (optional — only if SUPABASE_URL configured) ─────────────
def _get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _save_bundle_to_supabase(bundle_dict: dict):
    sb = _get_supabase()
    if not sb:
        return
    try:
        # Insert bundle
        row = {k: v for k, v in bundle_dict.items()
               if k not in ("scalper_signal", "intraday_signal", "swing_signal",
                            "debate", "intermarket", "cot", "blackout_event",
                            "upcoming_events")}
        row["scalper_signal"]  = json.dumps(bundle_dict.get("scalper_signal"))
        row["intraday_signal"] = json.dumps(bundle_dict.get("intraday_signal"))
        row["swing_signal"]    = json.dumps(bundle_dict.get("swing_signal"))
        row["debate"]          = json.dumps(bundle_dict.get("debate"))
        row["intermarket"]     = json.dumps(bundle_dict.get("intermarket"))
        row["cot"]             = json.dumps(bundle_dict.get("cot"))
        row["blackout_event"]  = json.dumps(bundle_dict.get("blackout_event"))
        row["upcoming_events"] = json.dumps(bundle_dict.get("upcoming_events"))
        # Remove non-db fields
        for f in ("timestamp", "ai_pm_used"):
            row.pop(f, None)

        res = sb.table("signal_bundles").insert(row).execute()
        bundle_id = res.data[0]["id"] if res.data else None

        # Insert individual signals
        if bundle_id:
            for style in ("scalper", "intraday", "swing"):
                sig = bundle_dict.get(f"{style}_signal", {})
                if sig:
                    sb.table("signals").insert({
                        "bundle_id":  bundle_id,
                        "style":      style,
                        "action":     sig.get("side", "FLAT"),
                        "confidence": sig.get("confidence"),
                        "confluence": sig.get("confluence_count"),
                        "entry":      sig.get("entry"),
                        "sl":         sig.get("sl"),
                        "tp1":        sig.get("tp1"),
                        "tp2":        sig.get("tp2"),
                        "tp3":        sig.get("tp3"),
                        "rr_to_tp1":  sig.get("rr_to_tp1"),
                        "rr_to_tp2":  sig.get("rr_to_tp2"),
                        "regime":     sig.get("regime"),
                        "session":    sig.get("session"),
                        "reasons":    json.dumps(sig.get("reasons", [])),
                        "risks":      json.dumps(sig.get("risks", [])),
                        "xau_price":  bundle_dict.get("xau_price"),
                    }).execute()
    except Exception as e:
        log.warning(f"Supabase write failed: {e}")


# ─── Bundle serializer ─────────────────────────────────────────────────────────
def _bundle_to_dict(bundle) -> dict:
    return {
        "xau_price":        bundle.xau_price,
        "timestamp":        bundle.timestamp,
        "regime":           bundle.regime,
        "session":          bundle.session,
        "in_news_blackout": bundle.in_news_blackout,
        "blackout_event":   bundle.blackout_event,
        "upcoming_events":  bundle.upcoming_events,
        "scalper_signal":   bundle.scalper_signal,
        "intraday_signal":  bundle.intraday_signal,
        "swing_signal":     bundle.swing_signal,
        "debate":           bundle.debate,
        "intermarket":      bundle.intermarket,
        "cot":              bundle.cot,
        "ai_pm_used":       bundle.ai_pm_used,
        "final_action":     bundle.debate.get("final_action", "FLAT"),
        "signal_strength":  bundle.debate.get("signal_strength", "FLAT"),
        "confidence":       bundle.debate.get("confidence", 0.0),
    }


# ─── Pydantic models ───────────────────────────────────────────────────────────
class PositionRequest(BaseModel):
    equity_usd: float = 10_000
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    side: str = "LONG"
    profile: str = "moderat"
    broker_max_leverage: float = 100
    custom_risk_pct: Optional[float] = None


class BacktestRequest(BaseModel):
    interval: str = "4h"
    starting_equity: float = 10_000
    risk_per_trade: float = 0.01
    mc_runs: int = 10_000  # default kecil untuk API (100k terlalu lama)


# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "yeehee XAU/USD Signal API",
        "version": "1.0.0",
        "ai_mode": HAS_AI_KEY,
        "telegram": HAS_TELEGRAM,
    }


@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}


@app.get("/api/signals")
def get_signals(background_tasks: BackgroundTasks, refresh: bool = False):
    """
    Generate (atau return cached) signal bundle lengkap.
    TTL cache: 5 menit. Pakai ?refresh=true untuk force regenerate.
    """
    if refresh:
        _invalidate("signals")

    try:
        from signal_engine import generate_signals
        bundle = _cached(
            "signals",
            lambda: generate_signals(use_pm_narrative=HAS_AI_KEY),
        )
        d = _bundle_to_dict(bundle)
        # Save to Supabase in background (non-blocking)
        if refresh:
            background_tasks.add_task(_save_bundle_to_supabase, d)
        return d
    except Exception as e:
        log.exception("Error generating signals")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/position")
def calc_position(req: PositionRequest):
    """Hitung ukuran posisi berdasarkan request."""
    try:
        from risk.sizing import compute_position
        plan = compute_position(
            equity_usd=req.equity_usd,
            entry=req.entry, sl=req.sl,
            tp1=req.tp1, tp2=req.tp2, tp3=req.tp3,
            side=req.side, profile=req.profile,
            broker_max_leverage=req.broker_max_leverage,
            custom_risk_pct=req.custom_risk_pct,
        )
        return {
            "lot_size":            plan.lot_size,
            "units_oz":            plan.units_oz,
            "risk_amount_usd":     plan.risk_amount_usd,
            "risk_pct":            plan.risk_pct,
            "leverage_used":       plan.leverage_used,
            "pip_value_usd":       plan.pip_value_usd,
            "notional_value_usd":  plan.notional_value_usd,
            "margin_required_usd": plan.margin_required_usd,
            "expected_payoff_usd": plan.expected_payoff_usd,
            "profile":             plan.profile,
            "warnings":            plan.warnings,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/calendar")
def get_calendar():
    """Economic calendar (cached 1 jam)."""
    try:
        from data.calendar_fetcher import fetch_calendar
        events = _cached("calendar", fetch_calendar, ttl=3600)
        return [
            {
                "when_utc":  e.when_utc,
                "currency":  e.currency,
                "impact":    e.impact,
                "title":     e.title,
                "forecast":  e.forecast,
                "previous":  e.previous,
            }
            for e in (events or [])
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backtest")
def run_backtest_api(req: BacktestRequest):
    """Jalankan backtest + Monte Carlo. Bisa lambat — max mc_runs=50k via API."""
    try:
        from data.price_fetcher import fetch_xau
        from features.technical import add_all
        from features.smc import add_all_smc
        from features.regime import detect_regime
        from backtest.engine import run_backtest, default_swing_signal
        from backtest.monte_carlo import run_monte_carlo

        mc_runs = min(req.mc_runs, 50_000)  # cap biar tidak timeout

        df = fetch_xau(req.interval)
        df = add_all(df)
        df = add_all_smc(df)
        df = detect_regime(df)

        bt = run_backtest(df, default_swing_signal,
                          starting_equity=req.starting_equity,
                          risk_per_trade=req.risk_per_trade)
        mc = run_monte_carlo(bt, n_runs=mc_runs,
                             risk_per_trade=req.risk_per_trade)

        stats   = bt.stats()
        mc_dict = mc.to_dict()

        return {
            "stats": stats,
            "monte_carlo": mc_dict,
            "n_bars": len(df),
            "equity_curve": bt.equity_curve[:500],  # sampel buat chart
            "trades": [
                {"entry_price": t.entry_price, "exit_price": t.exit_price,
                 "pnl_r": t.pnl_r, "pnl_usd": t.pnl_usd, "side": t.side}
                for t in bt.trades[-200:]  # last 200 trades
            ],
        }
    except Exception as e:
        log.exception("Backtest error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/{interval}")
def get_chart_data(interval: str, bars: int = 200):
    """OHLCV + indicators untuk chart. interval: 5m, 15m, 1h, 4h, 1d."""
    valid = {"5m", "15m", "1h", "4h", "1d"}
    if interval not in valid:
        raise HTTPException(status_code=400, detail=f"interval harus salah satu: {valid}")
    try:
        from data.price_fetcher import fetch_xau
        from features.technical import add_all
        from features.regime import detect_regime

        cache_key = f"chart_{interval}"
        df = _cached(cache_key, lambda: _build_chart_df(interval), ttl=120)

        tail = df.tail(min(bars, 500))
        records = []
        for idx, row in tail.iterrows():
            records.append({
                "time":   int(idx.timestamp()),
                "open":   float(row.get("open", 0)),
                "high":   float(row.get("high", 0)),
                "low":    float(row.get("low", 0)),
                "close":  float(row.get("close", 0)),
                "volume": float(row.get("volume", 0)),
                "ema21":  _safe_float(row.get("ema21")),
                "ema50":  _safe_float(row.get("ema50")),
                "ema200": _safe_float(row.get("ema200")),
                "rsi14":  _safe_float(row.get("rsi14")),
                "adx":    _safe_float(row.get("adx")),
                "regime": str(row.get("regime", "")),
            })
        return {"interval": interval, "bars": len(records), "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_chart_df(interval: str):
    from data.price_fetcher import fetch_xau
    from features.technical import add_all
    from features.regime import detect_regime
    df = fetch_xau(interval)
    df = add_all(df)
    df = detect_regime(df)
    return df


def _safe_float(v) -> Optional[float]:
    try:
        import math
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except Exception:
        return None


@app.get("/api/risk-profiles")
def get_risk_profiles():
    return {
        k: {**v, "label": _profile_label(k)}
        for k, v in RISK_PROFILES.items()
    }


def _profile_label(k: str) -> str:
    labels = {
        "konservatif": "Konservatif (0.5% risk)",
        "moderat":     "Moderat (1% risk) — default",
        "agresif":     "Agresif (2% risk)",
        "bebas":       "Bebas (5% risk) — BAHAYA",
    }
    return labels.get(k, k)


@app.delete("/api/cache")
def clear_cache():
    """Force clear all cached data (force refresh dari yfinance)."""
    _cache.clear()
    return {"cleared": True}
