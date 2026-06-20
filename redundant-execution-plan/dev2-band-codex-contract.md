# Dev 2 Band Multi-Agent Demo Contract for Codex

This document is the single source of truth for Codex to implement the Band multi-agent demo workflow for Redundant.

It combines the strongest requirements from the Band trace requirements and the Dev 2 Band workflow plan:

- Band must be visibly central to the demo.
- The workflow must generate a deterministic pathological trace that Redundant can ingest.
- Every expensive action must go through the Redundant runtime wrappers.
- The demo must prove exact reuse, semantic reuse, unsafe reuse blocking, loop/runaway alerting, cost attribution, and replayability.

## 1. Owner Goal

Dev 2 owns the Band-facing multi-agent workflow.

The goal is to make Band look like the natural place where agent collaboration happens, and Redundant like the system that detects and prevents waste inside that collaboration.

The demo must clearly show multiple Band agents collaborating in a shared room, accidentally repeating work, and Redundant catching or reusing safe duplicate calls across agents.

Required visible line in the UI or terminal:

```text
ReportAgent reused ResearchAgent's prior result.
```

## 2. What Dev 2 Owns

Dev 2 owns:

- Band room setup.
- Band agent definitions.
- Agent prompts.
- Agent-to-agent context exchange.
- Scripted redundant work in the multi-agent flow.
- Baseline Band run with waste enabled.
- Redundant-enabled Band run using the same task.
- Proof that all agents call the same Redundant runtime/backend.
- Demo fallback path when live Band credentials or APIs fail.
- Frozen trace JSON that can be replayed into Redis Streams.

Dev 2 does not own:

- Redundant runtime internals.
- Cache decision engine internals.
- Semantic verifier internals.
- Terac eval/labeling internals.
- Final UI implementation.

Dev 2 consumes wrappers, cache decisions, verifier decisions, Redis events, and demo tooling from the other devs.

## 3. Inputs From Other Devs

Dev 1 provides:

- `redundant.llm()` wrapper.
- `redundant.tool()` wrapper.
- Demo tools:
  - `search_docs(query)`
  - `summarize_page(url_or_text)`
  - `scan_repo(topic)`
  - `compare_tools(tool_a, tool_b)`
  - `verify_source(source_or_claim)` or equivalent flaky verification tool.
- Exact reuse decisions.
- Semantic reuse decisions.
- Side-effect and loop warnings.
- Redis/Redis Streams-backed event emission.
- Final call records with cost, latency, source call, and explanation.

Dev 3 provides:

- Terac labels/eval for semantic reuse safety.
- Verifier story or simulated verifier behavior if live Terac flow is not ready.
- One unsafe semantic candidate that Redis/semantic matching finds but the verifier blocks.

Dev 4 provides:

- Live run timeline.
- Burn meter.
- Duplicate clusters.
- Final report.
- Band collaboration view or sponsor tab.

## 4. Demo Task

Use this task unless the team explicitly changes the source plan:

```text
Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation.
```

The task must run in two modes:

1. Baseline Band run with waste enabled.
2. Redundant-enabled Band run with the same task.

The second run must show:

- Exact reuse.
- Semantic reuse.
- Cross-agent reuse.
- Unsafe semantic block.
- Runaway loop alert.
- Cost savings attribution.
- Replay path from saved trace JSON.

## 5. Required Band Room Setup

Create a Band room with at least four agents.

Required agents:

- `ResearchAgent`
  - Searches, scans, summarizes sources, and posts findings into the room.
- `ReportAgent`
  - Reads room context, asks overlapping questions, and writes the final recommendation.
- `VerifierAgent`
  - Checks source quality and produces intentionally repeated flaky verification calls for the runaway alert path.
  - This is demo/story support. Runtime verifier ownership remains Dev 1/Dev 3.
- `AuditAgent`
  - Performs one deliberately overlapping exact tool call so the system has at least three distinct agents producing the same exact cacheable redundancy.

The minimum two-agent Band sponsor story is not enough. The trace must include at least three distinct agents making the same exact cacheable call so Redundant can prove cross-agent exact reuse.

## 6. Required Agent Flow

Implement this flow:

