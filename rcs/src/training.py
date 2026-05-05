"""ML training pipeline for RCS v0.2 — XGBoost on yfinance historical XAU.

Pragmatic approach:
    - Fetch 1+ year XAU OHLCV via existing data.price_fetcher (no MT5 needed)
    - Use existing features.technical + features.smc (already battle-tested)
    - Triple barrier label per timeframe params from rcs/config.yaml
    - 70/30 train/holdout split with TIME-ORDERED split (oldest 70% train, newest 30% holdout — NO shuffle)
    - Train logistic regression baseline first (sanity check)
    - Train XGBoost classifier (3-class: short/neutral/long)
    - Save .pkl + metadata to rcs/models/
    - Insert metrics to rcs_models table

Run:
    cd D:\\dextrade\\rcs
    python -m rcs.src.training --tf M15

Output:
    rcs/models/xgb_M15.pkl
    rcs/models/metadata_M15.json
    Insert row to rcs_models table
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Resolve project root (yeehee monorepo)
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.price_fetcher import fetch_xau
from features.technical import add_all as add_technical
from features.smc       import add_all_smc
from rcs.src.labeling   import triple_barrier_labels, label_distribution

# ML imports (gracefully fallback if missing)
try:
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import classification_report, log_loss, accuracy_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


# ─── Config ─────────────────────────────────────────────────────────────────────

# Triple barrier params per TF (mirror rcs/config.yaml.labeling)
LABELING_PARAMS = {
    "M5":  {"k_tp": 1.5, "k_sl": 1.0, "max_hold": 24},
    "M15": {"k_tp": 2.0, "k_sl": 1.5, "max_hold": 32},
    "H1":  {"k_tp": 2.5, "k_sl": 2.0, "max_hold": 48},
}

# Map yeehee timeframe → yfinance interval
TF_TO_INTERVAL = {
    "M5":  "5m",
    "M15": "15m",
    "H1":  "1h",
}

# Period to fetch (yfinance limits)
TF_TO_PERIOD = {
    "M5":  "60d",   # ~17000 candles, OK for training
    "M15": "60d",   # ~5800 candles
    "H1":  "180d",  # ~3000 candles
}

# Feature columns to use (from existing features.technical.add_all)
FEATURE_COLS = [
    "ema9", "ema21", "ema50", "ema200",
    "rsi14",
    "macd", "signal", "hist",     # MACD components
    "atr14",
    "adx", "plus_di", "minus_di",
    "bb_mid", "bb_up", "bb_low", "bb_width", "bb_pctb",
    "stoch_k", "stoch_d",
]

# Derived features computed before training
DERIVED_FEATURE_FN = "_compute_derived_features"


def _compute_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features that aren't in technical.add_all."""
    out = df.copy()

    # EMA spread features (normalized by close)
    out["ema_20_50_diff_pct"]  = (out["ema21"] - out["ema50"])  / out["close"] * 100
    out["ema_50_200_diff_pct"] = (out["ema50"] - out["ema200"]) / out["close"] * 100
    out["price_vs_ema_200"]    = (out["close"] - out["ema200"]) / out["ema200"] * 100

    # Returns at multiple lags
    for lag in (1, 3, 5, 10):
        out[f"ret_{lag}"] = out["close"].pct_change(lag)

    # RSI slope (now - 5 bars ago)
    out["rsi_slope_5"] = out["rsi14"] - out["rsi14"].shift(5)

    # MACD hist slope
    out["macd_hist_slope_3"] = out["hist"] - out["hist"].shift(3)

    # ATR percentile (rolling 100)
    atr_rank = out["atr14"].rolling(100, min_periods=20).rank(pct=True)
    out["atr_pct_rank"] = atr_rank

    # SMC boolean flags (already added by add_all_smc)
    for col in ("bull_sweep", "bear_sweep", "fvg_bull", "fvg_bear", "bos_up", "bos_dn"):
        if col in out.columns:
            out[col] = out[col].astype(int)
        else:
            out[col] = 0

    return out


