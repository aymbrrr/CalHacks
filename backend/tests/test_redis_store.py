"""Integration tests for the real RedisStore. Skipped automatically if Redis is
unreachable (e.g. no Redis Cloud creds configured)."""

import time
import uuid

import pytest

from redundant.config import SETTINGS
from redundant.embeddings import embed_list
from redundant.schema import CallRecord, Cacheability, CallType, Decision, RedundantEvent


@pytest.fixture(scope="module")
def store():
    try:
        from redundant.redis_store import RedisStore

        s = RedisStore(SETTINGS)
        s.ping()
        s.ensure_index()
        return s
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")


def _vector_knn_supported(store) -> bool:
    """Smoke-test KNN on a throwaway doc. Not every Redis (Cloud plan / version)
    actually serves RediSearch vector search; on those it returns no rows for a
    perfectly-formed doc, so the vector-specific test should skip, not fail."""
    probe_id = f"probe-{uuid.uuid4().hex}"
    scope = f"run:probe-{uuid.uuid4().hex[:6]}"
    rec = _record(scope.split(":", 1)[1], "knn capability probe", call_id=probe_id)
    store.index_call(scope, rec)
    time.sleep(0.3)
    try:
        return bool(store.knn_search(scope, embed_list("knn capability probe"), k=1))
    finally:
        try:
            store.r.delete(store._call_key(probe_id))
        except Exception:
            pass


def _record(run_id, text, cacheability=Cacheability.PURE, call_id=None):
    norm = f'{{"q":"{text}"}}'
    return CallRecord(
        call_id=call_id or str(uuid.uuid4()), run_id=run_id, agent_id="research-agent",
        call_type=CallType.TOOL, tool_name="search_docs", cacheability=cacheability,
        normalized_input=norm, input_hash=str(uuid.uuid4()), embedding=embed_list(text),
        output=f"out:{text}", input_tokens=100, output_tokens=50, cost_usd=0.01,
        latency_ms=1500, created_at="2026-06-20T00:00:00Z", decision=Decision.EXECUTE,
    )


def test_exact_put_get_roundtrip(store):
    run = f"it-{uuid.uuid4().hex[:6]}"
    scope = f"run:{run}"
    rec = _record(run, "redis caching")
    store.put_exact(scope, rec)
    got = store.get_exact(scope, rec.input_hash)
    assert got is not None and got.output == rec.output


def test_side_effecting_not_stored(store):
    run = f"it-{uuid.uuid4().hex[:6]}"
    scope = f"run:{run}"
    rec = _record(run, "send", cacheability=Cacheability.SIDE_EFFECTING)
    store.put_exact(scope, rec)
    assert store.get_exact(scope, rec.input_hash) is None


def test_knn_finds_indexed_call(store):
    if not _vector_knn_supported(store):
        pytest.skip("RediSearch vector KNN unavailable on this Redis instance")
    run = f"it-{uuid.uuid4().hex[:6]}"
    scope = f"run:{run}"
    rec = _record(run, "redis vector search")
    store.index_call(scope, rec)
    time.sleep(0.3)  # allow index to catch up
    hits = store.knn_search(scope, embed_list("redis vector search"), k=3)
    assert hits and hits[0].similarity > 0.99


def test_stream_emit_and_read(store):
    run = f"it-{uuid.uuid4().hex[:6]}"
    ev = RedundantEvent(
        event_id="pending", run_id=run, ts="2026-06-20T00:00:00Z", agent_id="research-agent",
        call_id="c1", call_type=CallType.TOOL, tool_name="search_docs",
        decision=Decision.EXECUTE, cacheability=Cacheability.PURE, summary="s", explanation="e",
    )
    sid = store.emit_event(ev)
    assert sid
    events = store.read_events(run)
    assert len(events) == 1 and events[0].event_id == sid
