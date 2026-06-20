# Redundant — Design Doc

*A trace-level profiler for AI agent runs. Hackathon build, 24h, 4 people.*

---

## 1. One-liner

Redundant reads an agent's entire execution trace as a process over time and surfaces **behavioral waste** that call-level tools structurally can't see — repeated tool calls, re-derived subgoals, and redundant sub-agents — then pins a dollar cost to each one and routes it to the right fix.

## 2. The core insight (protect this)

There are two kinds of repeated work in an agent run, and they are *not the same problem*:

- **Harmless-but-wasteful redundancy** → a caching problem. Send it to **LangCache**.
- **A genuine runaway loop** → a reliability incident. Fire a **Sentry alert**.

A stuck agent isn't something you cache around; it's something you page someone about. That fork is the entire point of the product. Everything else is plumbing in service of making that distinction visible and cheap.

## 3. Positioning

Call-level semantic caches (Redis LangCache) answer *"is this one query similar to a past one?"* Redundant works one level up, on the **trace**: it reads the whole call graph and the sequence of span intents, so it can see structure a single-call view cannot — loops, duplicate subgoals across differently-worded prompts, and sub-agents independently asking the same question.

Redundant is **complementary** to LangCache, not competitive. It's the diagnosis layer that decides *what* should be cached and *what* should be alerted on. Position in the stack:

```
Arize (trace in) → Redundant (diagnose) → LangCache (cache the waste) + Sentry (alert on the runaways)
                                    ↑
                          Band generates the demo trace
```

## 4. Goals & non-goals (24h scope)

**Goals**
- Ingest an agent trace (OpenTelemetry / Arize) into a normalized internal model.
- Detect three pathologies: repeated tool calls, structural cycles, semantic-duplicate subgoals.
- Attribute a dollar cost to each finding.
- Render the run as a flamegraph with every finding lit up red and its cost shown.
- Route each finding: wasteful → LangCache (gated by a verifier), runaway → Sentry alert.
- Demo the full chain on a deliberately messy multi-agent Band run.

**Non-goals (explicitly out of scope for the hackathon)**
- Production-grade ingestion of arbitrary trace formats. We support *our* normalized schema; one real adapter (Arize/OTLP) is enough.
- A general-purpose side-effect inference engine. The verifier uses a **configured tool allowlist**, not inference.
- Auto-applying fixes to a live agent. We *recommend and route*; we don't rewrite the agent.
- Multi-trace / fleet analytics. Single trace in, single diagnosis out.

## 5. Architecture

```
            ┌──────────────┐
  Band run  │  Ingestion   │   OTel spans → normalized Trace
 ──────────▶│  (OTLP/Arize)│ ─────────────────────────┐
            └──────────────┘                          │
                                                       ▼
                                          ┌─────────────────────────┐
                                          │     Detection Engine     │
                                          │  • repetition detector   │
                                          │  • cycle detector        │
                                          │  • semantic clustering   │
                                          │  • cost attribution      │
                                          └────────────┬─────────────┘
                                                       │ Findings[]
                            ┌──────────────────────────┼──────────────────────────┐
                            ▼                           ▼                          ▼
                    ┌───────────────┐         ┌───────────────────┐      ┌──────────────────┐
                    │  Flamegraph   │         │  Remediation Router│      │   (cost rollup)  │
                    │  UI (React)   │         │  wasteful → cache  │      │  $ wasted / total│
                    │  red = finding│         │  runaway  → alert  │      └──────────────────┘
                    └───────────────┘         └─────────┬─────────┘
                                                        │
                                       ┌────────────────┴────────────────┐
                                       ▼                                 ▼
                              ┌─────────────────┐               ┌─────────────────┐
                              │  LangCache       │               │  Sentry          │
                              │  + verifier gate │               │  alert / incident│
                              └─────────────────┘               └─────────────────┘
```

A FastAPI backend holds the trace and serves `Findings[]` as JSON. The UI and the router both consume that one JSON contract.

## 6. Data contracts (lock these at hour 0)

Everything in the system is built against these two shapes. Nail them before anyone writes real logic, and let people mock against them.

### 6.1 Normalized Span / Trace