def _expanded_feature_list() -> list[str]:
    """Final feature list = base technical + derived."""
    derived = [
        "ema_20_50_diff_pct", "ema_50_200_diff_pct", "price_vs_ema_200",
        "ret_1", "ret_3", "ret_5", "ret_10",
        "rsi_slope_5", "macd_hist_slope_3", "atr_pct_rank",
        "bull_sweep", "bear_sweep", "fvg_bull", "fvg_bear", "bos_up", "bos_dn",
    ]
    return FEATURE_COLS + derived


# ─── Pipeline ───────────────────────────────────────────────────────────────────

def fetch_and_prepare(tf: str, source: str = "yfinance", n_candles: int = 100000, log=print) -> pd.DataFrame:
    """Fetch OHLCV + compute all features. Returns DataFrame ready for labeling.

    Args:
        tf: 'M5' | 'M15' | 'H1'
        source: 'yfinance' (default, ~60-180 days) or 'mt5' (3+ years if MT5 history allows).
                MT5 source needs MT5_LOGIN/PASSWORD/SERVER in env.
        n_candles: max candles when source='mt5' (default 100k).
    """
    if source == "mt5":
        log(f"[train] fetching XAU {tf} via MT5 (n={n_candles})...")
        try:
            from rcs.src.mt5_connector import MT5Connector, MT5ConnectionError
            conn = MT5Connector()
            conn.connect()  # uses env credentials
            df = conn.fetch_candles(tf, n_candles=n_candles)
            conn.shutdown()
            log(f"[train] fetched {len(df)} candles from MT5")
        except (ImportError, MT5ConnectionError) as e:
            log(f"[train] MT5 unavailable ({e}), falling back to yfinance")
            source = "yfinance"

    if source == "yfinance":
        interval = TF_TO_INTERVAL[tf]
        period   = TF_TO_PERIOD[tf]
        log(f"[train] fetching XAU {interval} period={period} via yfinance...")
        df = fetch_xau(interval=interval, period=period)
        log(f"[train] fetched {len(df)} candles")

    log("[train] computing features (technical + SMC)...")
    df = add_technical(df)
    df = add_all_smc(df)
    df = _compute_derived_features(df)
    df = df.dropna(subset=["atr14", "ema200", "rsi14"])  # warmup period
    log(f"[train] post-warmup: {len(df)} usable rows")
    return df


def add_cross_tf_features(df_main: pd.DataFrame, df_higher: pd.DataFrame, prefix: str = "h1") -> pd.DataFrame:
    """Merge higher-TF features into main TF dataframe via timestamp asof.

    For each row in df_main, finds the most recent df_higher row at-or-before.
    Adds columns: {prefix}_ema21_50_diff_pct, {prefix}_rsi14, {prefix}_adx, {prefix}_atr_pct_rank.
    """
    if df_main is None or df_higher is None or len(df_higher) == 0:
        return df_main

    # Pick subset of features from higher TF
    higher_cols = [c for c in ["ema21", "ema50", "ema200", "rsi14", "adx", "atr14", "ema_50_200_diff_pct"]
                   if c in df_higher.columns]
    higher = df_higher[higher_cols].copy()
    higher = higher.add_prefix(f"{prefix}_")

    # asof merge (each main row gets most-recent higher row at-or-before)
    out = pd.merge_asof(
        df_main.sort_index(),
        higher.sort_index(),
        left_index=True, right_index=True,
        direction="backward",
    )
    return out


def label_dataset(df: pd.DataFrame, tf: str, log=print) -> tuple[pd.DataFrame, np.ndarray]:
    """Apply triple barrier labels."""
    params = LABELING_PARAMS[tf]
    log(f"[train] labeling with k_tp={params['k_tp']} k_sl={params['k_sl']} max_hold={params['max_hold']}")
    labels = triple_barrier_labels(df, **params, atr_col="atr14")
    dist = label_distribution(labels)
    log(f"[train] label distribution: {dist}")
    # Convert -1/0/+1 to 0/1/2 for sklearn (3-class)
    y = (labels + 1).astype(int)  # -1 -> 0 (SHORT), 0 -> 1 (NEUTRAL), 1 -> 2 (LONG)
    # Drop last `max_hold` rows (incomplete lookahead = label=0 unreliable)
    valid_end = len(df) - params["max_hold"]
    return df.iloc[:valid_end], y[:valid_end]


