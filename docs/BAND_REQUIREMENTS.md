# Band Section — Requirements

*The demo-trace generator. Produces the deliberately messy multi-agent run that Redundant ingests over Redis Streams and diagnoses on stage.*

Companion to `DESIGN_redis.md`. Span schema and stream convention are defined there (§6.1) and restated here as the hard contract.

---

## 1. Purpose

The Band section produces **one reproducible multi-agent agent run** whose execution trace contains, by construction, every pathology Redundant detects — so the diagnosis, the dollar attribution, and the cache/alert fork all have something real to fire on during the demo. This is the *input* to the whole pipeline; if it doesn't exhibit the pathologies cleanly, nothing downstream has anything to show.

## 2. Consumers (who depends on this)

- **Ingestion / detection** reads the spans off Redis Streams. Needs correct schema + populated tokens/model.
- **Flamegraph UI** renders the span tree. Needs a readable span count and clean nesting.
- **LangCache + verifier** needs at least one *cacheable* redundancy and (stretch) one *side-effecting* one.
- **Sentry path** needs at least one *runaway* loop.

## 3. The contract: how spans reach the system

Each span is one entry on a per-run Redis Stream. One run = one stream, keyed `trace:{run_id}`.

```
XADD trace:run-001 * data '{
  "span_id": "s_07",
  "parent_span_id": "s_03",
  "kind": "tool",                 // "agent" | "llm" | "tool"
  "name": "tool:web_search",
  "tool_name": "web_search",      // null unless kind=="tool"
  "agent_name": "researcher_a",   // owning agent — drives sub-agent grouping
  "input": "population of france 2024",
  "output": "~68 million",
  "input_hash": "a1b2c3",         // hash of NORMALIZED input
  "start_time": 1718877601200,    // epoch ms
  "end_time":   1718877602900,
  "tokens": { "input": 1800, "output": 320 },
  "model": "gpt-4o"               // null for pure tool calls
}'
```

## 4. Functional requirements

Each requirement is written so it's testable against the produced trace.

### Pathologies the run MUST contain

- **BR-1 · Redundant sub-agents (cacheable).** At least **3 distinct agents** (different `agent_name`) MUST each call the **same tool with inputs that normalize to the same `input_hash`**. This is what the repetition detector groups cross-agent and what LangCache caches.
  - *Why identical hash:* the exact-match repetition path and the cache key both key on `(tool_name, input_hash)`. If the inputs differ even slightly after normalization, they won't group. Make these calls genuinely identical.

- **BR-2 · Duplicate subgoal via differently-worded prompts (semantic).** At least **2 LLM/agent spans** MUST pursue the **same intent with different wording** — e.g. *"summarize how France's population is changing"* vs *"give an overview of French population trends."* Same meaning, different surface text → semantic-duplicate candidate.
  - *Why different wording:* this is the case `input_hash` can't catch; it exists specifically to exercise the semantic clustering path.

- **BR-3 · Runaway loop (alert).** One agent MUST call a **flaky tool ≥ 12 times** (clearing the `R_max = 10` threshold) with **non-converging output** — repeated failures or unchanging results, no progress toward a terminal state. This classifies as `runaway` → Sentry.
  - *Why 12, not 10:* clears the threshold with margin so a slightly different run still trips it.

### Baseline so the waste is a *fraction*

- **BR-4 · Legitimate non-redundant work.** The run MUST include several **distinct, non-repeated** tool/LLM calls (different facts, different subgoals) so total run cost meaningfully exceeds wasted cost. The headline is **"$X wasted of $Y total"** — if the run is *all* waste, the number is unconvincing. Target waste ≈ 20–40% of total.

### Span shape

- **BR-5 · Schema conformance.** Every span MUST match §3 exactly. Unknown/missing required fields fail ingestion.
- **BR-6 · Tokens + model populated.** Every `llm` and `tool` span MUST carry real `tokens.{input,output}` and `model`. **The entire dollar story depends on this** — it is the single most important field-level requirement. If Band can't capture real token usage, populate a best-effort estimate rather than null.
- **BR-7 · Stable hashing.** `input_hash` MUST be computed by a normalization the detection side agrees on (lowercase, trim, collapse whitespace, then hash). Coordinate the exact function with the core owner so producer and detector agree.
- **BR-8 · Correct parentage.** `parent_span_id` MUST reflect real call nesting (sub-agent spans under their spawning agent), so the flamegraph nests correctly and sub-agent grouping works.

