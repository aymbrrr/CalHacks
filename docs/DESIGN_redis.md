# Redundant — Design Doc (Redis-centric build)

*Owner: Redis + Core. Arize replaced by Redis Streams as the trace bus. Step-by-step roadmap embedded below (§9).*

---

## 1. One-liner

Redundant reads an agent's entire execution trace as a process over time and surfaces **behavioral waste** that call-level tools structurally can't see — repeated tool calls, re-derived subgoals, redundant sub-agents — then pins a dollar cost to each and routes it to the right fix. Traces arrive over **Redis Streams**; remediation lands in **LangCache** and **Sentry**.

## 2. Core insight (protect this)

Two kinds of repeated work in an agent run, and they are *not the same problem*:

- **Harmless-but-wasteful redundancy** → a caching problem → **LangCache**.
- **A genuine runaway loop** → a reliability incident → **Sentry alert**.

A stuck agent isn't something you cache around; it's something you page someone about. That fork is the entire point of the product.

## 3. Positioning — Redis sits at *both* ends

Replacing Arize with Redis Streams makes the whole pipeline Redis-centric, which is exactly the slice I own:

```
Band (agent run)
   │  XADD span events
   ▼
Redis Streams  ──────────▶  Redundant  ──────────┬──▶ LangCache (cache the waste)   ◀── Redis again
 (trace bus)        ingest + diagnose            └──▶ Sentry     (alert the runaways)
```

Redis appears twice — as the **trace bus** (Streams) and as the **cache** (LangCache). One consumer pulls spans off a stream; one verifier-gated cache absorbs the wasteful repeats. Both are mine.

Versus call-level caches: LangCache answers *"is this one query like a past one?"* Redundant works on the **whole trace** — the call graph and the sequence of span intents — so it sees loops, duplicate subgoals across differently-worded prompts, and sub-agents independently asking the same thing. Redundant is the layer that *decides* what LangCache should cache.

## 4. My scope vs. team handoffs