```json
{
  "trace_id": "run-001",
  "spans": [
    {
      "span_id": "s_07",
      "parent_span_id": "s_03",
      "kind": "tool",                       // "agent" | "llm" | "tool"
      "name": "tool:web_search",
      "tool_name": "web_search",            // null unless kind=="tool"
      "agent_name": "researcher",           // owning agent, for sub-agent grouping
      "input": "population of france 2024", // normalized text of args/prompt
      "output": "~68 million",              // normalized text of result
      "input_hash": "a1b2c3",               // hash of normalized input, for exact-match dedup
      "start_time": "2026-06-20T10:00:01.2Z",
      "end_time":   "2026-06-20T10:00:02.9Z",
      "tokens": { "input": 1800, "output": 320 },
      "model": "gpt-4o",                    // null for pure tool calls
      "attributes": { }                     // raw OTel GenAI attributes, passthrough
    }
  ]
}
```

> **Critical hour-0 check:** confirm `tokens` and `model` actually survive ingestion. The entire dollar story dies if they don't. If Band/Arize doesn't populate them per span, decide the fallback (estimate from text length) *now*, not at hour 16.

### 6.2 Finding

```json
{
  "finding_id": "f_12",
  "type": "repetition",                 // "repetition" | "cycle" | "semantic_duplicate"
  "span_ids": ["s_07", "s_11", "s_15"], // all spans implicated
  "representative_span_id": "s_07",
  "count": 3,
  "description": "web_search called 3x with near-identical args across 3 sub-agents",
  "token_cost": { "input": 5400, "output": 960 },
  "dollar_cost": 0.21,                   // wasted cost = cost of all but one instance
  "severity": "wasteful",                // "wasteful" | "runaway"
  "route": "cache",                      // "cache" | "alert"
  "cacheable": true,                     // false if any implicated tool is side-effecting
  "evidence": {
    "similarity": 0.94,                  // for semantic dups
    "cycle_path": null,                  // ["s_a","s_b","s_a"] for cycles
    "convergence": "none"                // "none" | "progressing" — drives runaway call
  }
}
```

## 7. Detection engine

### 7.1 Two distinct detectors (do not conflate)

The single most common pathology — an agent calling the same tool ten times — is **not** a topological cycle. It's a frequency pattern. Build these as two separate passes:

**A. Repetition detector (frequency)**
- Group spans by `(tool_name, input_hash)` *or* by `(tool_name, near-duplicate input)`.
- "Near-duplicate" = normalized-input similarity above a threshold (cheap: token-set Jaccard, or embedding cosine if already computing embeddings).
- A group of size N ≥ 2 is a repetition finding. Waste = cost of (N − 1) instances.
- Sub-case: if the N spans belong to **different `agent_name`s**, label it a *redundant sub-agent* finding (same question asked independently).

**B. Cycle detector (structure)**
- Build a directed graph over the call tree: nodes = tools/agents, edge A→B when B is invoked in the reasoning that follows A's result.
- Run cycle detection (`networkx.simple_cycles` or Tarjan SCC). A back-edge that revisits a node is a structural loop.
- This catches A→B→A ping-pong that the frequency pass misses.

### 7.2 Semantic clustering (the impressive, fragile half)

- Embed each span's `input` (intent) with sentence-transformers or an embeddings API.
- Cluster (agglomerative / DBSCAN on cosine distance). Clusters with members from different prompts/agents but the same intent = **semantic-duplicate subgoals**.
- **Degradation rule:** this is the part most likely to mislabel on stage. Gate it behind a high similarity threshold and present its outputs as *candidate* duplicates, visually distinct from the deterministic findings. If at the hour-14 stop it's noisy, ship deterministic-only and frame semantic as "experimental."

### 7.3 Cost attribution

```
span_cost = tokens.input  * price_in(model)
          + tokens.output * price_out(model)

finding.dollar_cost = (sum of span_cost over implicated spans)
                      - (cost of one kept instance)        # the work you'd still do once
```

For a loop of N identical calls, waste = `(N − 1) × unit_cost`. The headline number is `Σ finding.dollar_cost` over `Σ total run cost` → **"$X wasted of $Y."** Keep a small hardcoded price table for the 2–3 models in the demo.

### 7.4 Wasteful vs. runaway (the routing brain)

This binary drives the LangCache/Sentry fork. Defined, defensible rule:

| Condition | Severity | Route |
|---|---|---|
| Repetition/cycle with `count ≥ R_max` (e.g. 10) | runaway | alert |
| Repetition/cycle where `evidence.convergence == "none"` (outputs not changing, no progress) | runaway | alert |
| Any implicated tool is side-effecting (per allowlist) | runaway* | alert |
| Everything else redundant (incl. all semantic duplicates) | wasteful | cache |

\*Side-effecting redundancy is never a cache candidate — caching a write is dangerous — so it routes to alert even at low counts.

One-sentence answer for judges: *"Low-count, convergent, read-only redundancy is cacheable waste; high-count or non-converging or side-effecting repetition is a reliability incident."*

