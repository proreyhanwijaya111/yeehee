"""RCS — REY Composite Signal (Multi-TF ML pipeline).

This package is OPTIONAL — daemon-utama (yeehee) jalan tanpa RCS. Kalau MT5 +
trained models tersedia, RCS daemon push prediksi tambahan ke rcs_signals
table sebagai REFERENCE indikator buat sistem 12-agent LLM.

Module overview:
    mt5_connector.py     — wrapper MetaTrader5 lib (graceful fallback ke MOCK
                            kalau lib ga ke-install / non-Windows)
    data_ingestion.py    — fetch + cache OHLCV ke parquet
    feature_engineering.py — 48 features per TF + 8 cross-TF
    labeling.py          — triple barrier (López de Prado) untuk training
    cross_validation.py  — Purged K-Fold dengan embargo
    training.py          — XGBoost + Optuna hyperparam search
    evaluation.py        — directional accuracy, calibration, SHAP
    inference.py         — load model + predict per timeframe
    daemon.py            — inference loop, push ke rcs_signals
    execution_api.py     — FastAPI endpoint buat EA polling (Phase 10)

Workflow:
    1. Setup: python -m rcs.src.data_ingestion       # fetch 3-tahun history
    2. Feature: python -m rcs.src.feature_engineering # compute features
    3. Label:   python -m rcs.src.labeling           # triple barrier
    4. Train:   python -m rcs.src.training           # XGBoost + Optuna
    5. Eval:    python -m rcs.src.evaluation        # validation metrics
    6. Run:     python -m rcs.src.daemon            # live inference loop

For status of each phase implementation, see rcs/README.md.
"""
__version__ = "0.1.0-scaffold"