**I own:**
- Redis Streams **ingestion** (consumer → normalized spans).
- The **detection engine** (repetition, cycle, semantic).
- **Cost attribution** and the `$wasted / $total` rollup.
- The **routing brain** (wasteful vs. runaway → sets each finding's `route`).
- **LangCache + the verifier** (the cache path and its safety gates).
- The **FastAPI backend** serving `/findings` and the re-run/remediate path.

**Handoffs (not mine, but I define the interface):**
- *Band trace generation* — a teammate produces the messy run; I define the `XADD` span convention they emit (§6.1, §7.1).
- *Flamegraph UI* — consumes my `/findings` JSON and my re-run savings. I keep that output stable.
- *Sentry firing* — I classify (`route == "alert"`); the Sentry owner fires. I emit, they page.

## 5. Architecture

```
                 ┌──────────────────────────────┐
 Band agents ───▶│  Redis Stream: trace:{run}   │   one entry per span
                 └──────────────┬───────────────┘
                                │ XRANGE (batch)  /  XREADGROUP (live)
                                ▼
                 ┌──────────────────────────────┐
                 │  Ingestion → Normalized Trace │
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │       Detection Engine        │
                 │  repetition · cycle · semantic│
                 │  + cost attribution           │
                 └──────────────┬───────────────┘
                                │ Findings[]
                 ┌──────────────┴───────────────┐
                 ▼                               ▼
        ┌─────────────────┐            ┌──────────────────────┐
        │  /findings (UI) │            │   Routing Router      │
        └─────────────────┘            │  cache → LangCache    │
                                       │  alert → Sentry owner │
                                       └──────────┬───────────┘
                                                  ▼
                                       ┌──────────────────────┐
                                       │ LangCache + verifier  │  (Redis)
                                       │  cacheability gate     │
                                       │  staleness gate        │
                                       └──────────────────────┘
```

A FastAPI backend holds the trace and serves `Findings[]` as JSON. UI and router both consume that one contract.

## 6. Data contracts (lock at hour 0)

### 6.1 Span — as a Redis Stream entry

Producer (Band side) emits one entry per span, span JSON in a single `data` field:

```
XADD trace:run-001 * data '{
  "span_id": "s_07",
  "parent_span_id": "s_03",
  "kind": "tool",                       // "agent" | "llm" | "tool"
  "name": "tool:web_search",
  "tool_name": "web_search",            // null unless kind=="tool"
  "agent_name": "researcher",           // for sub-agent grouping
  "input": "population of france 2024",
  "output": "~68 million",
  "input_hash": "a1b2c3",               // hash of normalized input
  "start_time": 1718877601200,          // epoch ms
  "end_time":   1718877602900,
  "tokens": { "input": 1800, "output": 320 },
  "model": "gpt-4o"                     // null for pure tool calls
}'
```

> **Hour-0 check:** confirm `tokens` and `model` are present per span. The dollar story dies without them. Fallback: estimate tokens from text length.

### 6.2 Finding (I own this shape)

```json
{
  "finding_id": "f_12",
  "type": "repetition",                 // "repetition" | "cycle" | "semantic_duplicate"
  "span_ids": ["s_07", "s_11", "s_15"],
  "representative_span_id": "s_07",
  "count": 3,
  "description": "web_search called 3x with near-identical args across 3 sub-agents",
  "token_cost": { "input": 5400, "output": 960 },
  "dollar_cost": 0.21,                   // wasted = cost of all but one instance
  "severity": "wasteful",                // "wasteful" | "runaway"
  "route": "cache",                      // "cache" | "alert"
  "cacheable": true,                     // false if any implicated tool is side-effecting
  "evidence": { "similarity": 0.94, "cycle_path": null, "convergence": "none" }
}
```

## 7. Components I own (detail)

### 7.1 Redis Streams ingestion

**Batch mode (must-have).** Agent finishes, read the whole stream:

```python
entries = r.xrange("trace:run-001", min="-", max="+")
spans = [json.loads(fields["data"]) for _id, fields in entries]
trace = build_trace(spans)   # parent/child tree + directed call graph
```

**Live mode (upside, §8).** Consumer group reads spans as they land, enabling alerts *before the run finishes*:

```python
r.xgroup_create("trace:run-001", "redundant", id="0", mkstream=True)
resp = r.xreadgroup("redundant", "worker-1", {"trace:run-001": ">"}, count=50, block=2000)
# feed new spans into incremental detector; r.xack(...) each processed entry
```

This replaces the entire OTel→Arize adapter with an `XRANGE` loop. Much less to fight.

### 7.2 Detection engine — two distinct detectors + a fragile third

The most common pathology (same tool 10×) is a **frequency** pattern, not a topological cycle. Build them separately.

**A. Repetition detector (frequency).** Group spans by `(tool_name, input_hash)` or near-duplicate input (token-set Jaccard / embedding cosine). Group size N ≥ 2 → finding; waste = cost of (N−1). If members span different `agent_name`s → tag as *redundant sub-agent*.

**B. Cycle detector (structure).** Directed graph over the call tree (edge A→B when B follows A's result); `networkx.simple_cycles` / SCC. Catches A→B→A the frequency pass misses.

**C. Semantic clustering (impressive, fragile).** Embed each span's `input`, cluster on cosine distance; cross-agent clusters with the same intent = semantic-duplicate subgoals. Gate behind a high threshold, present as *candidates*. **Hard stop hour 14** — ship deterministic-only if noisy.

### 7.3 Cost attribution

```
span_cost = tokens.input * price_in(model) + tokens.output * price_out(model)
finding.dollar_cost = Σ span_cost over implicated spans − (one kept instance)
```

Loop of N → waste = `(N−1) × unit_cost`. Headline = `Σ dollar_cost / Σ total cost` → **"$X wasted of $Y."** Hardcode a price table for the 2–3 demo models.

### 7.4 Routing brain (wasteful vs. runaway)

| Condition | Severity | Route |
|---|---|---|
| `count ≥ R_max` (e.g. 10) | runaway | alert |
| `evidence.convergence == "none"` (outputs not changing) | runaway | alert |
| Any implicated tool is side-effecting (allowlist) | runaway | alert |
| Everything else redundant (incl. all semantic dups) | wasteful | cache |

Judge answer: *"Low-count, convergent, read-only redundancy is cacheable waste; high-count or non-converging or side-effecting repetition is a reliability incident."*

### 7.5 LangCache + verifier (Redis as cache)

Keyed on `(tool_name, input_hash)`. The verifier is two explicit gates — **not** side-effect inference:

1. **Cacheability gate (write-time):** cache only if the tool is in the **read-only allowlist** (annotated tool registry: `web_search: read`, `send_email: write`, …). Anything else → never cached → flips to `alert`.
2. **Staleness gate (read-time):** entry carries a TTL + `input_hash`; serve only on exact hash match within TTL, else miss and run for real.

**Fallback if managed LangCache misbehaves (I own all of Redis, so this is in my control):**
- Exact cache: `SET cache:{tool}:{input_hash} <result> EX <ttl>` / `GET` on read. Guaranteed to work.
- Semantic cache (upside): store embeddings in Redis, `FT.SEARCH` vector index for nearest neighbor under threshold.

**Make the hit visible:** on demo re-run, the duplicated call is served from cache, cost drops, and the saved dollars land in the UI. Without this, the cache work is invisible on stage.

## 8. Live mode (the Streams upside)

Because Streams is a live append log, the incremental detector can fire a Sentry alert the moment a loop crosses `R_max` — *while the agent is still running*. That's a stronger demo than post-hoc ("we caught it mid-run and killed it") and it's a real advantage Streams has over a post-hoc trace store. Treat batch mode as the must-have and live mode as the flourish if hours 16–20 allow.

## 9. Step-by-step roadmap (my 24h sequence)

Critical-path note: my **deterministic detection + `/findings`** unblocks the UI and the router, so it ships *before* Redis caching depth. I build the detector against a **frozen JSON trace** first so I'm not blocked on the stream consumer.

**Step 0 — Setup (hr 0–2)**
- Drive the Finding schema (§6.2) with the team; define the `XADD` span convention for the Band teammate.
- Scaffold the detection package + FastAPI `/findings` returning mock Findings.
- Hand-author a **frozen trace** JSON (all 3 pathologies) to build against.
- Smoke-test Redis: `XADD`/`XRANGE` round-trip *and* `SET`/`GET`.
- *Done when:* `/findings` serves mock data and Redis read/write both work.

**Step 1 — Deterministic core against the frozen trace (hr 2–6)**
- Trace loader: spans → in-memory tree + directed call graph.
- Repetition detector (group by tool+input_hash / near-dup; cross-agent tag).
- Cycle detector (`networkx.simple_cycles`).
- Cost attribution + `$wasted/$total` rollup.
- *Done when:* frozen trace → real Findings[] with dollars, live on `/findings`. **This unblocks UI + router.**

**Step 2 — Redis Streams ingestion (hr 6–9)**
- Batch consumer: `XRANGE trace:{run} - +` → same normalized spans the detector already eats.
- Swap the frozen trace for the live stream read; detector code unchanged.
- *Done when:* a real Band stream flows end-to-end into Findings[].

**Step 3 — LangCache skeleton + verifier stub (hr 9–12)**
- Cache key `(tool_name, input_hash)`; write path caches a wasteful finding's result, read path looks it up.
- Stubbed verifier = hardcoded read-only allowlist.
- *Done when:* a wasteful finding round-trips through the cache.

**Step 4 — Routing brain (hr 12–14)**
- Wasteful-vs-runaway logic (§7.4): `R_max`, convergence check, side-effect override → set `severity` + `route`.
- Emit `route == "alert"` findings for the Sentry owner.
- *Done when:* every finding carries correct `severity` + `route`.

**Step 5 — Real verifier + visible savings (hr 14–17)**
- Two gates: read-only allowlist (write-time) + TTL/input_hash (read-time).
- Tool registry (the allowlist).
- Re-run path: duplicated call served from cache → cost drops → savings land in UI (coordinate visual with UI person).
- *Done when:* re-run shows a cache HIT and dollars saved on screen.

**Step 6 — Optional depth (hr 17–20, only if core is solid)**
- Semantic clustering (candidates) — **hard stop hr 14 decision already made; only resume here if it was working.**
- Live mode: `XREADGROUP` incremental detection → fire Sentry mid-run.
- *Done when:* whichever upside is stable; otherwise skip.

**Step 7 — Freeze + demo (hr 20–24)**
- Feature freeze; bulletproof the one golden path.
- Apply degradation ladder to my slice (below).
- Help record the backup video; prep the three judge answers.

## 10. Risks & degradation ladder

| Risk | Mitigation |
|---|---|
| Stream consumer slips | Frozen trace built first; detector is consumer-agnostic |
| Managed LangCache flaky | DIY exact-hash Redis cache (`SET/GET EX`) — fully in my control |
| Tokens/model missing → no $ | Hour-0 check; estimate from text length |
| Semantic clustering mislabels | High threshold, "candidate" framing, hard stop hr 14 |
| "Cycle detection" misses repeats | Two separate detectors (frequency + structure) |
| Verifier hand-waving | Allowlist + TTL, stated plainly; no inference claimed |

**Cut in this order if behind:** semantic clustering → live mode → managed LangCache (drop to DIY exact-hash) → convergence sophistication (fall back to plain `R_max`) → TTL staleness (exact-hash only). **Never cut:** deterministic detectors, cost attribution, `/findings`, one visible cache hit, one `route=="alert"` handoff to Sentry.

## 11. Tech stack (my slice)

| Layer | Choice |
|---|---|
| Trace bus | Redis Streams (`XADD` producer, `XRANGE`/`XREADGROUP` consumer) |
| Detection | Python; `networkx` (cycles); `sentence-transformers` + `scikit-learn` (semantic); `tiktoken` (tokens) |
| Backend | FastAPI serving `Findings[]` + re-run endpoint |
| Cache | Redis LangCache (primary) or DIY Redis `SET/GET`/`FT.SEARCH` (fallback) |
| Redis client | `redis-py` |

## 12. Open questions

- Does the Band export populate per-span tokens/model, or do I estimate?
- Batch-only, or is live `XREADGROUP` mode worth the demo flourish?
- `R_max` value that cleanly splits wasteful vs. runaway on the real trace — tune once it exists.
- Embedding model: local (`sentence-transformers`, no network) vs. API. Default local for reliability.