def train_models(tf: str, source: str = "yfinance", use_optuna: bool = False,
                 n_optuna_trials: int = 30, n_candles: int = 100000, log=print) -> dict:
    """Full pipeline: fetch → label → split → train baseline + XGB → save → metrics dict.

    Args:
        tf: target timeframe to train ('M5'/'M15'/'H1')
        source: 'yfinance' (60-180 days) or 'mt5' (3+ years if available)
        use_optuna: if True, run hyperparameter search before final fit
        n_optuna_trials: Optuna search budget (default 30, try 50-100 for serious training)
        n_candles: MT5 source max candles
    """
    if not HAS_SKLEARN:
        return {"error": "scikit-learn not installed. pip install scikit-learn joblib"}
    if not HAS_XGB:
        return {"error": "xgboost not installed. pip install xgboost"}

    started = time.time()
    df = fetch_and_prepare(tf, source=source, n_candles=n_candles, log=log)

    # Add cross-TF features (M15 main + H1 higher OR H1 main + D1 higher)
    if tf == "M15":
        try:
            log("[train] fetching H1 for cross-TF features...")
            df_h1 = fetch_and_prepare("H1", source=source, n_candles=n_candles, log=log)
            df = add_cross_tf_features(df, df_h1, prefix="h1")
            log("[train] cross-TF features added (h1_*)")
        except Exception as e:
            log(f"[train] cross-TF skipped: {e}")
    elif tf == "M5":
        try:
            log("[train] fetching M15 for cross-TF features...")
            df_m15 = fetch_and_prepare("M15", source=source, n_candles=n_candles, log=log)
            df = add_cross_tf_features(df, df_m15, prefix="m15")
        except Exception as e:
            log(f"[train] cross-TF skipped: {e}")

    df, y = label_dataset(df, tf, log=log)

    # Build feature list including cross-TF columns now in df
    feature_list = _expanded_feature_list()
    cross_tf_cols = [c for c in df.columns if c.startswith("h1_") or c.startswith("m15_")]
    feature_list = feature_list + cross_tf_cols

    available    = [c for c in feature_list if c in df.columns]
    missing      = [c for c in feature_list if c not in df.columns]
    if missing:
        log(f"[train] WARNING: missing features {missing[:10]}{'...' if len(missing) > 10 else ''}")

    X = df[available].fillna(0).astype(float).values
    log(f"[train] X shape: {X.shape}, y shape: {y.shape}")

    # 70/30 time-ordered split (NO shuffle — preserve time series structure)
    split = int(len(X) * 0.70)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    log(f"[train] split: train={len(X_train)} test={len(X_test)}")

    # Standardize (fit on train only)
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # ── Baseline: Logistic Regression ─────────────────────────────────────────
    # Note: sklearn 1.5+ deprecated multi_class param (auto-detected from y)
    log("[train] training LogReg baseline...")
    lr = LogisticRegression(max_iter=1000, solver="lbfgs",
                            class_weight="balanced", random_state=42)
    lr.fit(X_train_s, y_train)
    lr_acc = accuracy_score(y_test, lr.predict(X_test_s))
    lr_loss = log_loss(y_test, lr.predict_proba(X_test_s), labels=[0, 1, 2])
    log(f"[train] LogReg OOS accuracy={lr_acc:.4f}, log_loss={lr_loss:.4f}")

    # ── XGBoost dengan class balancing ─────────────────────────────────────────
    # IMPORTANT (v0.2.1): handle class imbalance. Tanpa ini, model bias ke
    # majority class (e.g. SHORT pas data bearish), precision LONG jelek.
    # Compute sample_weight inversely proportional to class frequency.
    from sklearn.utils.class_weight import compute_sample_weight
    sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)

    # Default hyperparams (used when not running Optuna)
    best_params = dict(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
    )

    if use_optuna:
        try:
            import optuna
            from sklearn.model_selection import TimeSeriesSplit

            log(f"[train] Optuna hyperparam search ({n_optuna_trials} trials)...")
            optuna.logging.set_verbosity(optuna.logging.WARNING)

            def objective(trial):
                params = {
                    "n_estimators":     trial.suggest_int("n_estimators", 100, 500),
                    "max_depth":        trial.suggest_int("max_depth", 3, 8),
                    "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                    "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
                    "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
                    "reg_alpha":        trial.suggest_float("reg_alpha", 0.0, 1.0),
                    "reg_lambda":       trial.suggest_float("reg_lambda", 0.5, 2.0),
                    "objective":        "multi:softprob",
                    "num_class":        3,
                    "eval_metric":      "mlogloss",
                    "random_state":     42,
                }
                # Walk-forward CV using TimeSeriesSplit (3 folds)
                tscv = TimeSeriesSplit(n_splits=3)
                scores = []
                for fold_train, fold_val in tscv.split(X_train_s):
                    m = XGBClassifier(**params)
                    sw = compute_sample_weight(class_weight="balanced", y=y_train[fold_train])
                    m.fit(X_train_s[fold_train], y_train[fold_train], sample_weight=sw)
                    pred = m.predict(X_train_s[fold_val])
                    scores.append(accuracy_score(y_train[fold_val], pred))
                return float(np.mean(scores))

            study = optuna.create_study(direction="maximize")
            study.optimize(objective, n_trials=n_optuna_trials, show_progress_bar=False)
            best_params.update(study.best_params)
            log(f"[train] Optuna best params: {study.best_params}")
            log(f"[train] Optuna best CV accuracy: {study.best_value:.4f}")
        except ImportError:
            log("[train] Optuna not installed (pip install optuna), using default params")
        except Exception as e:
            log(f"[train] Optuna error (using defaults): {e}")

    log("[train] training XGBoost (class-balanced via sample_weight)...")
    xgb = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        random_state=42,
        **best_params,
    )
    xgb.fit(X_train_s, y_train, sample_weight=sample_weights)
    xgb_pred  = xgb.predict(X_test_s)
    xgb_proba = xgb.predict_proba(X_test_s)
    xgb_acc   = accuracy_score(y_test, xgb_pred)
    xgb_loss  = log_loss(y_test, xgb_proba, labels=[0, 1, 2])
    log(f"[train] XGB OOS accuracy={xgb_acc:.4f}, log_loss={xgb_loss:.4f}")

    # Per-class precision/recall
    report = classification_report(y_test, xgb_pred, target_names=["SHORT", "NEUTRAL", "LONG"], output_dict=True, zero_division=0)
    log(f"[train] XGB per-class precision: SHORT={report['SHORT']['precision']:.3f} LONG={report['LONG']['precision']:.3f}")

    # ── Save model + metadata ────────────────────────────────────────────────
    models_dir = ROOT / "rcs" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    version = f"xgb_{tf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    model_path = models_dir / f"xgb_{tf}.pkl"

    joblib.dump({
        "model":         xgb,
        "scaler":        scaler,
        "feature_list":  available,
        "version":       version,
        "trained_at":    datetime.now(timezone.utc).isoformat(),
    }, model_path)
    log(f"[train] saved model to {model_path}")

    metadata = {
        "version":              version,
        "timeframe":            tf,
        "model_type":           "xgboost_multiclass",
        "trained_at":           datetime.now(timezone.utc).isoformat(),
        "training_window_start": str(df.index[0])[:10] if len(df) else None,
        "training_window_end":   str(df.index[-1])[:10] if len(df) else None,
        "num_features":         len(available),
        "feature_list":         available,
        "train_size":           int(len(X_train)),
        "test_size":            int(len(X_test)),
        "metrics": {
            "logreg_oos_accuracy": round(lr_acc, 4),
            "logreg_oos_log_loss": round(lr_loss, 4),
            "xgb_oos_accuracy":    round(xgb_acc, 4),
            "xgb_oos_log_loss":    round(xgb_loss, 4),
            "xgb_precision_long":  round(report["LONG"]["precision"], 4),
            "xgb_precision_short": round(report["SHORT"]["precision"], 4),
            "xgb_recall_long":     round(report["LONG"]["recall"], 4),
            "xgb_recall_short":    round(report["SHORT"]["recall"], 4),
            "xgb_f1_macro":        round(report["macro avg"]["f1-score"], 4),
        },
        "elapsed_sec": round(time.time() - started, 1),
    }

    metadata_path = models_dir / f"metadata_{tf}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log(f"[train] saved metadata to {metadata_path}")

    # Save reference distribution for drift detection (Phase v0.3)
    try:
        from rcs.src.drift_detector import save_reference_distribution
        save_reference_distribution(df.iloc[:split], available, tf)
        log(f"[train] saved reference distribution to rcs/models/reference_dist_{tf}.json")
    except Exception as e:
        log(f"[train] drift reference save failed (non-fatal): {e}")

    return metadata


