"""Mira chatbot job consumer.

Polls `mira_jobs` table where status='pending', calls LLM with the message,
writes the response back. This is a clean, standalone hook — runs as a separate
thread inside the daemon process, no shared state with signal worker.

Designed to coexist with the existing Mira WhatsApp Worker (Node.js) — that
worker handles WA messaging and pushes incoming user messages to mira_jobs.
This Python consumer just answers them.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

from ai_agent.llm_router import LLMRouter, LLMError


SYSTEM_PROMPT_DEFAULT = (
    "You are Mira, a friendly clinic assistant chatbot. Reply concisely in the "
    "same language the user wrote. If the question is outside clinical scope, "
    "politely defer."
)


class MiraConsumer:
    """Polls mira_jobs for pending jobs, processes them with the configured LLM."""

    def __init__(self, store, settings: dict):
        self.store = store
        self.settings = settings
        self.router = LLMRouter()
        self._refresh_credentials()

    def _refresh_credentials(self) -> None:
        """Pull latest provider keys + settings from Supabase."""
        keys = self.store.provider_keys()
        for prov, c in keys.items():
            self.router.set_credential(prov, api_key=c.get("api_key"), base_url=c.get("base_url"))
        self.settings = self.store.app_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enable_mira_worker", True))

    def poll_once(self, max_jobs: int = 5) -> int:
        """Process up to max_jobs pending jobs. Returns number processed."""
        if not self.enabled or not self.store.has_db:
            return 0
        client = self.store._client
        try:
            r = (
                client.from_("mira_jobs")
                .select("*")
                .eq("status", "pending")
                .order("created_at")
                .limit(max_jobs)
                .execute()
            )
            jobs = r.data or []
        except Exception as e:
            print(f"[mira] poll error: {e}")
            return 0

        processed = 0
        for job in jobs:
            self._process(job)
            processed += 1
        return processed

    def _process(self, job: dict) -> None:
        job_id = job.get("id")
        msg = job.get("content") or ""
        meta = job.get("metadata") or {}
        client = self.store._client

        # Mark started
        try:
            client.from_("mira_jobs").update({
                "status": "processing",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).execute()
        except Exception:
            pass

        provider = meta.get("provider") or self.settings.get("default_llm_provider", "openrouter")
        model    = meta.get("model")    or self.settings.get("default_llm_model",    "openai/gpt-oss-20b:free")
        system   = meta.get("system_prompt") or SYSTEM_PROMPT_DEFAULT

        try:
            resp = self.router.chat(
                provider=provider,
                model=model,
                system=system,
                prompt=msg,
                temperature=float(meta.get("temperature", 0.5)),
                max_tokens=int(meta.get("max_tokens", 600)),
            )
            client.from_("mira_jobs").update({
                "status": "done",
                "response": resp.text,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {**meta, "latency_ms": resp.latency_ms,
                             "tokens_in": resp.prompt_tokens,
                             "tokens_out": resp.completion_tokens,
                             "model_used": model},
            }).eq("id", job_id).execute()
        except LLMError as e:
            print(f"[mira] job {job_id} LLM error: {e}")
            client.from_("mira_jobs").update({
                "status": "error",
                "error": str(e)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", job_id).execute()
        except Exception as e:
            print(f"[mira] job {job_id} unexpected: {e}")
            traceback.print_exc()
            try:
                client.from_("mira_jobs").update({
                    "status": "error",
                    "error": f"{type(e).__name__}: {e}"[:500],
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", job_id).execute()
            except Exception:
                pass