## 5. Determinism & replay

- **BR-9 · Frozen capture.** The run MUST be captured once to a **frozen JSON trace** that can be replayed into the stream on demand (`XADD` the saved spans in order). The live demo cannot depend on an LLM behaving identically each attempt.
- **BR-10 · Replayable timing (stretch).** For live-mode demos, preserve relative `start_time` gaps so replay can pace `XADD`s and the incremental detector fires mid-run.

## 6. Non-functional requirements

- **BR-11 · Readable size.** Total spans SHOULD be **dozens, not thousands** (~30–60). Big enough to look like a real run, small enough that the flamegraph is legible and the loop is visually obvious.
- **BR-12 · Demo timing.** A full (non-replayed) run SHOULD complete in seconds to low minutes.
- **BR-13 · Realistic costs.** Token counts and models SHOULD be plausible so the dollar figures read as real.

## 7. Reference scenario (build this)

A "research-assistant team." Concrete blueprint that satisfies BR-1 through BR-4:

| Agent | Spans | Pathology / role |
|---|---|---|
| `planner` | 1 LLM call (decompose task) | baseline |
| `researcher_a` | `web_search("population of france 2024")` | BR-1 (identical input) |
| `researcher_b` | `web_search("population of france 2024")` | BR-1 (identical input) |
| `researcher_c` | `web_search("population of france 2024")` | BR-1 (identical input) |
| `researcher_a` | `web_search("france gdp 2024")` | baseline (distinct) |
| `writer` | LLM: *"summarize France's population trend"* | BR-2 (intent A) |
| `writer` | LLM: *"overview of how France's population is changing"* | BR-2 (intent A, reworded) |
| `writer` | LLM: draft the report | baseline (distinct) |
| `fact_checker` | `verify_source(...)` ×12, non-converging | BR-3 (runaway → alert) |

Result: one cacheable cross-agent redundancy (3×), one semantic duplicate, one runaway loop, and enough distinct work that waste is a clear *slice* of total.

## 8. Stretch goals

- **BR-14 · Side-effecting redundancy.** Add a `notifier` agent that calls a **write tool** (`send_email`) redundantly. This lets the demo show the verifier *refusing to cache a side-effecting call* and routing it to `alert` instead — a strong showcase of the cacheability gate.
- **BR-15 · Live emission.** Emit spans to the stream **as they happen** (not just batch at the end) so live-mode `XREADGROUP` detection can fire the Sentry alert before the run finishes.

## 9. Acceptance criteria (definition of done)

- [ ] Detector reports ≥1 **redundant sub-agent** finding (3 cross-agent calls, same `input_hash`) — BR-1.
- [ ] Detector reports ≥1 **semantic-duplicate** candidate — BR-2.
- [ ] Detector reports ≥1 **runaway** finding (`count ≥ 12`, non-converging) routed to `alert` — BR-3.
- [ ] Total run cost > wasted cost; waste lands around 20–40% — BR-4.
- [ ] Every span validates against the §3 schema — BR-5.
- [ ] Every llm/tool span has non-null `tokens` and `model` — BR-6.
- [ ] Redundant calls share an identical `input_hash` after normalization — BR-7.
- [ ] Flamegraph nests correctly from `parent_span_id` — BR-8.
- [ ] Run captured to a frozen JSON trace and replays cleanly via `XADD` — BR-9.
- [ ] Span count ~30–60, flamegraph legible, loop visually obvious — BR-11.

## 10. Band integration — TBD (owner to fill in)

These depend on Band's instrumentation API and need the Band owner to resolve early:

- How does Band expose per-span data (built-in tracing/OTel hooks, or manual emission)?
- Where do we inject the `XADD` — a span exporter/callback, or a post-run dump of Band's trace?
- Does Band capture LLM token usage per call? If not, how do we estimate (BR-6 fallback)?
- Can sub-agent spawning produce distinct `agent_name`s on child spans (needed for BR-1)?
- Can a tool be made deterministically flaky to force the 12× retry (BR-3)?

Resolve the token-capture question (BR-6) in the **hour-0 check** — everything dollar-denominated downstream rides on it.
