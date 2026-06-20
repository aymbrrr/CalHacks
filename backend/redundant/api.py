"""FastAPI app implementing the UI/Backend Contract.

Endpoints (docs/redundant-plan.md):
  POST /api/runs/start
  GET  /api/runs/{run_id}/events?after=<event_id>
  GET  /api/runs/{run_id}/stream            (SSE)
  GET  /api/runs/{run_id}/report
  POST /api/runs/{run_id}/replay

The UI builds against these and never reads Redis directly.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from redundant.config import SETTINGS
from redundant.demo import run_demo_task
from redundant.report import build_report
from redundant.schema import Run
from redundant.trace_ingest import load_spans
from redundant.detection import analyze
from redundant.lang_cache import LangCache
from redundant.routing import route_findings

try:
    from redundant.redis_store import RedisStore

    _store = RedisStore(SETTINGS)
    _store.ping()
except Exception:
    # Fall back to in-memory so the demo/UI still works offline.
    from redundant.memory_store import InMemoryStore

    _store = InMemoryStore(SETTINGS)


def get_store():
    return _store


app = FastAPI(title="Redundant Runtime API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StartBody(BaseModel):
    task: str
    mode: str = "redundant"  # baseline | redundant | replay


@app.post("/api/runs/start", response_model=Run)
async def start_run(body: StartBody) -> Run:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    run = Run(run_id=run_id, task=body.task, mode=body.mode, status="running",
              started_at=_now())
    store = get_store()
    store.save_run(run)
    # Run the scripted waste task in a background thread so events stream as they
    # happen and progress is independent of the request event loop.
    threading.Thread(target=_execute_run, args=(run, store), daemon=True).start()
    return run


def _execute_run(run: Run, store) -> None:
    try:
        run_demo_task(run.run_id, run.mode, store)
        run.status = "complete"
    except Exception as exc:  # pragma: no cover - defensive
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.completed_at = _now()
        store.save_run(run)


@app.get("/api/runs/{run_id}/events")
async def get_events(run_id: str, after: str = "0"):
    return [e.model_dump(mode="json") for e in get_store().read_events(run_id, after=after)]


@app.get("/api/runs/{run_id}/report")
async def get_report(run_id: str):
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(404, "unknown run")
    return build_report(run_id, store.read_events(run_id)).model_dump(mode="json")


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str):
    store = get_store()

    async def gen():
        last = "0"
        idle = 0
        while True:
            events = store.read_events(run_id, after=last)
            for ev in events:
                last = ev.event_id
                idle = 0
                yield {"event": "redundant", "data": ev.model_dump_json()}
            run = store.get_run(run_id)
            if run and run.status in ("complete", "failed") and not events:
                yield {"event": "done", "data": run.model_dump_json()}
                break
            await asyncio.sleep(0.25)
            idle += 1
            if idle > 1200:  # ~5 min safety cap
                break

    return EventSourceResponse(gen())


@app.post("/api/runs/{run_id}/replay", response_model=Run)
async def replay(run_id: str) -> Run:
    """Replay a previously recorded run's events under a fresh run id with
    deterministic timing, so the demo works even if sponsor APIs fail."""
    store = get_store()
    source_events = store.read_events(run_id)
    if not source_events:
        raise HTTPException(404, "no recorded events for run")
    new_id = f"replay-{uuid.uuid4().hex[:8]}"
    run = Run(run_id=new_id, task="(replay)", mode="replay", status="running",
              started_at=_now())
    store.save_run(run)

    def _do():
        import time

        for ev in source_events:
            ev.run_id = new_id
            ev.event_id = "pending"
            store.emit_event(ev)
            time.sleep(0.05)  # deterministic pacing for the demo
        run.status = "complete"
        run.completed_at = _now()
        store.save_run(run)

    threading.Thread(target=_do, daemon=True).start()
    return run


@app.get("/health")
async def health():
    return {"ok": True, "store": type(get_store()).__name__}



# ---------------------------------------------------------------------------
# /findings — Redis-centric trace analysis (DESIGN_redis.md)
# ---------------------------------------------------------------------------

@app.get("/findings")
async def get_findings(run_id: str = "", json_path: str = ""):
    """Analyze a trace and return Findings[].

    Query params:
      run_id    — read from Redis Stream trace:{run_id}
      json_path — path to a local frozen trace JSON (defaults to demo_trace.json)
    """
    store = get_store()
    redis_client = getattr(store, "r", None)

    spans = load_spans(
        run_id=run_id or None,
        json_path=json_path or None,
        redis_client=redis_client if run_id else None,
    )

    result = analyze(spans)
    route_findings(result["findings"])

    # Pre-warm LangCache from wasteful findings.
    cache = LangCache(redis_client=redis_client)
    spans_by_id = {s.span_id: s for s in spans}
    cache_written = cache.populate_from_findings(result["findings"], spans_by_id)

    return {
        "findings": [f.model_dump(mode="json") for f in result["findings"]],
        "total_cost_usd": result["total_cost_usd"],
        "wasted_cost_usd": result["wasted_cost_usd"],
        "waste_pct": result["waste_pct"],
        "cache_entries_written": cache_written,
        "span_count": len(spans),
    }


@app.get("/findings/cache-lookup")
async def cache_lookup(tool_name: str, input_hash: str):
    """Check if a result is in LangCache for the given (tool_name, input_hash)."""
    store = get_store()
    redis_client = getattr(store, "r", None)
    cache = LangCache(redis_client=redis_client)
    result = cache.get(tool_name, input_hash)
    return {"hit": result is not None, "result": result}
