"""High-level orchestrator: fetch config from Supabase, run 9-agent pipeline,
return final SignalBundle dict ready for storage.

Drop-in replacement for `signal_engine.generate_signals()` when LLM agents are enabled.
Falls back gracefully to rule_engine if any provider fails or use_llm_agents=False.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional


def _parse_iso(ts: object) -> Optional[datetime]:
    """Parse Supabase ISO timestamp ('2026-05-05T07:23:01.234567+00:00') to
    timezone-aware datetime. Returns None on any parse failure."""
    if not ts:
        return None
    s = str(ts)
    # Python 3.11+ fromisoformat handles 'Z' suffix, earlier versions need stripping
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

from ai_agent.llm_router import LLMRouter
from ai_agent.agents import (
    AgentRunConfig, AGENT_NAMES, AGENT_LABELS,
    run_pipeline, synthesize, SynthResult,
    build_htf_context, build_ltf_context, build_smc_context,
    build_intermarket_context, build_cot_context, build_news_context,
    extract_htf_numeric, extract_ltf_numeric, extract_smc_numeric,
    extract_intermarket_numeric, extract_cot_numeric, extract_news_numeric,
)
from ai_agent.rule_engine import debate as rule_debate, AgentVerdict, DebateResult


# ─── Settings loader (Supabase or env-based) ───────────────────────────────────

class SettingsStore:
    """Reads app_settings, provider_keys, agent_configs from Supabase.

    Falls back to env vars if no Supabase configured. Designed to never throw —
    caller can rely on sensible defaults.
    """

    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        self.url = supabase_url or os.environ.get("SUPABASE_URL")
        self.key = supabase_key or os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
        self._client = None
        if self.url and self.key:
            try:
                from supabase import create_client
                self._client = create_client(self.url, self.key)
            except Exception:
                self._client = None

    @property
    def has_db(self) -> bool:
        return self._client is not None

    # ── App settings ──

    def app_settings(self, user_id: str = "default") -> dict:
        defaults = {
            "user_id": user_id,
            "refresh_interval_minutes": 5,
            "default_llm_provider": os.environ.get("DEFAULT_LLM_PROVIDER", "openrouter"),
            "default_llm_model":    os.environ.get("DEFAULT_LLM_MODEL",    "openai/gpt-oss-20b:free"),
            "use_per_agent_models": False,
            "use_llm_agents":       True,
            "timezone":             "Asia/Jakarta",
            "daemon_active":        True,
            "enable_news_blackout": True,
            "enable_mira_worker":   True,
            "timeframe_focus":      "all",
        }
        if not self._client:
            return defaults
        try:
            r = self._client.from_("app_settings").select("*").eq("user_id", user_id).limit(1).execute()
            rows = r.data or []
            if rows:
                merged = {**defaults, **{k: v for k, v in rows[0].items() if v is not None}}
                return merged
        except Exception:
            pass
        return defaults

    # ── Provider keys ──

    def provider_keys(self, user_id: str = "default") -> dict[str, dict]:
        """Returns {provider: {api_key, base_url, enabled}}."""
        out: dict[str, dict] = {}
        # env fallback first
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic":  "ANTHROPIC_API_KEY",
            "openai":     "OPENAI_API_KEY",
            "groq":       "GROQ_API_KEY",
            "gemini":     "GEMINI_API_KEY",
        }
        for prov, var in env_map.items():
            v = os.environ.get(var)
            if v:
                out[prov] = {"api_key": v, "base_url": None, "enabled": True}

        if not self._client:
            return out
        try:
            r = self._client.from_("provider_keys").select("*").eq("user_id", user_id).execute()
            for row in (r.data or []):
                if row.get("enabled") and row.get("api_key"):
                    out[row["provider"]] = {
                        "api_key": row["api_key"],
                        "base_url": row.get("base_url"),
                        "enabled": True,
                    }
        except Exception:
            pass
        return out

    # ── Agent configs ──

    def agent_configs(self, user_id: str = "default") -> dict[str, AgentRunConfig]:
        """Returns {agent_name: AgentRunConfig}. Missing agents get defaults."""
        cfgs: dict[str, AgentRunConfig] = {n: AgentRunConfig() for n in AGENT_NAMES}
        if not self._client:
            return cfgs
        try:
            r = self._client.from_("agent_configs").select("*").eq("user_id", user_id).execute()
            for row in (r.data or []):
                name = row.get("agent_name")
                if name not in cfgs:
                    continue
                cfgs[name] = AgentRunConfig(
                    enabled=bool(row.get("enabled", True)),
                    provider=row.get("llm_provider"),
                    model=row.get("llm_model"),
                    temperature=float(row.get("temperature", 0.4)),
                    max_tokens=int(row.get("max_tokens", 800)),
                    weight=float(row.get("weight", 1.0)),
                    custom_prompt=row.get("custom_prompt"),
                )
        except Exception:
            pass
        return cfgs

    # ── Daemon heartbeat ──

    def push_heartbeat(self, user_id: str = "default", **fields) -> None:
        """Upsert daemon heartbeat. Multi-PC ready (migration 007):
        on_conflict=(user_id, worker_id) so each worker keeps its own row.
        Falls back to user_id-only on_conflict if migration 007 not yet applied
        (i.e. unique(user_id) constraint still active).
        """
        if not self._client:
            return
        # Migration safety: trigger_reason (005) + worker_id (006) might not be
        # applied yet. On column-missing error, pop the new field and retry.
        payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
        optional_cols = ("trigger_reason", "worker_id")

        def _try_upsert(p: dict, conflict_target: str) -> bool:
            try:
                self._client.from_("daemon_heartbeat").upsert(p, on_conflict=conflict_target).execute()
                return True
            except Exception as exc:
                msg = str(exc).lower()
                # Detect column-missing errors → drop optional fields + retry
                for col in optional_cols:
                    if col in msg and col in p:
                        p.pop(col, None)
                        return _try_upsert(p, conflict_target)
                # If conflict target not supported (migration 007 not applied),
                # fall back to user_id only
                if conflict_target != "user_id" and ("constraint" in msg or "conflict" in msg or "duplicate key" in msg):
                    return _try_upsert(p, "user_id")
                return False

        # Multi-PC default: per-worker row. Fall back to legacy single-row if migration not applied.
        target = "user_id,worker_id" if payload.get("worker_id") else "user_id"
        _try_upsert(payload, target)

    # ── Active worker election (multi-PC active-passive lock, migration 007) ──

    def is_primary_worker(self, user_id: str, worker_id: str,
                          stale_seconds: int = 600) -> tuple[bool, str]:
        """Election: should THIS worker push signal_bundles + open trades?

        Logic:
            active_worker_id NULL                       -> claim, become PRIMARY
            active_worker_id == worker_id               -> we already are PRIMARY
            active_worker_id != worker_id, stale > N    -> failover claim, become PRIMARY
            active_worker_id != worker_id, fresh        -> STANDBY (skip work)

        Returns: (is_primary, reason). reason is human-readable for logging.
        Graceful fallback: kalau migration 007 belum applied OR DB unreachable,
        default to True (assume single-worker mode = always primary).
        """
        if not self._client or not worker_id:
            return True, "no_db_or_no_worker_id_assumed_primary"

        try:
            r = (
                self._client.from_("app_settings")
                .select("active_worker_id, active_claimed_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                # No app_settings row at all → claim
                return self._claim_primary(user_id, worker_id, reason="no_settings_row")
            row = rows[0]
            active = row.get("active_worker_id")
            claimed_at = row.get("active_claimed_at")
        except Exception as e:
            # Migration not applied yet OR DB error → assume primary (single-PC mode)
            msg = str(e).lower()
            if "active_worker_id" in msg or "column" in msg:
                return True, "migration_007_not_applied_assumed_primary"
            return True, f"db_error_assumed_primary ({type(e).__name__})"

        # No primary set → claim
        if not active:
            return self._claim_primary(user_id, worker_id, reason="no_active_worker")

        # I am primary → keep going
        if active == worker_id:
            return True, "already_primary"

        # Other worker is primary. Check if their heartbeat is stale.
        try:
            r = (
                self._client.from_("daemon_heartbeat")
                .select("updated_at")
                .eq("user_id", user_id)
                .eq("worker_id", active)
                .limit(1)
                .execute()
            )
            hb_rows = r.data or []
        except Exception:
            hb_rows = []

        if hb_rows:
            try:
                hb_ts = _parse_iso(hb_rows[0].get("updated_at"))
                if hb_ts is None:
                    return self._claim_primary(user_id, worker_id, reason=f"failover_unparseable_ts_for_{active[:12]}")
                age = (datetime.now(timezone.utc) - hb_ts).total_seconds()
                if age > stale_seconds:
                    return self._claim_primary(
                        user_id, worker_id,
                        reason=f"failover_stale_{int(age)}s_old_primary={active[:12]}",
                    )
            except Exception:
                pass
        else:
            # Primary set but no heartbeat row → likely never started, claim
            return self._claim_primary(
                user_id, worker_id,
                reason=f"failover_no_heartbeat_for_{active[:12]}",
            )

        # Other worker is primary AND fresh → we are STANDBY
        return False, f"standby_primary_is_{active[:12]}"

    def _claim_primary(self, user_id: str, worker_id: str, reason: str) -> tuple[bool, str]:
        """Atomically attempt to claim primary role. Race-tolerant: if another
        worker claimed at same moment, last writer wins (Supabase upsert is atomic
        per row). On column-missing error (migration 007 not applied), assume primary.
        """
        if not self._client:
            return True, "no_db_assumed_primary"
        try:
            self._client.from_("app_settings").update({
                "active_worker_id":  worker_id,
                "active_claimed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
            return True, f"claimed ({reason})"
        except Exception as e:
            msg = str(e).lower()
            if "active_worker_id" in msg or "column" in msg:
                return True, "migration_007_not_applied_assumed_primary"
            return True, f"claim_failed_assumed_primary ({type(e).__name__})"

    # ── Push signal bundle ──

    def push_signal_bundle(self, bundle: dict) -> Optional[str]:
        """Insert a signal_bundles row. Returns the new id or None."""
        if not self._client:
            return None
        try:
            payload = {
                "xau_price":       bundle.get("xau_price"),
                "regime":          bundle.get("regime"),
                "session":         bundle.get("session"),
                "in_news_blackout": bundle.get("in_news_blackout", False),
                "final_action":    (bundle.get("debate") or {}).get("final_action"),
                "signal_strength": (bundle.get("debate") or {}).get("signal_strength"),
                "confidence":      (bundle.get("debate") or {}).get("confidence"),
                "primary_driver":  (bundle.get("debate") or {}).get("primary_driver"),
                "scalper_signal":  bundle.get("scalper"),
                "intraday_signal": bundle.get("intraday"),
                "swing_signal":    bundle.get("swing"),
                "debate":          bundle.get("debate"),
                "intermarket":     bundle.get("intermarket"),
                "cot":             bundle.get("cot"),
                "blackout_event":  bundle.get("blackout_event"),
                "upcoming_events": bundle.get("upcoming_events"),
                "ai_pm_used":      bundle.get("ai_pm_used", False),
                # Opsi B: event-driven momentum trigger reason
                "trigger_reason":  bundle.get("_trigger_reason", "scheduled"),
                # Migration 012: RCS composite snapshot for home/signals RcsPanel
                "rcs":             bundle.get("rcs"),
            }
            # Defensive insert: drop unknown columns one-by-one if any migration
            # is not yet applied. We try all → drop trigger_reason → drop rcs.
            try:
                r = self._client.from_("signal_bundles").insert(payload).execute()
            except Exception as e:
                msg = str(e).lower()
                # Drop rcs column if migration 012 not yet applied
                if "rcs" in msg and ("column" in msg or "schema" in msg or "does not exist" in msg):
                    payload.pop("rcs", None)
                    try:
                        r = self._client.from_("signal_bundles").insert(payload).execute()
                    except Exception as e2:
                        msg2 = str(e2).lower()
                        if "trigger_reason" in msg2 or "column" in msg2:
                            payload.pop("trigger_reason", None)
                            r = self._client.from_("signal_bundles").insert(payload).execute()
                        else:
                            raise
                # Drop trigger_reason if migration 005 not applied
                elif "trigger_reason" in msg or "column" in msg:
                    payload.pop("trigger_reason", None)
                    payload.pop("rcs", None)
                    r = self._client.from_("signal_bundles").insert(payload).execute()
                else:
                    raise
            new_row = (r.data or [{}])[0]
            bundle_id = new_row.get("id")

            # Also insert per-style flat rows in `signals`
            if bundle_id:
                style_rows = []
                for style_key, sig in [("scalper", bundle.get("scalper")),
                                       ("intraday", bundle.get("intraday")),
                                       ("swing", bundle.get("swing"))]:
                    if not sig:
                        continue
                    style_rows.append({
                        "bundle_id":  bundle_id,
                        "style":      style_key,
                        "action":     sig.get("action") or sig.get("side") or "FLAT",
                        "confidence": sig.get("confidence"),
                        "confluence": sig.get("confluence"),
                        "entry":      sig.get("entry"),
                        "sl":         sig.get("sl"),
                        "tp1":        sig.get("tp1"),
                        "tp2":        sig.get("tp2"),
                        "tp3":        sig.get("tp3"),
                        "rr_to_tp1":  sig.get("rr_to_tp1"),
                        "rr_to_tp2":  sig.get("rr_to_tp2"),
                        "regime":     bundle.get("regime"),
                        "session":    bundle.get("session"),
                        "reasons":    sig.get("reasons"),
                        "risks":      sig.get("risks"),
                        "xau_price":  bundle.get("xau_price"),
                    })
                if style_rows:
                    self._client.from_("signals").insert(style_rows).execute()
            return bundle_id
        except Exception as e:
            print(f"[push_signal_bundle] {e}")
            return None


# ─── Public entry point ────────────────────────────────────────────────────────

def run_llm_debate(
    market_ctx: dict,
    settings: dict,
    provider_keys: dict[str, dict],
    agent_configs: dict[str, AgentRunConfig],
    parallel: bool = True,
) -> dict:
    """Run the 9-agent LLM pipeline. Returns dict compatible with DebateResult.to_dict()."""
    router = LLMRouter()
    for prov, cred in provider_keys.items():
        router.set_credential(prov, api_key=cred.get("api_key"), base_url=cred.get("base_url"))

    default_provider = settings.get("default_llm_provider") or "openrouter"
    default_model    = settings.get("default_llm_model")    or "openai/gpt-oss-20b:free"

    # If no creds for default_provider and not local, fall back to rule
    if default_provider not in ("ollama", "lmstudio") and not router.has_credential(default_provider):
        return {"error": "no_credential", "provider": default_provider}

    results = run_pipeline(
        router=router,
        agent_configs=agent_configs,
        market_ctx=market_ctx,
        default_provider=default_provider,
        default_model=default_model,
        parallel=parallel,
    )

    synth = synthesize(
        results=results,
        market_ctx=market_ctx,
        router=router,
        cfg=agent_configs.get("synthesizer", AgentRunConfig()),
        default_provider=default_provider,
        default_model=default_model,
        use_llm=True,
    )

    return {
        "final_action": synth.final_action,
        "confidence":   synth.confidence,
        "signal_strength": synth.signal_strength,
        "primary_driver":  synth.primary_driver,
        "reasoning_chain": synth.reasoning_chain,
        "risks":           synth.risks,
        "agents":          [{"name": v.name, "verdict": v.verdict, "confidence": v.confidence,
                              "reasoning": v.reasoning} for v in results.values()],
        "engine":          "llm-9-agent",
    }


def build_market_context(
    df_15m, df_4h, intermarket: dict, cot: dict, session: str, regime: str,
    in_blackout: bool, blackout_event, upcoming_events: list,
    timeframe_focus: str = "intraday",
    rcs_result: Optional[dict] = None,
) -> dict:
    """Build market context for LLM agents.

    IMPROVEMENT #1 — now includes BOTH:
      - structured numerical dicts (*_numeric) for hallucination-resistant prompts
      - legacy text (*_text) for backward compat + readability

    Both are passed to agents; system prompts instruct them to PREFER JSON over text.

    rcs_result: optional dict from rcs.composite.compute_rcs(...).to_dict() —
      indicator pamungkas yang gabungin semua existing indikator. Disinjeksi ke
      prompts sebagai REFERENCE untuk synthesizer/devil's advocate.
    """
    rcs_numeric = {}
    rcs_text    = "RCS indicator unavailable"
    if rcs_result:
        rcs_numeric = {
            "rcs_score":      rcs_result.get("rcs_score"),
            "direction":      rcs_result.get("direction"),
            "confidence_pct": rcs_result.get("confidence_pct"),
            "top_drivers":    rcs_result.get("top_drivers", [])[:3],
        }
        rcs_text = (
            f"RCS={rcs_result.get('rcs_score', 0):+.3f} "
            f"({rcs_result.get('direction')}, conf {rcs_result.get('confidence_pct')}%) "
            f"drivers: {'; '.join(rcs_result.get('top_drivers', [])[:2])}"
        )

    return {
        "price":     float(df_15m["close"].iloc[-1]) if df_15m is not None and len(df_15m) else 0.0,
        "session":   session,
        "regime":    regime,
        "timeframe_focus": timeframe_focus,
        # Structured numerical (NEW — primary signal)
        "htf_numeric":   extract_htf_numeric(df_4h),
        "ltf_numeric":   extract_ltf_numeric(df_15m, tf_label="M15"),
        "smc_numeric":   extract_smc_numeric(df_15m),
        "inter_numeric": extract_intermarket_numeric(intermarket or {}),
        "cot_numeric":   extract_cot_numeric(cot or {}),
        "news_numeric":  extract_news_numeric(in_blackout, blackout_event, upcoming_events or []),
        # RCS — composite reference indicator (Phase 1 v0.1)
        "rcs_numeric":   rcs_numeric,
        "rcs_text":      rcs_text,
        # Legacy text (back-compat)
        "htf_text":  build_htf_context(df_4h),
        "ltf_text":  build_ltf_context(df_15m),
        "smc_text":  build_smc_context(df_15m),
        "inter_text": build_intermarket_context(intermarket or {}),
        "cot_text":  build_cot_context(cot or {}),
        "news_text": build_news_context(in_blackout, blackout_event, upcoming_events or []),
    }
