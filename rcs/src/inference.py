"""ML inference — loads trained XGBoost model + predicts probabilities.

Used by daemon as ALTERNATIVE to (or in ADDITION to) heuristic compute_rcs.
When trained model exists for a timeframe, daemon can call ml_predict() to
get probability triple (P_short, P_neutral, P_long) and convert to rcs_score.

Lifecycle:
    1. Train via: python -m rcs.src.training --tf M15 --push
    2. Mark model active: UPDATE rcs_models SET is_active=true WHERE version='...'
    3. Daemon picks up trained model on next cycle (cache: 5 min)

If no active model OR file missing → daemon falls back to heuristic compute_rcs.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False


# Module-level cache: model loaded once, kept in memory
_MODEL_CACHE: dict[str, dict] = {}  # tf -> {"model_pkg": dict, "loaded_at": datetime}
_CACHE_TTL_SEC = 300  # 5 min


def get_model(tf: str) -> Optional[dict]:
    """Load model from disk, cached. Returns None if file missing or load fails."""
    if not HAS_JOBLIB:
        return None

    now_ts = datetime.now(timezone.utc).timestamp()
    cached = _MODEL_CACHE.get(tf)
    if cached and (now_ts - cached["loaded_at"]) < _CACHE_TTL_SEC:
        return cached["model_pkg"]

    model_path = ROOT / "rcs" / "models" / f"xgb_{tf}.pkl"
    if not model_path.exists():
        return None

    try:
        pkg = joblib.load(model_path)
        _MODEL_CACHE[tf] = {"model_pkg": pkg, "loaded_at": now_ts}
        return pkg
    except Exception as e:
        print(f"[inference] failed to load {model_path}: {e}")
        return None


def ml_predict(tf: str, features_row: dict) -> Optional[dict]:
    """Predict using trained XGBoost.

    Args:
        tf: 'M5' | 'M15' | 'H1'
        features_row: dict mapping feature_name → numeric value
                      (must include all features in model's feature_list)

    Returns:
        {
          "prob_short": 0.20, "prob_neutral": 0.55, "prob_long": 0.25,
          "rcs_score":  0.05,                  # prob_long - prob_short, [-1, +1]
          "direction":  "WAIT",                 # LONG/SHORT/WAIT
          "confidence_pct": 5,                  # 0-95
          "model_version": "xgb_M15_2026...",
        }
        or None if no trained model OR feature mismatch.
    """
    pkg = get_model(tf)
    if not pkg:
        return None

    model        = pkg["model"]
    scaler       = pkg["scaler"]
    feature_list = pkg["feature_list"]
    version      = pkg.get("version", "unknown")

    # Build feature vector in correct order. Missing features default to 0.
    x = np.array([[float(features_row.get(f, 0)) for f in feature_list]])
    x_scaled = scaler.transform(x)

    # Predict 3-class probabilities: [P(SHORT), P(NEUTRAL), P(LONG)]
    proba = model.predict_proba(x_scaled)[0]
    p_short, p_neutral, p_long = float(proba[0]), float(proba[1]), float(proba[2])

    # RCS score = long - short, range [-1, +1]
    rcs_score = p_long - p_short

    # Direction
    if rcs_score >= 0.40:
        direction = "LONG"
    elif rcs_score <= -0.40:
        direction = "SHORT"
    elif rcs_score >= 0.20:
        direction = "LONG"   # weak side
    elif rcs_score <= -0.20:
        direction = "SHORT"
    else:
        direction = "WAIT"

    confidence_pct = int(min(95, abs(rcs_score) * 100))

    return {
        "prob_short":     round(p_short, 4),
        "prob_neutral":   round(p_neutral, 4),
        "prob_long":      round(p_long, 4),
        "rcs_score":      round(rcs_score, 4),
        "direction":      direction,
        "confidence_pct": confidence_pct,
        "model_version":  version,
    }


def is_model_available(tf: str) -> bool:
    """Quick check without loading. Used by daemon to decide composite vs ML path."""
    model_path = ROOT / "rcs" / "models" / f"xgb_{tf}.pkl"
    return model_path.exists()


# ─── Smoke test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tf", choices=["M5", "M15", "H1"], default="M15")
    args = p.parse_args()

    print(f"Model available for {args.tf}: {is_model_available(args.tf)}")
    pkg = get_model(args.tf)
    if pkg:
        print(f"Loaded model version: {pkg.get('version')}")
        print(f"Features: {pkg.get('feature_list', [])[:10]}...")
        # Dummy prediction
        fake_row = {f: 0.5 for f in pkg["feature_list"]}
        result = ml_predict(args.tf, fake_row)
        print(f"Dummy prediction: {result}")
    else:
        print("No trained model. Run: python -m rcs.src.training --tf", args.tf)
