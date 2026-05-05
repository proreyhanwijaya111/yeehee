"""RCS — REY Composite Signal package.

Lightweight indicator that combines existing yeehee features (technical, SMC,
intermarket, regime, session) into single composite score. Reference for the
12-agent LLM pipeline; not a replacement.

Public API:
    from rcs.composite import compute_rcs, RCSResult
    from rcs.persistence import push_rcs_signal, get_latest_rcs

Phase 2 (future): ML enhancement (XGBoost on RCS features → outcome).
Phase 3 (future): MT5 EA bot for auto-execute based on RCS direction.
"""
__version__ = "0.1.0"

from rcs.composite import compute_rcs, RCSResult, ComponentScore  # noqa: F401
