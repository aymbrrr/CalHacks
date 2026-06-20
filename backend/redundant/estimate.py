"""Cost / latency / token estimation.

Pure and dependency-light: a local token heuristic by default, with an optional
Anthropic count_tokens path. Spend numbers are estimates for the demo dashboard,
not billing-accurate.
"""

from __future__ import annotations

from typing import Any

from redundant.config import (
    MODEL_PRICING,
    DEFAULT_LLM_LATENCY_MS,
    DEFAULT_TOOL_LATENCY_MS,
)


def count_tokens(text: str) -> int:
    """Local heuristic: ~4 chars per token. Cheap, deterministic, no network."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages or []:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content
            )
        total += count_tokens(str(content))
    return total


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost for a call given token counts and the model pricing table."""
    price = MODEL_PRICING.get(model)
    if price is None:
        # Unknown model: assume mid-tier so the demo still shows a number.
        price = MODEL_PRICING["claude-sonnet-4-6"]
    return round(
        input_tokens / 1_000_000 * price.input_per_mtok
        + output_tokens / 1_000_000 * price.output_per_mtok,
        6,
    )


def default_latency_ms(call_type: str) -> int:
    return DEFAULT_LLM_LATENCY_MS if call_type == "llm" else DEFAULT_TOOL_LATENCY_MS


def savings_from_reuse(source_cost_usd: float, source_latency_ms: int,
                       source_tokens: int) -> dict[str, float | int]:
    """When a call is reused/blocked instead of executed, the saved amount is the
    cost/latency/tokens of the call we avoided running."""
    return {
        "saved_cost_usd": round(source_cost_usd, 6),
        "saved_latency_ms": int(source_latency_ms),
        "saved_tokens": int(source_tokens),
    }
