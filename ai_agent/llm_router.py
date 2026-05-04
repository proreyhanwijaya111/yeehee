"""Provider-agnostic LLM client.

Supports: OpenRouter, Anthropic, OpenAI, Groq, Google Gemini, Ollama (any OpenAI-compat).
Single interface: LLMRouter().chat(provider, model, system, prompt, temperature, max_tokens)

All requests go through `httpx` directly (no SDK lock-in). Each provider has its own
endpoint normaliser so the caller does not care.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# ── Provider Catalog ────────────────────────────────────────────────────────────

PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "format": "openai",   # OpenAI-compatible chat completions
        "auth": "bearer",
        "extra_headers": {
            "HTTP-Referer": "https://yeehee.vercel.app",
            "X-Title": "yeehee XAU Signal",
        },
        "models_endpoint": "/models",
        "free_filter": lambda m: ":free" in m.get("id", "") or m.get("pricing", {}).get("prompt") in ("0", 0, "0.0"),
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "format": "anthropic",
        "auth": "x-api-key",
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "models_endpoint": "/models",
        "free_filter": None,
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "format": "openai",
        "auth": "bearer",
        "extra_headers": {},
        "models_endpoint": "/models",
        "free_filter": None,
    },
    "groq": {
        "label": "Groq Cloud",
        "base_url": "https://api.groq.com/openai/v1",
        "format": "openai",
        "auth": "bearer",
        "extra_headers": {},
        "models_endpoint": "/models",
        "free_filter": lambda m: True,  # Groq free tier covers all listed models with rate limits
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "format": "gemini",
        "auth": "query_key",
        "extra_headers": {},
        "models_endpoint": "/models",
        "free_filter": lambda m: True,
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "format": "openai",
        "auth": "none",
        "extra_headers": {},
        "models_endpoint": "/models",
        "free_filter": lambda m: True,
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "format": "openai",
        "auth": "none",
        "extra_headers": {},
        "models_endpoint": "/models",
        "free_filter": lambda m: True,
    },
}


# ── Result Types ────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = None  # full raw response for debugging


@dataclass
class LLMError(Exception):
    provider: str
    status: Optional[int]
    message: str

    def __str__(self) -> str:  # type: ignore[override]
        return f"LLMError[{self.provider}] status={self.status} msg={self.message}"


# ── Router ─────────────────────────────────────────────────────────────────────

class LLMRouter:
    """One client to rule them all.

    Usage:
        r = LLMRouter()
        r.set_credential('openrouter', api_key='sk-or-v1-...')
        resp = r.chat(
            provider='openrouter',
            model='meta-llama/llama-3.3-70b-instruct:free',
            system='You are a helpful assistant.',
            prompt='Hello',
        )
        print(resp.text)
    """

    def __init__(self, credentials: Optional[dict[str, dict]] = None, timeout: int = 60):
        # credentials = {provider: {'api_key': str, 'base_url': str (optional)}}
        self._creds: dict[str, dict] = credentials or {}
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __del__(self):
        try:
            self._client.close()
        except Exception:
            pass

    # ── Configuration ──

    def set_credential(self, provider: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        provider = provider.lower()
        cur = self._creds.get(provider, {})
        if api_key is not None:
            cur["api_key"] = api_key
        if base_url is not None:
            cur["base_url"] = base_url
        self._creds[provider] = cur

    def load_from_env(self) -> None:
        """Pull credentials from common env vars."""
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
                self.set_credential(prov, api_key=v)

    def has_credential(self, provider: str) -> bool:
        provider = provider.lower()
        if provider in ("ollama", "lmstudio"):
            return True  # local, no key needed
        return bool(self._creds.get(provider, {}).get("api_key"))

    def _base_url(self, provider: str) -> str:
        provider = provider.lower()
        custom = self._creds.get(provider, {}).get("base_url")
        if custom:
            return custom.rstrip("/")
        return PROVIDERS[provider]["base_url"].rstrip("/")

    def _auth_headers(self, provider: str) -> dict[str, str]:
        info = PROVIDERS[provider]
        key = self._creds.get(provider, {}).get("api_key", "")
        h: dict[str, str] = dict(info.get("extra_headers", {}))
        if info["auth"] == "bearer":
            if key:
                h["Authorization"] = f"Bearer {key}"
        elif info["auth"] == "x-api-key":
            if key:
                h["x-api-key"] = key
        # gemini uses query string, not header
        h["Content-Type"] = "application/json"
        return h

    # ── Chat ──

    def chat(
        self,
        provider: str,
        model: str,
        system: str,
        prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 800,
        json_mode: bool = False,
    ) -> LLMResponse:
        provider = provider.lower()
        if provider not in PROVIDERS:
            raise LLMError(provider, None, f"unknown provider '{provider}'")
        info = PROVIDERS[provider]

        if info["format"] == "openai":
            return self._chat_openai_compat(provider, model, system, prompt, temperature, max_tokens, json_mode)
        if info["format"] == "anthropic":
            return self._chat_anthropic(provider, model, system, prompt, temperature, max_tokens, json_mode)
        if info["format"] == "gemini":
            return self._chat_gemini(provider, model, system, prompt, temperature, max_tokens, json_mode)
        raise LLMError(provider, None, f"format {info['format']} not implemented")

    # ── OpenAI-compatible (OpenRouter, OpenAI, Groq, Ollama, LM Studio) ──

    def _chat_openai_compat(self, provider, model, system, prompt, temperature, max_tokens, json_mode) -> LLMResponse:
        url = f"{self._base_url(provider)}/chat/completions"
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        t0 = time.time()
        try:
            r = self._client.post(url, headers=self._auth_headers(provider), json=body)
        except httpx.RequestError as e:
            raise LLMError(provider, None, f"network error: {e}")
        latency = int((time.time() - t0) * 1000)

        if r.status_code >= 400:
            raise LLMError(provider, r.status_code, r.text[:500])

        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError(provider, r.status_code, f"unexpected response: {str(data)[:300]}")

        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            provider=provider,
            model=model,
            latency_ms=latency,
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            raw=data,
        )

    # ── Anthropic native ──

    def _chat_anthropic(self, provider, model, system, prompt, temperature, max_tokens, json_mode) -> LLMResponse:
        url = f"{self._base_url(provider)}/messages"
        body: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        t0 = time.time()
        try:
            r = self._client.post(url, headers=self._auth_headers(provider), json=body)
        except httpx.RequestError as e:
            raise LLMError(provider, None, f"network error: {e}")
        latency = int((time.time() - t0) * 1000)

        if r.status_code >= 400:
            raise LLMError(provider, r.status_code, r.text[:500])

        data = r.json()
        try:
            blocks = data.get("content", [])
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except Exception:
            raise LLMError(provider, r.status_code, f"unexpected response: {str(data)[:300]}")

        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            provider=provider,
            model=model,
            latency_ms=latency,
            prompt_tokens=usage.get("input_tokens", 0) or 0,
            completion_tokens=usage.get("output_tokens", 0) or 0,
            raw=data,
        )

    # ── Google Gemini native ──

    def _chat_gemini(self, provider, model, system, prompt, temperature, max_tokens, json_mode) -> LLMResponse:
        key = self._creds.get(provider, {}).get("api_key", "")
        if not key:
            raise LLMError(provider, None, "gemini api key required")

        # Gemini model names like 'gemini-2.0-flash-exp' or 'models/gemini-2.0-flash-exp'
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = f"{self._base_url(provider)}/{model_path}:generateContent?key={key}"

        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_tokens),
            },
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        t0 = time.time()
        try:
            r = self._client.post(url, headers={"Content-Type": "application/json"}, json=body)
        except httpx.RequestError as e:
            raise LLMError(provider, None, f"network error: {e}")
        latency = int((time.time() - t0) * 1000)

        if r.status_code >= 400:
            raise LLMError(provider, r.status_code, r.text[:500])

        data = r.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(provider, r.status_code, f"unexpected response: {str(data)[:300]}")

        usage = data.get("usageMetadata", {}) or {}
        return LLMResponse(
            text=text,
            provider=provider,
            model=model,
            latency_ms=latency,
            prompt_tokens=usage.get("promptTokenCount", 0) or 0,
            completion_tokens=usage.get("candidatesTokenCount", 0) or 0,
            raw=data,
        )

    # ── Validation ──

    def test_credential(self, provider: str) -> tuple[bool, str]:
        """Quick ping to validate the api key. Returns (ok, message)."""
        provider = provider.lower()
        if provider not in PROVIDERS:
            return False, f"unknown provider '{provider}'"
        if not self.has_credential(provider) and provider not in ("ollama", "lmstudio"):
            return False, "no api key set"

        try:
            models = self.list_models(provider)
            return True, f"ok — {len(models)} models available"
        except LLMError as e:
            return False, str(e)
        except Exception as e:
            return False, f"error: {e}"

    # ── Models listing ──

    def list_models(self, provider: str, free_only: bool = False) -> list[dict]:
        provider = provider.lower()
        if provider not in PROVIDERS:
            raise LLMError(provider, None, f"unknown provider '{provider}'")
        info = PROVIDERS[provider]
        url = f"{self._base_url(provider)}{info['models_endpoint']}"
        if provider == "gemini":
            key = self._creds.get(provider, {}).get("api_key", "")
            url = f"{url}?key={key}"
        try:
            r = self._client.get(url, headers=self._auth_headers(provider))
        except httpx.RequestError as e:
            raise LLMError(provider, None, f"network error: {e}")
        if r.status_code >= 400:
            raise LLMError(provider, r.status_code, r.text[:300])
        data = r.json()

        # Normalise to list[{id, label, free}]
        if provider == "anthropic":
            raw = data.get("data", []) or []
            out = [{"id": m["id"], "label": m.get("display_name", m["id"]), "free": False} for m in raw]
        elif provider == "gemini":
            raw = data.get("models", []) or []
            out = [
                {
                    "id": m["name"].replace("models/", ""),
                    "label": m.get("displayName", m["name"]),
                    "free": True,
                }
                for m in raw
                if "generateContent" in (m.get("supportedGenerationMethods") or [])
            ]
        else:
            # OpenAI-style
            raw = data.get("data", []) or []
            out = []
            for m in raw:
                free_flag = False
                if info.get("free_filter"):
                    try:
                        free_flag = bool(info["free_filter"](m))
                    except Exception:
                        free_flag = False
                out.append({
                    "id": m.get("id", ""),
                    "label": m.get("name") or m.get("id", ""),
                    "free": free_flag,
                    "context_length": m.get("context_length"),
                    "pricing": m.get("pricing"),
                })

        if free_only:
            out = [m for m in out if m.get("free")]
        return out


# ── Helper: load router from Supabase or env ────────────────────────────────────

def build_default_router_from_env() -> LLMRouter:
    r = LLMRouter()
    r.load_from_env()
    return r
