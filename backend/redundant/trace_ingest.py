"""Trace ingestion: frozen JSON loader + Redis Streams XRANGE batch consumer.

§7.1 of DESIGN_redis.md.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from redundant.pricing import cost_for
from redundant.span_schema import Span


def _stamp_cost(span: Span) -> Span:
    """Populate ``cost_usd`` if missing so every span carries a real number.

    Spans that already arrive with a cost (e.g. from the runtime emitter) are
    left untouched — the runtime's number wins over a token-derived estimate.
    """
    if span.cost_usd:
        return span
    span.cost_usd = cost_for(span.model, span.tokens.input, span.tokens.output)
    return span


def load_from_json(path: str | Path) -> list[Span]:
    """Load spans from a frozen trace JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_stamp_cost(Span.model_validate(s)) for s in data]


def load_from_stream(run_id: str, redis_client) -> list[Span]:
    """Batch-consume an entire Redis Stream for a run via XRANGE."""
    entries = redis_client.xrange(f"trace:{run_id}", min="-", max="+")
    spans: list[Span] = []
    for _sid, fields in entries:
        raw = fields.get(b"data") or fields.get("data")
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        spans.append(_stamp_cost(Span.model_validate(json.loads(raw))))
    return spans


def load_spans(run_id: Optional[str] = None, json_path: Optional[str | Path] = None,
               redis_client=None) -> list[Span]:
    """Unified loader: prefer stream if redis_client provided, else fall back to JSON.

    An empty stream (run id not present in Redis) falls through to the JSON
    path so endpoints like /findings and /rerun still return something useful
    when called with an unknown run id — important for demo determinism.
    """
    if redis_client is not None and run_id:
        try:
            spans = load_from_stream(run_id, redis_client)
            if spans:
                return spans
        except Exception:
            pass
    if json_path:
        return load_from_json(json_path)
    # Default: load the bundled demo trace.
    default = Path(__file__).parent / "demo_trace.json"
    return load_from_json(default)
