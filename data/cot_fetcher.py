"""CFTC Commitments of Traders weekly report (Gold = Code 088691).
Free public CSV. Used buat detect extreme positioning (mean reversion edge).
"""
from __future__ import annotations
import io
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from config.settings import DATA_CACHE

CACHE_FILE = DATA_CACHE / "cot_gold.parquet"
CACHE_TTL = 7 * 24 * 3600  # weekly

GOLD_CFTC_CODE = "088691"


def _current_year_url() -> str:
    year = datetime.now().year
    return f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


def _prev_year_url() -> str:
    year = datetime.now().year - 1
    return f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


def _download_zip_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = z.namelist()[0]
    with z.open(name) as f:
        df = pd.read_csv(f, low_memory=False)
    return df


def fetch_cot_gold(use_cache: bool = True, history: bool = False) -> pd.DataFrame:
    """Returns weekly COT for Gold dengan kolom turunan: net_mm, net_pct, z_score."""
    if use_cache and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL:
            try:
                return pd.read_parquet(CACHE_FILE)
            except Exception:
                pass

    try:
        try:
            cur = _download_zip_csv(_current_year_url())
        except Exception:
            # Fallback ke tahun sebelumnya kalau tahun ini belum ada (early Jan)
            cur = _download_zip_csv(_prev_year_url())
        if history:
            try:
                prev = _download_zip_csv(_prev_year_url())
                full = pd.concat([prev, cur], ignore_index=True).drop_duplicates()
            except Exception:
                full = cur
        else:
            full = cur
    except Exception as e:
        print(f"[warn] COT fetch failed: {e}")
        return pd.DataFrame()

    code_col = next((c for c in full.columns if "CFTC_Contract_Market_Code" in c or "CFTC Contract Market Code" in c), None)
    if code_col is None:
        return pd.DataFrame()

    full[code_col] = full[code_col].astype(str).str.zfill(6)
    gold = full[full[code_col] == GOLD_CFTC_CODE].copy()

    if gold.empty:
        return pd.DataFrame()

    # Disaggregated cols: Money_Manager_Positions_Long_All, ..._Short_All
    long_col = next((c for c in gold.columns if "Money_Manager_Positions_Long_All" in c.replace(" ", "_")), None)
    short_col = next((c for c in gold.columns if "Money_Manager_Positions_Short_All" in c.replace(" ", "_")), None)
    date_col = next((c for c in gold.columns if "Report_Date_as_YYYY_MM_DD" in c.replace(" ", "_") or "Report_Date_as_MM_DD_YYYY" in c.replace(" ", "_")), None)

    if not (long_col and short_col and date_col):
        return pd.DataFrame()

    gold["date"] = pd.to_datetime(gold[date_col], errors="coerce")
    gold = gold.dropna(subset=["date"]).sort_values("date")
    gold["mm_long"] = pd.to_numeric(gold[long_col], errors="coerce")
    gold["mm_short"] = pd.to_numeric(gold[short_col], errors="coerce")
    gold["net_mm"] = gold["mm_long"] - gold["mm_short"]

    # Rolling z-score (52w) — extreme positioning detector
    gold["net_z52"] = (
        (gold["net_mm"] - gold["net_mm"].rolling(52, min_periods=10).mean())
        / gold["net_mm"].rolling(52, min_periods=10).std()
    )
    gold["net_pct52"] = gold["net_mm"].rolling(52, min_periods=10).apply(
        lambda x: (x.rank(pct=True).iloc[-1]) if len(x) else float("nan")
    )

    out = gold[["date", "mm_long", "mm_short", "net_mm", "net_z52", "net_pct52"]].reset_index(drop=True)

    try:
        out.to_parquet(CACHE_FILE)
    except Exception:
        pass

    return out


def latest_cot_signal() -> dict:
    """Quick signal: -1 (extreme net long → mean revert short bias), +1 (extreme short → long bias), 0 neutral."""
    df = fetch_cot_gold()
    if df.empty:
        return {"signal": 0, "z": None, "note": "COT data unavailable"}
    z = df["net_z52"].iloc[-1]
    if pd.isna(z):
        return {"signal": 0, "z": None, "note": "insufficient history"}
    if z > 1.5:
        return {"signal": -1, "z": float(z), "note": "MM extreme long → mean-revert short bias"}
    if z < -1.5:
        return {"signal": 1, "z": float(z), "note": "MM extreme short → mean-revert long bias"}
    return {"signal": 0, "z": float(z), "note": "no extreme positioning"}


if __name__ == "__main__":
    df = fetch_cot_gold()
    print(f"[ok] COT: {len(df)} weekly rows")
    print(df.tail(3))
    print("Latest signal:", latest_cot_signal())
