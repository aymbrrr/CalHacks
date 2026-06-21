"""Pricing + provider classification for model names.

Single lookup point used by detection (cost attribution), trace ingest (per-span
cost stamping), and the UI (sponsor chips, model-swap dropdowns). Backed by
``config.MODEL_PRICING``; gracefully degrades for unknown model strings.
"""

from __future__ import annotations

from redundant.config import MODEL_PRICING, ModelPrice

# Default used when the model is unknown / null. Mid-tier price so estimates
# don't massively under- or over-state cost for unrecognised names.
_DEFAULT = ModelPrice(
    input_per_mtok=3.0,
    output_per_mtok=15.0,
    provider="unknown",
    family="unknown",
    short_label="model",
)


def info_for(model: str | None) -> ModelPrice:
    """Return pricing + metadata for a model name.

    Order:
      1. Exact registry match.
      2. Prefix match (handles dated variants like ``gpt-4o-2025-08-01``).
      3. Heuristic provider sniff so unknown future names still surface the right
         sponsor hook (Anthropic prompt-cache fix, etc.).
      4. ``_DEFAULT``.
    """
    if not model:
        return _DEFAULT

    if model in MODEL_PRICING:
        return MODEL_PRICING[model]

    for key, info in MODEL_PRICING.items():
        if model.startswith(key) or key.startswith(model):
            return info

    lo = model.lower()
    if lo.startswith("claude"):
        return ModelPrice(_DEFAULT.input_per_mtok, _DEFAULT.output_per_mtok,
                          "anthropic", "claude", model)
    if lo.startswith("gpt"):
        return ModelPrice(_DEFAULT.input_per_mtok, _DEFAULT.output_per_mtok,
                          "openai", "gpt", model)
    if lo.startswith("gemini"):
        return ModelPrice(_DEFAULT.input_per_mtok, _DEFAULT.output_per_mtok,
                          "google", "gemini", model)
    if any(tok in lo for tok in ("llama", "qwen", "mistral")):
        family = "mistral" if "mistral" in lo else ("qwen" if "qwen" in lo else "llama")
        return ModelPrice(0.0, 0.0, "local", family, model)

    return _DEFAULT


def cost_for(model: str | None, tokens_in: int, tokens_out: int) -> float:
    """Estimate spend in USD given a model and token usage."""
    p = info_for(model)
    return round(
        tokens_in / 1_000_000 * p.input_per_mtok
        + tokens_out / 1_000_000 * p.output_per_mtok,
        6,
    )


def short_label(model: str | None) -> str:
    """A compact display label for chips and tooltips.

    Falls back to the raw model string if the registry has no short form and the
    string is short enough to render; otherwise truncates the path part of names
    like ``meta-llama/Llama-3.1-70B-Instruct`` to the trailing segment.
    """
    if not model:
        return "—"
    info = info_for(model)
    if info.short_label:
        return info.short_label
    # Trim Hugging-Face-style ``org/Model-Name`` paths down to the trailing slug.
    if "/" in model:
        return model.rsplit("/", 1)[-1]
    return model
