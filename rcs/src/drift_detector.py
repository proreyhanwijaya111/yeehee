"""Drift detection — compare live feature distribution vs training set.

Concept (population stability index / KL divergence):
    Models train on a snapshot of market behavior. As market regime evolves,
    feature distributions shift. When live features look statistically
    different from training, model predictions become unreliable.

Implementation:
    1. At training time: save histogram (bins + frequencies) per feature.
    2. At inference time: compute live histogram from last N candles.
    3. Compute Population Stability Index (PSI) per feature.
    4. Aggregate to single drift score.

PSI thresholds (industry standard):
    < 0.1   = no significant change
    0.1-0.25 = minor drift, worth watching
    > 0.25  = significant drift, retrain recommended

Usage in daemon:
    Run check_drift() every cycle; if score > 0.25, log warning + push to
    rcs_drift_history table. UI can show drift indicator on /more/rcs-monitor.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent

# Drift thresholds (PSI conventions)
DRIFT_THRESHOLD_MINOR    = 0.10
DRIFT_THRESHOLD_MODERATE = 0.25
DRIFT_THRESHOLD_SEVERE   = 0.50


def compute_psi(reference: np.ndarray, live: np.ndarray, n_bins: int = 10) -> float:
    """Population Stability Index. PSI ≈ KL divergence (symmetric variant).

    PSI = sum( (P_live - P_ref) * ln(P_live / P_ref) )

    Bins are quantile-based on reference distribution to handle skewed features.
    Empty bins get small epsilon to avoid log(0).
    """
    if reference is None or len(reference) == 0:
        return 0.0
    if live is None or len(live) == 0:
        return 0.0

    # Filter NaN
    ref = pd.Series(reference).dropna().values
    liv = pd.Series(live).dropna().values
    if len(ref) < 10 or len(liv) < 5:
        return 0.0

    # Quantile-based binning from reference distribution
    quantiles = np.linspace(0, 1, n_bins + 1)
    bin_edges = np.unique(np.quantile(ref, quantiles))
    if len(bin_edges) < 3:
        return 0.0  # all same value, no useful bins

    # Histogram counts
    ref_counts, _ = np.histogram(ref, bins=bin_edges)
    liv_counts, _ = np.histogram(liv, bins=bin_edges)

    # Convert to probabilities + add epsilon to empty bins
    eps = 1e-6
    ref_pct = ref_counts / max(1, ref_counts.sum())
    liv_pct = liv_counts / max(1, liv_counts.sum())
    ref_pct = np.where(ref_pct == 0, eps, ref_pct)
    liv_pct = np.where(liv_pct == 0, eps, liv_pct)

    psi = float(np.sum((liv_pct - ref_pct) * np.log(liv_pct / ref_pct)))
    return psi


def compute_drift(
    feature_list: list[str],
    reference_df: pd.DataFrame,
    live_df: pd.DataFrame,
) -> dict:
    """Compute PSI per feature + aggregate score.

    Returns:
        {
          "score": 0.18,                                   # average PSI
          "max_score": 0.42,                                # worst feature
          "level": "minor"|"moderate"|"severe"|"none",
          "per_feature": {"rsi14": 0.05, "atr14": 0.42, ...},
          "drifted_features": ["atr14", "ema21"],          # > MODERATE
          "n_features_checked": 18,
          "computed_at": "2026-...",
        }
    """
    per_feat = {}
    for feat in feature_list:
        if feat not in reference_df.columns or feat not in live_df.columns:
            continue
        psi = compute_psi(reference_df[feat].values, live_df[feat].values)
        per_feat[feat] = round(psi, 4)

    if not per_feat:
        return {"score": 0.0, "level": "none", "per_feature": {}, "n_features_checked": 0}

    scores = list(per_feat.values())
    avg = float(np.mean(scores))
    mx  = float(np.max(scores))

    if mx > DRIFT_THRESHOLD_SEVERE:
        level = "severe"
    elif mx > DRIFT_THRESHOLD_MODERATE:
        level = "moderate"
    elif mx > DRIFT_THRESHOLD_MINOR:
        level = "minor"
    else:
        level = "none"

    drifted = [f for f, s in per_feat.items() if s > DRIFT_THRESHOLD_MODERATE]
    return {
        "score":              round(avg, 4),
        "max_score":          round(mx, 4),
        "level":              level,
        "per_feature":        per_feat,
        "drifted_features":   drifted,
        "n_features_checked": len(per_feat),
        "computed_at":        datetime.now(timezone.utc).isoformat(),
    }


def save_reference_distribution(df: pd.DataFrame, feature_list: list[str], tf: str) -> None:
    """Save reference (training) feature distribution snapshot for later drift check.

    Stored as JSON: {feature: {min, max, q05, q25, q50, q75, q95, mean, std}}
    Compact, doesn't bloat repo.
    """
    snapshot = {}
    for feat in feature_list:
        if feat not in df.columns:
            continue
        s = df[feat].dropna()
        if len(s) < 10:
            continue
        snapshot[feat] = {
            "min":  float(s.min()),
            "max":  float(s.max()),
            "q05":  float(s.quantile(0.05)),
            "q25":  float(s.quantile(0.25)),
            "q50":  float(s.quantile(0.50)),
            "q75":  float(s.quantile(0.75)),
            "q95":  float(s.quantile(0.95)),
            "mean": float(s.mean()),
            "std":  float(s.std()),
        }

    out_path = ROOT / "rcs" / "models" / f"reference_dist_{tf}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "tf": tf,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": len(df),
        "features": snapshot,
    }, indent=2), encoding="utf-8")


def load_reference_distribution(tf: str) -> Optional[dict]:
    """Load saved reference distribution. Returns None if not yet saved."""
    path = ROOT / "rcs" / "models" / f"reference_dist_{tf}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def quick_drift_check(live_df: pd.DataFrame, tf: str = "M15") -> Optional[dict]:
    """Lightweight drift check using saved reference quantiles.

    For each feature:
      - Compute live mean, q25, q75
      - Compare vs reference q25-q75 range
      - Score: how far live mean is OUTSIDE reference IQR (in IQR units)

    Returns None if no reference saved yet.
    """
    ref = load_reference_distribution(tf)
    if not ref:
        return None
    features = ref.get("features", {})
    if not features:
        return None

    drifts = {}
    for feat, ref_stats in features.items():
        if feat not in live_df.columns:
            continue
        live_vals = live_df[feat].dropna()
        if len(live_vals) < 5:
            continue
        live_mean = float(live_vals.mean())
        ref_q25 = ref_stats["q25"]
        ref_q75 = ref_stats["q75"]
        ref_iqr = max(1e-6, ref_q75 - ref_q25)
        ref_mid = (ref_q25 + ref_q75) / 2

        # How many IQR widths is live_mean from reference midpoint?
        z = abs(live_mean - ref_mid) / ref_iqr
        drifts[feat] = round(z, 3)

    if not drifts:
        return {"score": 0, "level": "none", "per_feature": {}}

    scores = list(drifts.values())
    mx = float(np.max(scores))
    avg = float(np.mean(scores))
    if mx > 3.0:
        level = "severe"
    elif mx > 2.0:
        level = "moderate"
    elif mx > 1.0:
        level = "minor"
    else:
        level = "none"

    return {
        "score":     round(avg, 3),
        "max_score": round(mx, 3),
        "level":     level,
        "per_feature": drifts,
        "n_features_checked": len(drifts),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "reference_saved_at": ref.get("saved_at"),
        "method": "iqr_zscore",
    }