def push_metadata_to_supabase(metadata: dict, log=print) -> Optional[int]:
    """Insert training metadata to rcs_models table."""
    try:
        from ai_agent.orchestrator import SettingsStore
        store = SettingsStore()
        if not store.has_db:
            log("[train] no DB — skip rcs_models insert")
            return None

        m = metadata.get("metrics", {})
        payload = {
            "version":               metadata["version"],
            "timeframe":             metadata["timeframe"],
            "model_type":            metadata["model_type"],
            "trained_at":            metadata["trained_at"],
            "training_window_start": metadata.get("training_window_start"),
            "training_window_end":   metadata.get("training_window_end"),
            "oos_accuracy":          m.get("xgb_oos_accuracy"),
            "oos_precision_long":    m.get("xgb_precision_long"),
            "oos_precision_short":   m.get("xgb_precision_short"),
            "oos_recall_long":       m.get("xgb_recall_long"),
            "oos_recall_short":      m.get("xgb_recall_short"),
            "oos_f1_macro":          m.get("xgb_f1_macro"),
            "oos_log_loss":          m.get("xgb_oos_log_loss"),
            "num_features":          metadata.get("num_features"),
            "storage_path":          f"rcs/models/xgb_{metadata['timeframe']}.pkl",
            "feature_list":          metadata.get("feature_list", []),
            "is_active":             False,   # user manually flips after review
            "notes":                 f"trained in {metadata.get('elapsed_sec', '?')}s",
        }
        r = store._client.from_("rcs_models").insert(payload).execute()
        new_id = (r.data or [{}])[0].get("id")
        log(f"[train] pushed metadata to rcs_models id={new_id}")
        return new_id
    except Exception as e:
        log(f"[train] DB push failed: {e}")
        return None


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="RCS ML training pipeline")
    p.add_argument("--tf", choices=["M5", "M15", "H1"], default="M15", help="Timeframe to train")
    p.add_argument("--source", choices=["yfinance", "mt5"], default="yfinance",
                   help="Data source: yfinance (60-180d) or mt5 (3+ years if MT5 history allows)")
    p.add_argument("--n-candles", type=int, default=100000,
                   help="Max candles when source=mt5 (default 100k)")
    p.add_argument("--optuna", action="store_true",
                   help="Run Optuna hyperparameter search (recommended for serious training)")
    p.add_argument("--trials", type=int, default=30,
                   help="Optuna trial budget (default 30; try 50-100 for thorough search)")
    p.add_argument("--push", action="store_true",
                   help="Push metadata to rcs_models Supabase table")
    args = p.parse_args()

    try:
        metadata = train_models(
            args.tf,
            source=args.source,
            use_optuna=args.optuna,
            n_optuna_trials=args.trials,
            n_candles=args.n_candles,
            log=print,
        )
        if "error" in metadata:
            print(f"FAIL: {metadata['error']}")
            sys.exit(1)
        print()
        print("=== TRAINING COMPLETE ===")
        print(json.dumps(metadata, indent=2))

        if args.push:
            push_metadata_to_supabase(metadata)
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