1. Start a shared Band room for one `run_id`.
2. Post the user task into the room.
3. `ResearchAgent` creates a short research plan in Band.
4. `ResearchAgent` calls wrapped tools through Redundant.
5. `ResearchAgent` posts findings back into Band.
6. `ReportAgent` reads Band context.
7. `ReportAgent` asks overlapping questions and calls the same wrapped tools.
8. `AuditAgent` performs one deliberately overlapping exact query.
9. Redundant reuses at least one prior `ResearchAgent` result for `ReportAgent`.
10. `VerifierAgent` performs a flaky/non-converging verification loop at least 12 times.
11. The system emits a runaway loop warning or alert event.
12. `ReportAgent` writes a short recommendation in Band.
13. The UI or terminal shows the final savings report.
14. Save the completed trace as frozen JSON.
15. Provide a replay command that re-emits the frozen trace into Redis Streams.

## 7. Required Scripted Waste

The workflow must contain all of the following scripted pathologies.

### 7.1 Exact Cross-Agent Reuse

At least three distinct agents must call the same tool with inputs that normalize to the same `input_hash`.

Required exact duplicate:

```text
ResearchAgent.search_docs("agent cost optimization redis sentry")
ReportAgent.search_docs("agent cost optimization redis sentry")
AuditAgent.search_docs("agent cost optimization redis sentry")
```

Expected Redundant behavior:

```text
EXACT_REUSE
```

This is the strongest cacheability story. Do not rely only on semantic similarity here. These calls must be genuinely identical after normalization.

### 7.2 Semantic Cross-Agent Reuse

At least two agents must pursue the same intent with different wording.

Required semantic overlap:

```text
ResearchAgent.scan_repo("cached tool wrapper")
ReportAgent.scan_repo("tool cache decorator")
```

Expected Redundant behavior:

```text
SEMANTIC_REUSE
```

This proves that Redundant can catch reuse beyond exact hash matching.

### 7.3 Summary Reuse

At least two agents must summarize the same source.

Required summary overlap:

```text
ResearchAgent.summarize_page(same_source)
ReportAgent.summarize_page(same_source)
```

Expected Redundant behavior:

```text
EXACT_REUSE
```

If the summary prompts differ slightly, safe semantic reuse is acceptable, but exact reuse is preferred.

### 7.4 Unsafe Semantic Block

Include one similar-looking request that should not be reused because it is not actually equivalent or safe.

Example:

```text
ResearchAgent.search_docs("Redis cache invalidation strategies for agent tool calls")
ReportAgent.search_docs("Sentry alert routing strategies for runaway agents")
```

Expected Redundant behavior:

```text
BLOCKED_BY_VERIFIER
```

or:

```text
UNSAFE_SEMANTIC_BLOCK
```

The point is to show that semantic matching alone is not enough and that the verifier can reject unsafe reuse.

### 7.5 Runaway Loop Alert

`VerifierAgent` must call a flaky or non-converging tool at least 12 times.

Required loop:

```text
VerifierAgent.verify_source(...) x 12
```

The outputs should show repeated failures, unchanged uncertainty, or no progress toward a terminal state.

Expected Redundant behavior:

```text
RUNAWAY_LOOP_ALERT
```

or:

```text
ALERT
```

A three-call loop is not enough. The loop must clear an `R_max = 10` style threshold with margin.

### 7.6 Legitimate Non-Redundant Work

The run must also include several distinct useful calls so the final waste number is a fraction of the total cost, not the entire cost.

Include examples like:

```text
ResearchAgent.search_docs("LangChain agent tracing cost optimization")
ResearchAgent.search_docs("Sentry performance monitoring agent failures")
ReportAgent.compare_tools("Redis", "Sentry")
ReportAgent.llm("draft final recommendation")
```

Target waste:

```text
20% to 40% of total run cost
```

The final report should be able to say something like:

```text
$X wasted of $Y total
```

## 8. Redundant Runtime Integration

Every expensive action from every Band agent must go through the Redundant wrappers.

Use this shape for LLM calls:

```ts
redundant.llm({
  runId,
  agentId,
  messages,
  model,
  metadata
})
```

Use this shape for tool calls:

```ts
redundant.tool({
  runId,
  agentId,
  toolName,
  args,
  cacheability,
  metadata
})
```

Dev 2 must ensure:

