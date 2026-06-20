# Redundant — Shared Contracts, Integration & Remaining Work

*Everything that isn't owned by a single section doc. These are the pieces that sit **between** owners — each section assumes someone else handles them, so without this doc they fall through the cracks at hour 18.*

Covers the gaps left after `DESIGN_redis`, `BAND_REQUIREMENTS`, `UI_REQUIREMENTS`, and `SENTRY_REQUIREMENTS`.

---

## 1. How to use this doc

Two kinds of content: **shared artifacts that are specified here concretely** (build them as written), and **integration/ops work that needs an owner** (assign in the hour-0 huddle). The ownership matrix below assigns every item; the rest of the doc specifies them.

## 2. Ownership matrix

| Item | §  | Owner | Confirmed-with |
|---|---|---|---|
| Tool registry (read/write allowlist) | 3.1 | Core | Band (tool list) |
| `input_hash` normalization | 3.2 | Core (shared module) | Band |
| Model price table | 3.3 | Core | Band (models used) |
| API contract (`/analyze`, `/findings`, `/rerun`) | 3.4 | Core | UI |
| Trace-completion signal | 3.5 | Band emits / Core consumes | — |
| Frozen trace JSON fixture | 4.1 | Core or Integration | Band (targets it) |
| Frozen findings JSON fixture | 4.2 | Core | UI (consumes it) |
| `/rerun` savings computation | 5.1 | Core | UI |
| Convergence heuristic | 5.2 | Core | — |
| Embeddings setup | 5.3 | Core | — |
| Service topology / compose | 6.1 | Integration (4th) | all |
| Env & secrets | 6.2 | Integration | all |
| Replay script | 6.3 | Integration | Core |
| Demo runbook | 6.4 | Integration | all |
| Smoke test | 6.5 | Integration | Core |

Note the load: most shared contracts land on **Core** (you), and the operational glue lands on the **Integration/Sentry** teammate. Plan accordingly.

## 3. Shared data contracts (specified — build as written)

### 3.1 Tool registry

The verifier's source of truth for cacheability. Defaults: `cacheable == (kind == "read")`.

```json
{
  "web_search":    { "kind": "read",  "cacheable": true },
  "verify_source": { "kind": "read",  "cacheable": true },
  "db_query":      { "kind": "read",  "cacheable": true },
  "send_email":    { "kind": "write", "cacheable": false },
  "db_write":      { "kind": "write", "cacheable": false }
}
```

A tool not in the registry is treated as **write/non-cacheable** (fail safe). The list must match the tools Band's run actually uses.

### 3.2 `input_hash` normalization (shared module — both Band and Core import this exact function)

```python
import hashlib, re

def input_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(norm.encode()).hexdigest()[:12]
```

Put it in one shared file both sides vendor. If Band and Core normalize differently, the "identical" redundant calls won't group and the cache key won't match — silent demo failure.

### 3.3 Model price table

```json
{
  "gpt-4o":      { "in_per_1k": 0.0025,  "out_per_1k": 0.01   },
  "gpt-4o-mini": { "in_per_1k": 0.00015, "out_per_1k": 0.0006 }
}
```
```
span_cost = tokens.input/1000 * in_per_1k  +  tokens.output/1000 * out_per_1k
```

> Values are **illustrative — verify current pricing** for whatever models Band's run uses before trusting the demo dollar figures. Unknown model → fall back to a default rate, never crash.

### 3.4 API contract (Core serves, UI + Integration consume)

```
POST /analyze        body { "run_id": "run-001" }
   → reads the stream, runs detection, caches the result
   → { "run_id": "run-001", "finding_count": 3, "ready": true }

GET  /findings?run_id=run-001
   → { "trace":   { "trace_id": "...", "spans": [ ... ] },
       "findings":[ ... ],
       "rollup":  { "total_cost": 1.42, "wasted_cost": 0.42,
                    "wasted_pct": 0.30, "finding_count": 3 } }

POST /rerun          body { "run_id": "run-001" }
   → { "run_id": "run-001", "original_cost": 1.42, "cached_cost": 1.21,
       "saved": 0.21,
       "cache_hits": [ { "finding_id": "f_12", "tool": "web_search",
                         "served_from_cache": true, "saved": 0.21 } ] }

GET  /health  → { "ok": true }
```

Ingestion is **stream-driven**, not an HTTP upload — `/analyze` pulls from `trace:{run_id}`. Lock these field names before UI and Core build in parallel.

### 3.5 Trace-completion signal (how the consumer knows a run is done)

Batch mode needs to know when the producer has finished. Band emits a final sentinel entry:

```
XADD trace:run-001 * data '{"event": "trace_end"}'
```

- **Batch:** Core reads `XRANGE - +` until it sees `trace_end` (or a short idle timeout as backup).
- **Live:** the sentinel tells the incremental consumer to finalize.

Without this, the consumer can't tell "still running" from "done." Band MUST emit it (add to `BAND_REQUIREMENTS` BR-9 capture).

## 4. Frozen fixtures

### 4.1 Frozen trace JSON
The captured Band run (or a hand-authored stand-in) satisfying `BAND_REQUIREMENTS` §9. Lives at a known path (e.g. `fixtures/frozen_trace.json`) as an ordered list of spans + the `trace_end` sentinel. The replay script (§6.3) `XADD`s it. **This is the highest-leverage artifact** — it unblocks Core, UI, and gives Band a target. Build it first, before the real Band run exists.

