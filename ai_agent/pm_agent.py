"""Optional Claude API layer — only activates kalau ANTHROPIC_API_KEY ada.
Wrap rule_engine output dengan natural-language reasoning dari PM persona."""
from __future__ import annotations
import json
from typing import Optional

from config.settings import HAS_AI_KEY, ANTHROPIC_API_KEY, AI
from ai_agent.rule_engine import DebateResult
from ai_agent.prompts import PM_PERSONA, SYNTHESIZER


def claude_available() -> bool:
    if not HAS_AI_KEY:
        return False
    try:
        import anthropic  # noqa
        return True
    except ImportError:
        return False


def enrich_with_pm_narrative(result: DebateResult, market_context: dict) -> DebateResult:
    """Optionally enrich rule-based result dengan PM narrative dari Claude.
    Kalau API gagal/no key, kembali apa adanya."""
    if not claude_available():
        return result

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        agent_summary = "\n".join(
            f"- {a.name}: {a.verdict} (conf={a.confidence:.2f}) — reasons: {'; '.join(a.reasoning[:4])}"
            for a in result.agents
        )

        prompt = f"""\
Current XAU/USD market context:
- Price: {market_context.get('price', 'N/A')}
- Regime: {market_context.get('regime', 'N/A')}
- Session: {market_context.get('session', 'N/A')}
- Intermarket score: {market_context.get('intermarket_score', 'N/A')}
- COT z-score: {market_context.get('cot_z', 'N/A')}
- Upcoming high-impact events: {market_context.get('news_summary', 'none in 24h')}

4-agent rule-based debate result:
{agent_summary}

Final consensus: {result.final_action} (conf {result.confidence}), strength {result.signal_strength}
Risks flagged: {'; '.join(result.risks)}

As the senior XAU PM, write a CONCISE 3-bullet narrative explaining the trade thesis or why we stand aside.
Output JSON with keys: thesis (1 sentence), key_levels_to_watch (1 sentence), what_invalidates (1 sentence).
Strict JSON only, no markdown."""

        msg = client.messages.create(
            model=AI.model,
            max_tokens=AI.max_tokens,
            temperature=AI.temperature,
            system=PM_PERSONA,
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        # Try parse JSON
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                pm_lines = [
                    f"[PM thesis] {parsed.get('thesis', '')}",
                    f"[PM levels] {parsed.get('key_levels_to_watch', '')}",
                    f"[PM invalidation] {parsed.get('what_invalidates', '')}",
                ]
                result.reasoning_chain.extend(pm_lines)
        except Exception:
            result.reasoning_chain.append(f"[PM raw] {text[:300]}")

    except Exception as e:
        result.reasoning_chain.append(f"[PM unavailable: {e}]")

    return result