- All agents share the same `run_id`.
- Each call has the correct `agent_id`.
- All agents use the same Redundant runtime/backend.
- Cross-agent reuse can connect `ReportAgent` calls to `ResearchAgent` source calls.
- Band messages can reference Redundant decisions when useful.
- Side-effecting calls are not auto-replayed.
- Fake or dry-run side-effect tools are clearly marked as such.

## 9. Redis Stream Span Contract

Every span must be emitted to a per-run Redis Stream.

Stream key:

```text
trace:{run_id}
```

Example:

```redis
XADD trace:run-001 * data '{
  "span_id": "s_07",
  "parent_span_id": "s_03",
  "kind": "tool",
  "name": "tool:search_docs",
  "tool_name": "search_docs",
  "agent_name": "ResearchAgent",
  "input": "agent cost optimization redis sentry",
  "output": "...",
  "input_hash": "a1b2c3",
  "start_time": 1718877601200,
  "end_time": 1718877602900,
  "tokens": { "input": 1800, "output": 320 },
  "model": "gpt-4o"
}'
```

Required span fields:

- `span_id`
- `parent_span_id`
- `kind`
- `name`
- `tool_name`
- `agent_name`
- `input`
- `output`
- `input_hash`
- `start_time`
- `end_time`
- `tokens.input`
- `tokens.output`
- `model`

Rules:

- `kind` must be one of `agent`, `llm`, or `tool`.
- `tool_name` must be null unless `kind == "tool"`.
- `model` must be populated for every `llm` and `tool` span.
- `tokens` must be populated for every `llm` and `tool` span.
- If real token usage is unavailable, use a plausible estimate instead of null.
- `parent_span_id` must reflect real call nesting.
- Sub-agent spans must appear under the agent or room span that spawned them.
- Span count should be roughly 30 to 60 total.

## 10. Hashing and Normalization Contract

The exact reuse path and cache key depend on stable hashing.

Use this normalization before hashing:

1. Lowercase.
2. Trim leading/trailing whitespace.
3. Collapse repeated internal whitespace to one space.
4. Hash the normalized string.

Required invariant:

```text
(tool_name, input_hash)
```

must be identical for the exact duplicate calls.

The producer and detector must use the same normalization function. If Dev 1 exposes a canonicalization helper, use that instead of reimplementing it.

## 11. Band Context Requirements

The agents must exchange useful context through Band. They must not merely run independently in parallel.

Minimum Band room messages:

- Task kickoff.
- `ResearchAgent` plan.
- `ResearchAgent` findings.
- `ReportAgent` request for overlapping information.
- `AuditAgent` duplicate check or audit note.
- Redundant reuse note or event reference.
- `VerifierAgent` warning or verification status.
- Final recommendation.

The judge should be able to see that Band is coordinating the agents.

## 12. UI and Event Expectations

Dev 2 does not own the UI, but the workflow must produce enough events for Dev 4 to render.

The run should produce decision/event records with fields like:

- `run_id`
- `agent_id`
- `tool_name`
- `decision`
- `summary`
- `explanation`
- `saved_cost_usd`
- `saved_latency_ms`
- `saved_tokens`
- `source_call_id`
- `verifier_score`
- `cluster_id`
- `sponsor_hooks`

Where useful, include:

```json
{
  "sponsor_hooks": ["Band"]
}
```

Required visible moments:

- `ReportAgent reused ResearchAgent's prior result.`
- A duplicate cluster showing at least three cross-agent exact duplicate calls.
- A semantic reuse cluster.
- An unsafe semantic candidate that was blocked.
- A runaway loop alert.
- A final savings/cost report.

## 13. Determinism and Replay

The live demo must not depend on an LLM behaving identically every attempt.

Dev 2 must save one successful run to a frozen JSON trace.

The saved trace must:

- Preserve span order.
- Preserve `span_id` and `parent_span_id` relationships.
- Preserve relative timing if possible.
- Preserve token counts and model names.
- Preserve duplicate inputs and `input_hash` values.
- Replay cleanly into Redis Streams with `XADD`.

Provide a replay command, for example:

```bash
python scripts/replay_band_trace.py traces/band_demo_trace.json --run-id run-001
```

Stretch:

- Preserve relative `start_time` gaps so replay can pace `XADD`s and the detector can fire mid-run.

