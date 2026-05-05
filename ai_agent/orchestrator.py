"""High-level orchestrator: fetch config from Supabase, run 9-agent pipeline,
return final SignalBundle dict ready for storage.

Drop-in replacement for `signal_engine.generate_signals()` when LLM agents are enabled.
Falls back gracefully to rule_engine if any provider fails or use_llm_agents=False.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

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
        if not self._client:
            return
        # Opsi B: trigger_reason field requires migration 005. Retry without if missing.
        payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}
        try:
            self._client.from_("daemon_heartbeat").upsert(payload, on_conflict="user_id").execute()
        except Exception as e:
            if "trigger_reason" in str(e).lower() or "column" in str(e).lower():
                payload.pop("trigger_reason", None)
                try:
                    self._client.from_("daemon_heartbeat").upsert(payload, on_conflict="user_id").execute()
                except Exception:
                    pass

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
            }
            try:
                r = self._client.from_("signal_bundles").insert(payload).execute()
            except Exception as e:
                # Graceful: if migration 005 not applied, retry without trigger_reason
                if "trigger_reason" in str(e).lower() or "column" in str(e).lower():
                    payload.pop("trigger_reason", None)
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
) -> dict:
    """Build market context for LLM agents.

    IMPROVEMENT #1 — now includes BOTH:
      - structured numerical dicts (*_numeric) for hallucination-resistant prompts
      - legacy text (*_text) for backward compat + readability

    Both are passed to agents; system prompts instruct them to PREFER JSON over text.
    """
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
        # Legacy text (back-compat)
        "htf_text":  build_htf_context(df_4h),
        "ltf_text":  build_ltf_context(df_15m),
        "smc_text":  build_smc_context(df_15m),
        "inter_text": build_intermarket_context(intermarket or {}),
        "cot_text":  build_cot_context(cot or {}),
        "news_text": build_news_context(in_blackout, blackout_event, upcoming_events or []),
    }
