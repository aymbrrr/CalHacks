"""Configuration: env loading, model pricing, similarity threshold, cacheability TTLs.

All tunables live here so the decision engine and estimator stay pure and testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv optional at runtime
    pass


# --- Model pricing (USD per 1M tokens) --------------------------------------
# Approximate published rates; used only to estimate spend saved for the demo.
@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


MODEL_PRICING: dict[str, ModelPrice] = {
    # OpenAI chat models — what redundant.llm() actually executes against.
    "gpt-4o": ModelPrice(5.0, 15.0),
    "gpt-4o-mini": ModelPrice(0.15, 0.6),
    # Embeddings (input only); output cost is 0.
    "text-embedding-3-small": ModelPrice(0.02, 0.0),
    # Reference pricing only — for ingested traces that name these models. We
    # never call them; kept so the dashboard can price third-party trace data.
    "claude-opus-4-8": ModelPrice(15.0, 75.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-haiku-4-5": ModelPrice(0.80, 4.0),
}

# Fallback assumed latency (ms) per executed call type, used to credit savings
# on reuse when we have no measured baseline for the avoided call.
DEFAULT_LLM_LATENCY_MS = 2200
DEFAULT_TOOL_LATENCY_MS = 1500


@dataclass(frozen=True)
class Settings:
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))
    # OpenAI — used for both embeddings and redundant.llm() executions.
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    # Sentry alert arm. Empty DSN → mock mode (SR-9), never crashes the pipeline.
    sentry_dsn: str = field(default_factory=lambda: os.getenv("SENTRY_DSN", ""))
    # Repetition count that tips a finding into "runaway" (mirrors detection.R_MAX).
    r_max: int = field(default_factory=lambda: int(os.getenv("R_MAX", "10")))
    # Above these, a runaway escalates from "error" to "fatal" (SR-3 level policy).
    sentry_fatal_count: int = 20
    sentry_fatal_cost: float = 1.0

    default_model: str = field(default_factory=lambda: os.getenv("REDUNDANT_DEFAULT_MODEL", "gpt-4o-mini"))
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Cosine similarity (1 - distance) at/above which a semantic candidate is a
    # reuse candidate (still subject to the verifier).
    sim_threshold: float = field(
        default_factory=lambda: float(os.getenv("REDUNDANT_SIM_THRESHOLD", "0.86"))
    )

    # Token count above which an unsafe-to-reuse call is considered "bloated"
    # and routed to COMPRESS_AND_EXECUTE.
    bloat_token_threshold: int = 1500

    # Number of identical hashes within a run that trips loop detection.
    loop_threshold: int = 3

    # TTLs (seconds) by cacheability class.
    ttl_pure: int = 24 * 3600
    ttl_freshness_sensitive: int = 120
    ttl_state_bound: int = 600
    # side_effecting is never stored for reuse.

    # Redis key namespace.
    namespace: str = "redundant"


SETTINGS = Settings()


def ttl_for(cacheability: str, settings: Settings = SETTINGS) -> int | None:
    """Return the exact-cache TTL (seconds) for a cacheability class, or None
    if the class must never be stored for reuse."""
    return {
        "pure": settings.ttl_pure,
        "freshness_sensitive": settings.ttl_freshness_sensitive,
        "state_bound": settings.ttl_state_bound,
        "side_effecting": None,
    }.get(cacheability)
