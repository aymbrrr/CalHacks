#!/usr/bin/env python3
"""Verify Band agent tool calls route through the real Redundant backend.

Run twice with the same args:
  Call 1  → EXECUTE, writes redundant:cache:exact:... key, XADDs to stream
  Call 2  → EXACT_REUSE, reads the same cache key from Redis
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Make backend importable from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from redundant.runtime import Redundant
from redundant.redis_store import RedisStore
from redundant.config import SETTINGS


TOOL_NAME = "search_docs"
ARGS = {"query": "agent cost optimization tools Redis Sentry"}


def call_tool(r: Redundant, agent_id: str, call_num: int) -> None:
    print(f"\n{'='*60}")
    print(f"  CALL #{call_num}  agent={agent_id!r}  tool={TOOL_NAME!r}")
    print(f"  args={ARGS!r}")
    print(f"{'='*60}")
    event = r.tool(agent_id, TOOL_NAME, ARGS, cacheability="pure")
    print(f"\n  >>> RESULT decision={event.decision.value!r}  call_id={event.call_id!r}")
    print(f"  >>> source_call_id={event.source_call_id!r}")
    print(f"  >>> saved_cost=${event.saved_cost_usd:.4f}  saved_latency={event.saved_latency_ms}ms")
    print(f"  >>> stream event_id={event.event_id!r}")
    return event


def main() -> None:
    run_id = f"verify-{uuid.uuid4().hex[:8]}"
    print(f"\n[verify] run_id={run_id!r}")
    print(f"[verify] Redis: {SETTINGS.redis_url.split('@')[-1]}")

    store = RedisStore(SETTINGS)
    print(f"[verify] Redis ping: {store.ping()}")

    r = Redundant(run_id=run_id, store=store, enabled=True)

    # Call 1: should EXECUTE and write to cache
    ev1 = call_tool(r, "ResearchAgent", 1)
    assert ev1.decision.value == "EXECUTE", f"Expected EXECUTE, got {ev1.decision.value}"
    print("\n[verify] ✓ Call 1 decision = EXECUTE")

    # Confirm the exact cache key exists in Redis
    from redundant.normalize import normalize_tool_args, compute_hash, scope_key
    normalized = normalize_tool_args(TOOL_NAME, ARGS)
    scope = scope_key(run_id, "pure", None)
    h = compute_hash(scope, normalized)
    exact_key = store._exact_key(scope, h)
    raw = store.r.get(exact_key)
    assert raw is not None, f"Expected cache key {exact_key!r} to exist after EXECUTE"
    print(f"[verify] ✓ Redis key written: {exact_key!r}")

    # Call 2 (same agent, same args) → should EXACT_REUSE from Redis
    ev2 = call_tool(r, "ReportAgent", 2)
    assert ev2.decision.value == "EXACT_REUSE", f"Expected EXACT_REUSE, got {ev2.decision.value}"
    print("\n[verify] ✓ Call 2 decision = EXACT_REUSE")
    assert ev2.source_call_id == ev1.call_id, (
        f"source_call_id mismatch: expected {ev1.call_id!r}, got {ev2.source_call_id!r}"
    )
    print(f"[verify] ✓ source_call_id matches call 1 ({ev2.source_call_id!r})")

    # Confirm stream received both events
    events = store.read_events(run_id)
    stream_key = store.stream_key(run_id)
    print(f"\n[verify] Stream key: {stream_key!r}")
    print(f"[verify] Events in stream: {len(events)}")
    for ev in events:
        print(f"  sid={ev.event_id!r}  decision={ev.decision.value!r}  tool={ev.tool_name!r}  agent={ev.agent_id!r}")

    assert len(events) >= 2, f"Expected ≥2 events in stream, got {len(events)}"
    decisions = [ev.decision.value for ev in events]
    assert "EXECUTE" in decisions, "Missing EXECUTE event in stream"
    assert "EXACT_REUSE" in decisions, "Missing EXACT_REUSE event in stream"

    print("\n[verify] ✓ All assertions passed.")
    print("[verify] ✓ Band agent tool calls are routed through the real Redundant backend.")
    print(f"[verify] ✓ Frontend can consume live events from: GET /api/runs/{run_id}/stream")


if __name__ == "__main__":
    main()