## 8. The verifier (gating LangCache)

The verifier is **not** a magic side-effect detector. It's two explicit gates around the cache:

1. **Cacheability gate (write-time).** A tool is cacheable only if it's in the **idempotent/read-only allowlist** — a small annotated tool registry we configure (`web_search: read`, `db_write: write`, `send_email: write`, …). Anything not on the read list is treated as side-effecting and never cached.
2. **Staleness gate (read-time).** Each cache entry carries a TTL and the `input_hash`. A read is served only on exact `input_hash` match *and* within TTL; otherwise it's a miss and the call runs for real.

LangCache is keyed on `(tool_name, input_hash)`. The verifier sits in front of both the write and the read. This is honest, demoable, and survives the obvious "how do you know it's safe to cache?" question.

## 9. Demo design

**The messy trace (built on Band).** A small research-assistant team:
- A planner spawns 3 sub-agents that each *independently* call `web_search` for the same fact → redundant sub-agent finding (cacheable).
- One agent re-derives the same subgoal through two differently-worded prompts → semantic duplicate (cacheable).
- One agent hits a flaky tool and retries it 12× with no changing output → runaway loop (alert).

Don't over-build the Band agent; a deliberately bad prompt that naturally loops beats a hand-crafted masterpiece. Freeze the resulting trace as JSON so the rest of the team isn't blocked on live ingestion.

**The 3-minute storyboard.**
1. *0:00* — "Here's a multi-agent run. Looks fine. It cost \$Y and nobody knows why." Flamegraph loads.
2. *0:30* — Red bars light up. Headline: **"\$X of \$Y was wasted."**
3. *1:00* — Click the red sub-agent cluster: "3 agents asked the same question, \$0.21 — cache candidate." → show it routed to LangCache; re-run, cost drops.
4. *1:45* — Click the deep-red bar: "tool retried 12×, no convergence — this isn't caching, it's an incident." → Sentry alert fires on screen.
5. *2:30* — Land the chain: Arize traced it, Redundant diagnosed it, LangCache + Sentry remediated it. The dollars saved are the payoff of the diagnosis, not the headline.

**Record a backup video by hour 22.** Live demos die.

## 10. Tech stack

| Layer | Choice |
|---|---|
| Ingestion | Python, OpenTelemetry SDK, OTLP / Arize exporter |
| Detection | Python; `networkx` (graph/cycles); `sentence-transformers` or embeddings API + `scikit-learn` (clustering); `tiktoken` (tokens) |
| Backend | FastAPI serving `Findings[]` JSON |
| Frontend | React + flamegraph (`d3-flame-graph`, speedscope-style, or custom SVG); reads findings, overlays red |
| Remediation | Redis LangCache client; Sentry SDK |
| Trace gen | Band (messy multi-agent run) |

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Live Arize/OTel ingest slips | **Frozen mock trace** in the normalized schema, in everyone's hands by hour 2; real adapter swaps in later |
| Token/model metadata missing → no \$ | Verify at hour 0; fallback = estimate tokens from text length |
| Semantic clustering mislabels on stage | High threshold; "candidate" framing; hard stop at hour 14; ship deterministic-only if noisy |
| "Cycle detection" misses repeated calls | Two separate detectors — frequency *and* structure |
| Verifier hand-waving | It's an allowlist + TTL, stated plainly; no inference claimed |
| Integration eats the last hours | Feature freeze at hour 16; one golden demo path made bulletproof |
| 4 people awake 24h → broken demo at hr 23 | Staggered rest in shifts during hours 8–20 |

**Degradation ladder (cut in this order if behind):** semantic clustering → verifier sophistication (drop to plain allowlist) → live Band ingestion (use frozen trace) → extra Sentry alert types. **Never cut:** deterministic detector, cost attribution, flamegraph, the single clean Sentry fire. That quartet *is* the pitch.

## 12. Open questions

- Does the Band/Arize export populate per-span token usage, or do we estimate?
- What `R_max` count cleanly separates "wasteful" from "runaway" on the demo trace? Tune once the real trace exists.
- Embedding model: local (`sentence-transformers`, no network dependency) vs. API (better quality, network risk)? Default local for reliability.

## 13. Future work (the "if this were real" slide)

- Auto-generated fix PRs (insert a cache call / a loop guard) instead of just routing.
- Cross-run fleet view: which pathologies recur across an agent's history.
- Trace-format adapters beyond Arize (LangSmith, Langfuse, raw OTLP).
- A learned side-effect classifier to replace the hand-annotated allowlist.
