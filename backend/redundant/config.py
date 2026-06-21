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
# Approximate published rates; used to estimate spend saved for the demo and to
# drive provider-aware UI affordances (sponsor chips, model swap dropdowns).
@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    provider: str = "unknown"        # "anthropic" | "openai" | "google" | "mistral" | "local" | "unknown"
    family: str = "unknown"          # "claude" | "gpt" | "gemini" | "mistral" | "llama" | "qwen" | "embedding"
    short_label: str = ""            # tight chip label, e.g. "Opus 4.7", "GPT-4o", "Haiku 4.5"


MODEL_PRICING: dict[str, ModelPrice] = {
    # Anthropic — reference pricing for ingested traces that name these models.
    "claude-opus-4-8":      ModelPrice(15.0, 75.0, "anthropic", "claude", "Opus 4.8"),
    "claude-opus-4-7":      ModelPrice(15.0, 75.0, "anthropic", "claude", "Opus 4.7"),
    "claude-sonnet-4-6":    ModelPrice(3.0,  15.0, "anthropic", "claude", "Sonnet 4.6"),
    "claude-haiku-4-5":     ModelPrice(0.80,  4.0, "anthropic", "claude", "Haiku 4.5"),
    # OpenAI — gpt-4o / gpt-4o-mini are what redundant.llm() actually executes against.
    "gpt-4o":               ModelPrice(5.0,  15.0, "openai",    "gpt",    "GPT-4o"),
    "gpt-4o-mini":          ModelPrice(0.15,  0.6, "openai",    "gpt",    "GPT-4o mini"),
    # Google
    "gemini-1.5-pro":       ModelPrice(1.25,  5.0, "google",    "gemini", "Gemini 1.5 Pro"),
    "gemini-1.5-flash":     ModelPrice(0.075, 0.3, "google",    "gemini", "Gemini 1.5 Flash"),
    # Mistral
    "mistral-large":        ModelPrice(2.0,   6.0, "mistral",   "mistral","Mistral Large"),
    # Local / open weights — tokens counted, marginal cost 0.
    "llama-3.1-70b":        ModelPrice(0.0,   0.0, "local",     "llama",  "Llama 3.1 70B"),
    "qwen-2.5-72b":         ModelPrice(0.0,   0.0, "local",     "qwen",   "Qwen 2.5 72B"),
    # Embeddings (input only); output cost is 0.
    "text-embedding-3-small": ModelPrice(0.02, 0.0, "openai",   "embedding", "Embedding 3 small"),
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

    # Force the deterministic local-fallback embedding even when an API key is
    # present. Set REDUNDANT_EMBEDDINGS_OFFLINE=1 for hermetic tests / zero-cost
    # offline demos (the suite sets this so it never makes real OpenAI calls).
    embeddings_offline: bool = field(
        default_factory=lambda: os.getenv("REDUNDANT_EMBEDDINGS_OFFLINE", "").strip().lower()
        in ("1", "true", "yes")
    )

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