### 4.2 Frozen findings JSON
The expected `/findings` output for the frozen trace — the UI's no-backend fallback (UR-13) and the smoke-test oracle. Lives at e.g. `fixtures/frozen_findings.json`. Should contain the three expected findings (redundant sub-agent, semantic duplicate, runaway) with stable costs.

## 5. Underspecified core logic (yours to pin down)

### 5.1 `/rerun` savings computation
Do **not** re-execute the agent. Simulate: for each finding with `route=="cache"` and `cacheable==true`, the first occurrence runs (cost kept) and the remaining `count-1` are served from cache (cost saved).

```
cached_cost = total_cost − Σ(finding.dollar_cost for cacheable cache-route findings)
saved       = total_cost − cached_cost
```

Pre-bake the "after" response as a fixture for demo safety, with the live computation as the real path behind it.

### 5.2 Convergence heuristic (drives runaway classification)
For a repetition/cycle group, set `evidence.convergence`:
- All outputs identical, or all are errors/failures → **`"none"`** (runaway).
- Outputs differ in a way that suggests progress toward a result → **`"progressing"`**.

A minimal demo-grade rule: `none` if the set of distinct outputs has size 1 *or* every output matches an error pattern; else `progressing`. Tune against the real trace.

### 5.3 Embeddings setup (for semantic clustering)
Default **local** `sentence-transformers` (e.g. `all-MiniLM-L6-v2`), downloaded at startup, no runtime network dependency. API embeddings are an option but add a network failure mode and a key. If the model fails to load, **skip semantic clustering and ship deterministic-only** (matches the degradation ladder).

## 6. Integration & orchestration (assign to the 4th teammate)

### 6.1 Service topology

```
docker-compose:
  redis     — Streams (trace bus) + cache + dedup set      :6379
  backend   — FastAPI: ingest + detect + router + /findings :8000
              (+ in-process embeddings, LangCache client, Sentry dispatch)
  ui        — React dev server                              :5173
  # Sentry is external SaaS — just a DSN, no container
```

A single `docker-compose up` should bring up redis + backend + ui.

### 6.2 Environment & secrets

| Var | Used by | Notes |
|---|---|---|
| `REDIS_URL` | backend | Streams + cache + dedup |
| `SENTRY_DSN` | backend | unset → Sentry mock mode (SR-9) |
| `LANGCACHE_*` | backend | managed LangCache creds; else DIY Redis cache |
| `OPENAI_API_KEY` | backend / Band | LLM for the run; embeddings if API mode |
| `R_MAX` | backend | runaway threshold (default 10) |
| `CACHE_TTL` | backend | verifier staleness window |

Collect these in one `.env.example` so any teammate can run the stack.

### 6.3 Run & replay
A `replay.py` that reads the frozen trace and `XADD`s each span onto `trace:{run_id}` in order, then emits the `trace_end` sentinel. This deterministically seeds the demo without depending on a live LLM. (Live-mode demo: pace the `XADD`s by the relative timestamps so the incremental detector fires mid-run.)

### 6.4 Demo runbook (run-of-show)
1. `docker-compose up` (redis, backend, ui).
2. `python replay.py --trace fixtures/frozen_trace.json --run run-001`.
3. `POST /analyze { run_id }` (or auto-trigger on `trace_end`).
4. Open the UI at `run-001`.
5. Present the §9 storyboard beats; trigger **Re-run** (cache savings); open the **Sentry** issue.
6. **Backup video** recorded by hour 22 in case live fails.

### 6.5 Smoke test
A script run at hour 16 and again pre-demo: replay frozen trace → `/analyze` → assert findings include all three expected types and `wasted_cost > 0` → assert `/rerun` `saved > 0` → assert a Sentry event (mock) fired. This is your "is the demo still alive?" check.

## 7. Failure modes & fallbacks (unified)

| Failure | Fallback |
|---|---|
| Redis down | Local fixture mode (UI static JSON, Core reads frozen trace from disk) |
| Tokens/model missing on spans | Estimate tokens from text length; default model price |
| `SENTRY_DSN` unset / Sentry unreachable | Mock dispatcher records event + sets fired state (SR-9) |
| Managed LangCache flaky | DIY Redis `SET/GET EX` exact-hash cache |
| Embeddings model fails to load | Skip semantic clustering, deterministic-only |
| No findings produced | UI shows "no waste detected" cleanly; don't crash the banner |
| `/rerun` live path errors | Serve the pre-baked "after" fixture |
| Backend not ready | UI renders from `frozen_findings.json` (UR-13) |

## 8. Hour-0 coordination checklist (lock these before anyone builds)

- [ ] Span schema + Finding schema field names final (`DESIGN_redis` §6).
- [ ] `input_hash` shared module written and imported by Band + Core (3.2).
- [ ] Tool registry authored, tool list matches Band's run (3.1).
- [ ] Price table populated with Band's actual models (3.3).
- [ ] API contract field names locked (3.4).
- [ ] `trace_end` sentinel convention agreed (3.5).
- [ ] Core→Sentry handoff interface chosen: in-process vs Redis channel (`SENTRY_REQUIREMENTS` §4).
- [ ] Alert ack mechanism chosen: `/findings` flag vs `alerts:{run_id}` (SR-8).
- [ ] Frozen trace + frozen findings fixtures produced and shared (4.1, 4.2).
- [ ] `.env.example` populated; everyone can run the stack (6.2).

## 9. Open questions

- Real Sentry project vs mock for the demo (real looks best; mock is safest — arm both).
- Live mode (mid-run alert) in scope, or batch-only?
- `R_MAX` value that cleanly splits wasteful vs runaway on the real trace.
- Who physically presents, and on whose machine does the stack run (decide early; that machine needs all secrets).
