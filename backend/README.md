# Redundant — Runtime + Redis Core (Chunk 1)

The runtime firewall: intercepts every expensive agent call, decides whether to
execute or safely reuse, and emits live events + a final cost report.

## Setup

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env        # fill REDIS_URL (Redis Cloud), OPENAI_API_KEY, ANTHROPIC_API_KEY
```

Everything runs **offline** without keys/Redis via an in-memory store + deterministic
demo tools/LLM, so the demo and tests never hard-depend on sponsor APIs.

## Run

```bash
python scripts/run_waste_demo.py          # baseline vs redundant cost table
uvicorn redundant.api:app --reload        # HTTP API + SSE for the UI (Chunk 4)
python scripts/record_trace.py trace.json # capture a replay trace (fallback)
```

## Test

```bash
pytest                # full suite (Redis integration tests skip if no REDIS_URL)
```

## What a caller does (Chunk 2 — Band agents)

```python
from redundant.runtime import Redundant
r = Redundant(run_id="demo-run-001")          # shared run => cross-agent reuse

ev = r.tool("research-agent", "search_docs", {"query": "redis caching"})
ev = r.tool("report-agent",  "search_docs", {"query": "redis caching"})  # -> EXACT_REUSE
ev = r.llm("report-agent", [{"role": "user", "content": "write report"}], model="claude-haiku-4-5")
print(ev.decision, ev.saved_cost_usd, ev.output)
```

Reuse is **run-scoped, not agent-scoped**, so one agent reuses another's result.

## Decisions

| Decision | When |
|---|---|
| `EXECUTE` | no safe prior result |
| `EXACT_REUSE` | identical normalized call already in run scope |
| `SEMANTIC_REUSE` | vector match above threshold **and** verifier approves |
| `COMPRESS_AND_EXECUTE` | reuse unsafe but prompt bloated |
| `BLOCK_OR_WARN` | duplicate side-effect or loop detected (never replays) |

## HTTP contract (owned by Chunk 1, consumed by Chunk 4)

- `POST /api/runs/start` `{task, mode}` → `Run`
- `GET  /api/runs/{id}/events?after=<event_id>` → `RedundantEvent[]`
- `GET  /api/runs/{id}/stream` → SSE of `RedundantEvent`
- `GET  /api/runs/{id}/report` → `RunReport`
- `POST /api/runs/{id}/replay` → replays a recorded trace

Event stream key: `stream:redundant:events:{run_id}`. The UI never reads Redis directly.

## Seams for other chunks (swap the default, keep the interface)

- **Chunk 3 / Terac** → `redundant/verifier.py` `Verifier.score()` (default = cosine threshold)
- **Chunk 4 / Token Company** → `redundant/compressor.py` `Compressor.compress()` (default = passthrough)
- **Production Redis** → `redundant/redis_store.py` (auto-selected when `REDIS_URL` reachable; else in-memory)
