"""Trace ingestion: frozen JSON loader + Redis Streams XRANGE batch consumer.

§7.1 of DESIGN_redis.md.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from redundant.pricing import cost_for
from redundant.span_schema import Span


# Decisions whose calls never executed — their ~0 cost is real, not "unstamped".
_NON_EXECUTED_DECISIONS = {"EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN"}


def _stamp_cost(span: Span) -> Span:
    """Populate ``cost_usd`` if missing so every span carries a real number.

    Spans that already arrive with a cost (e.g. from the runtime emitter) are
    left untouched — the runtime's number wins over a token-derived estimate.
    Non-executed calls (reuse/block) legitimately cost ~0, so don't re-derive a
    token cost they never incurred just because cost_usd is falsy.
    """
    if span.cost_usd or span.decision in _NON_EXECUTED_DECISIONS:
        return span
    span.cost_usd = cost_for(span.model, span.tokens.input, span.tokens.output)
    return span


def load_from_json(path: str | Path) -> list[Span]:
    """Load spans from a frozen trace JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_stamp_cost(Span.model_validate(s)) for s in data]


def load_spans(
    run_id: Optional[str] = None,
    json_path: Optional[str | Path] = None,
    store=None,
    *,
    allow_default_fallback: bool = True,
) -> list[Span]:
    """Unified loader: prefer the run's span stream, else fall back to JSON.

    The ``store`` (RedisStore or InMemoryStore) owns the per-run span stream
    ``trace:{run_id}`` via ``read_spans``; using it instead of a raw Redis client
    means the offline (in-memory) path returns live spans too. An empty stream
    falls through to the JSON path only when ``allow_default_fallback`` is true.
    Explicit live-run callers set it false so a missing ``trace:{run_id}`` is
    visible instead of silently masquerading as bundled demo data.
    """
    if store is not None and run_id:
        try:
            raw = store.read_spans(run_id)
            if raw:
                return [_stamp_cost(Span.model_validate(s)) for s in raw]
        except Exception:
            pass
    if json_path:
        return load_from_json(json_path)
    if not allow_default_fallback:
        print(f"[trace_ingest] no live spans for run_id={run_id!r}; returning empty live payload")
        return []
    # Default: load the bundled demo trace for no-run demo routes.
    default = Path(__file__).parent / "demo_trace.json"
    print(
        f"[trace_ingest] no live spans for run_id={run_id!r}; "
        f"serving bundled demo_trace.json fallback"
    )
    return load_from_json(default)