## 14. Fallback Plan

If live Band setup is blocked, implement a local `BandRoom` adapter with the same message flow.

The fallback must:

- Use the same agent names.
- Use the same room transcript shape.
- Emit the same Redundant spans/events.
- Save the same frozen trace JSON.
- Support the same replay command.
- Still make Band visible conceptually.

The target demo remains a real Band room, but the fallback must be strong enough to demo end-to-end without external Band credentials.

## 15. Recommended Implementation Shape

Codex should implement a small, deterministic demo package with this shape:

```text
demos/band/
  README.md
  run_band_demo.py or run_band_demo.ts
  agents/
    research_agent.*
    report_agent.*
    verifier_agent.*
    audit_agent.*
  band_room_adapter.*
  fallback_band_room.*
  scripted_tools.*
  trace_writer.*
  replay_trace.*
  traces/
    band_demo_trace.json
```

The implementation should support:

```bash
# Baseline waste-enabled run
python demos/band/run_band_demo.py --mode baseline --run-id run-001

# Redundant-enabled run
python demos/band/run_band_demo.py --mode redundant --run-id run-001

# Replay frozen trace
python demos/band/replay_trace.py demos/band/traces/band_demo_trace.json --run-id run-001
```

Equivalent TypeScript commands are acceptable if the project is TypeScript-first.

## 16. Acceptance Criteria

The implementation is done only when all of the following are true.

### Band Demo Acceptance

- A Band room exists with `ResearchAgent`, `ReportAgent`, `VerifierAgent`, and `AuditAgent`, or a fallback adapter faithfully simulates them.
- Agents exchange context through Band.
- Both baseline and Redundant-enabled modes run the same task.
- All agents call the same Redundant runtime/backend.
- All expensive LLM/tool calls go through Redundant wrappers.
- Each call has the correct `run_id` and `agent_id`.
- The UI or terminal shows `ReportAgent reused ResearchAgent's prior result.`
- Band is visibly part of the flow.

### Trace Acceptance

- Spans are emitted to `trace:{run_id}`.
- Every span validates against the required schema.
- Every `llm` and `tool` span has non-null `tokens` and `model`.
- `parent_span_id` nesting produces a readable flamegraph.
- Total span count is roughly 30 to 60.
- Frozen JSON trace exists and replays cleanly.

### Detection Acceptance

- Detector reports at least one exact redundant sub-agent finding:
  - Three distinct agents.
  - Same `tool_name`.
  - Same normalized `input_hash`.
- Detector reports at least one semantic duplicate candidate.
- Detector reports at least one safe semantic reuse.
- Detector reports at least one unsafe semantic candidate blocked by verifier.
- Detector reports at least one runaway finding with count >= 12.
- Runaway finding routes to alert/Sentry path.
- Total run cost is greater than wasted cost.
- Waste lands around 20% to 40% of total.

### Handoff Acceptance

Dev 2 must provide:

- Run command for the Band demo.
- Baseline run command or mode.
- Redundant-enabled run command or mode.
- Replay command.
- Agent list and prompts.
- Sample room transcript.
- Expected duplicate/reuse moments.
- Saved trace JSON path.
- Known fallback limitations.

## 17. Non-Negotiables

Codex must not weaken these requirements:

- Do not reduce exact cross-agent redundancy below three agents.
- Do not rely on semantic similarity for the exact-cache path.
- Do not reduce the runaway loop below 12 calls.
- Do not omit token counts or model names.
- Do not emit only UI events without raw trace spans.
- Do not make Band invisible by running agents independently without room context.
- Do not auto-replay or cache real side-effecting calls.
- Do not skip frozen trace replay.

## 18. Codex Build Prompt

Implement the Band multi-agent demo described in this document.

Prioritize correctness and determinism over cleverness. Build the smallest working version that satisfies every acceptance criterion.

Use the Redundant wrappers for every expensive action. Emit raw spans to `trace:{run_id}` and decision events for the UI. Include a fallback `BandRoom` adapter if live Band APIs are unavailable. Save one successful pathological run as frozen JSON and provide a replay command.

The final demo must show Band agents collaborating, accidentally repeating work, Redundant safely reusing repeated calls, blocking unsafe semantic reuse, detecting a runaway loop, and reporting cost savings.
