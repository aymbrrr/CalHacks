# Redundant: Multi-Agent Cost Firewall

## Summary
Build **Redundant**, a runtime layer for multi-agent AI apps that prevents wasted LLM/tool spend before it happens. The core demo uses **Band** as the multi-agent coordination layer: multiple agents collaborate in a shared room, accidentally repeat work, and Redundant catches/reuses safe duplicate calls across agents.

Base stack:
**Band + Redis + Redis Streams + Terac + Sentry + The Token Company + Anthropic**

Reach goals:
**Fetch AI** for an Agentverse/ASI:One auditor agent, **Browserbase** for realistic browser-agent waste, and **Arize** for optional trace/eval polish.

Target track:
Primarily **Ddoski’s Toolbox** / developer tooling, with strong sponsor hooks for Band, Redis/Redis Streams, Terac, Sentry, Token Company, Anthropic, and optional Arize.

## Product Behavior
Redundant wraps every expensive agent action:

```ts
redundant.llm({
  runId,
  agentId,
  messages,
  model,
  metadata
})

redundant.tool({
  runId,
  agentId,
  toolName,
  args,
  cacheability,
  metadata
})
```

For each call, Redundant decides:

- `EXECUTE`: no safe prior result found.
- `EXACT_REUSE`: same normalized call hash exists.
- `SEMANTIC_REUSE`: Redis finds similar prior call and Terac verifier approves.
- `COMPRESS_AND_EXECUTE`: unsafe to reuse, but prompt/context is bloated.
- `BLOCK_OR_WARN`: side-effecting or loop-like behavior detected.

Every decision is logged with cost, latency, confidence, source call, and explanation.

## Core Data Flow
1. Band agents start a collaborative task in a shared room.
2. Agents call LLMs and tools through Redundant wrappers.
3. Redundant normalizes input and computes:
   - exact hash
   - semantic embedding
   - cacheability class
   - state/freshness fingerprint
4. Redis checks exact cache first, then vector similarity.
5. Terac-trained verifier approves or rejects semantic reuse candidates.
6. If reuse is unsafe but prompt is bloated, Token Company compression is applied.
7. Executed/reused calls are emitted to Redis Streams for the live UI and optionally mirrored to Sentry.
8. UI shows live burn meter, duplicate clusters, savings, and suggested fixes.

## Required Call Schema
Each intercepted call stores:

```json
{
  "call_id": "uuid",
  "run_id": "demo-run-001",
  "agent_id": "research-agent",
  "call_type": "llm | tool",
  "tool_name": "web_search | summarize | repo_scan | llm",
  "cacheability": "pure | freshness_sensitive | state_bound | side_effecting",
  "normalized_input": "...",
  "input_hash": "...",
  "embedding": "[vector]",
  "output": "...",
  "input_tokens": 1200,
  "output_tokens": 300,
  "cost_usd": 0.018,
  "latency_ms": 2200,
  "created_at": "iso timestamp",
  "state_fingerprint": "optional",
  "decision": "EXECUTE",
  "reuse_source_call_id": null,
  "verifier_score": null,
  "explanation": "No safe duplicate found"
}
```

## UI/Backend Contract
Lock this before parallel work starts. The backend/runtime owns these shapes; the UI should be able to build first against mocked responses, then switch to live Redis Streams events without changing component code.

Conventions:
- Timestamps are ISO strings.
- Costs are USD numbers.
- Latency is milliseconds.
- `event_id` is the Redis Streams ID when live, or a stable replay ID when mocked.
- Unknown optional fields should be ignored by the UI.

Run lifecycle:

```ts
type Run = {
  run_id: string
  task: string
  mode: "baseline" | "redundant" | "replay"
  status: "idle" | "running" | "complete" | "failed"
  started_at: string
  completed_at?: string
  error?: string
}
```

Live Redis Streams event:

```ts
type RedundantEvent = {
  event_id: string
  run_id: string
  ts: string
  agent_id: "research-agent" | "report-agent" | "verifier-agent" | string
  call_id: string
  call_type: "llm" | "tool"
  tool_name: string
  decision: "EXECUTE" | "EXACT_REUSE" | "SEMANTIC_REUSE" | "COMPRESS_AND_EXECUTE" | "BLOCK_OR_WARN"
  cacheability: "pure" | "freshness_sensitive" | "state_bound" | "side_effecting"
  summary: string
  explanation: string
  saved_cost_usd: number
  saved_latency_ms: number
  saved_tokens: number
  source_call_id?: string
  verifier_score?: number
  cluster_id?: string
  sponsor_hooks?: Array<"Band" | "Redis" | "Redis Streams" | "Terac" | "Sentry" | "Token Company" | "Anthropic" | "Arize">
}
```

Final report:

```ts
type RunReport = {
  run_id: string
  attempted_calls: number
  executed_calls: number
  reused_or_blocked_calls: number
  redundant_rate: number
  estimated_baseline_cost_usd: number
  actual_cost_usd: number
  saved_cost_usd: number
  saved_latency_ms: number
  saved_tokens: number
  worst_duplicate_cluster?: string
  clusters: DuplicateCluster[]
  fixes: SuggestedFix[]
}

type DuplicateCluster = {
  cluster_id: string
  label: string
  calls: number
  unique_needed: number
  waste_percent: number
  saved_cost_usd: number
  saved_latency_ms: number
  agent_ids: string[]
}

type SuggestedFix = {
  fix_id: string
  title: string
  description: string
  sponsor_hook?: "Redis" | "Redis Streams" | "Terac" | "Sentry" | "Token Company" | "Anthropic" | "Band" | "Arize"
  code_hint?: string
}
```

Required endpoints:
- `POST /api/runs/start`: body `{ task: string, mode: "baseline" | "redundant" | "replay" }`; returns `Run`.
- `GET /api/runs/:run_id/events?after=<event_id>`: returns `RedundantEvent[]` for polling/fallback.
- `GET /api/runs/:run_id/stream`: server-sent events stream where each message is a `RedundantEvent`.
- `GET /api/runs/:run_id/report`: returns `RunReport`; may return partial totals while running.
- `POST /api/runs/:run_id/replay`: replays a saved trace through the same event/report contract.

Redis Streams contract:
- Stream key: `stream:redundant:events:{run_id}`.
- Backend writes one JSON payload per event under field `payload`.
- UI never reads Redis directly; it consumes `/events` or `/stream`.
- Replay mode emits the same event shape with deterministic timing so the demo works even if sponsor APIs fail.

## Cacheability Rules
- `pure`: safe to cache aggressively. Examples: repo scan, doc search, static page summary.
- `freshness_sensitive`: cache with short TTL and stale warning. Examples: news, pricing, current docs.
- `state_bound`: cache only with state/user fingerprint. Examples: inbox, calendar, CRM, private repo.
- `side_effecting`: never replay. Examples: send email, create issue, purchase, write DB.

Side-effecting duplicate detection should only produce a warning:
“Similar side-effect action already happened; do not replay automatically.”

## Four-Person Project Chunks

### 1. Runtime + Redis Core
Owner goal: make Redundant actually intercept, decide, reuse, and log.

Build:
- `redundant.llm()` wrapper around Anthropic calls.
- `redundant.tool()` wrapper around demo tools.
- Normalization for tool args and prompt messages.
- Exact cache using deterministic hash.
- Redis vector search for semantic candidates.
- Cost/latency estimator.
- Decision engine for exact reuse, semantic reuse, stale miss, unsafe miss, side-effect warning.

Demo tools:
- `search_docs(query)`
- `summarize_page(url_or_text)`
- `scan_repo(topic)`
- `compare_tools(tool_a, tool_b)`

Acceptance:
- Same call reuses exact cached output.
- Similar call proposes semantic reuse.
- Side-effecting call never replays.
- Every call appears in final report with dollars/latency.

### 2. Band Multi-Agent Workflow
Owner goal: make Band central, not bolted on.

Build:
- Band room with at least two agents:
  - `ResearchAgent`: searches/scans/summarizes sources.
  - `ReportAgent`: asks for overlapping summaries and writes final report.
- Optional third agent if easy:
  - `VerifierAgent`: checks whether cached reuse seems valid.
- Agents must exchange context through Band.
- Both agents call the same Redundant runtime so cross-agent reuse works.

Demo task:
“Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation.”

Scripted waste:
- Both agents search similar queries.
- Both summarize same source under slightly different wording.
- One agent scans repo/docs after another already did.
- One agent enters a small loop repeating a tool call.

Acceptance:
- UI shows “ReportAgent reused ResearchAgent’s prior result.”
- Band is visibly part of the flow.
- At least two agents collaborate through Band, satisfying the Band sponsor story.

### 3. Terac Verifier + Evaluation
Owner goal: make semantic caching trustworthy, not hand-wavy.

Setup reference: [Terac readiness checklist](terac-readiness.md).

Build:
- Small annotation dataset of call pairs:
  - new call
  - cached candidate call
  - candidate output
  - task context
  - human label
- Labels:
  - `safe_reuse`
  - `not_equivalent`
  - `needs_freshness_check`
  - `state_specific`
  - `side_effect_risk`
- Terac annotation app collects labels during the hackathon.
- Train or simulate lightweight verifier:
  - minimum viable: rules + labeled examples + small LLM judge prompt
  - better: fine-tuned/classifier-style model if Terac flow supports it quickly
- Evaluation compares:
  - raw Redis similarity threshold
  - Terac verifier-gated reuse

Acceptance:
- Show held-out eval table:
  - unsafe cache hits before verifier
  - unsafe cache hits after verifier
  - savings retained
- Demo one unsafe semantic match that Redis finds but Terac verifier blocks.
- Explain: “Redis finds candidates; Terac teaches us when reuse is safe.”

### 4. Dashboard + Sponsor Polish
Owner goal: make the demo legible and prize-ready.

Build UI views:
- Live run timeline:
  - attempted call
  - decision
  - agent name
  - saved cost/latency
  - explanation
- Burn meter:
  - original estimated cost
  - actual cost
  - saved dollars
  - saved latency
  - redundant call rate
- Duplicate clusters:
  - cluster name
  - number of calls
  - number needed
  - waste percent
  - total cost burned/saved
- Fix suggestions:
  - add `@redundant.cached_tool(ttl="1h")`
  - move timestamp out of stable prompt prefix
  - compress bloated context
  - replace repeated LLM classifier with embedding lookup
- Sponsor tabs:
  - Redis cache/vector evidence
  - Redis Streams live event feed
  - Terac verifier/eval
  - Optional Arize trace comparison
  - Sentry issues
  - Band agent collaboration

Integrations:
- Redis Streams: base product event bus for attempted calls, decisions, savings, duplicate clusters, and live UI updates.
- Sentry: create/report issues for duplicate clusters or agent loops.
- Token Company: compress bloated prompts when reuse is unsafe.
- Anthropic: use Claude and include prompt-cache-layout recommendation.
- Arize: optional add-on for baseline vs optimized trace/eval comparison if time allows.

Acceptance:
- Judge can understand value in 30 seconds from UI.
- Final report can be screenshotted for Devpost.
- Demo works with live run or replayed trace fallback.

## Sponsor Integration Plan
- **Band**: base multi-agent system; at least two agents collaborate through Band.
- **Redis**: exact cache, vector search, TTL/staleness, duplicate clusters, and Redis Streams for live runtime events.
- **Terac**: human labels for semantic reuse safety verifier.
- **Sentry**: waste/loop issues with dollar and latency impact.
- **The Token Company**: compression path for unsafe-to-cache bloated prompts.
- **Anthropic**: Claude calls plus prompt-cache optimization suggestions.

Optional add-on:
- **Arize**: baseline vs optimized traces/evals if the core Redis Streams-based product is already stable.

Avoid adding:
- Pika/Midjourney unless making pitch assets after product is done.
- Deepgram unless voice becomes a UX goal.
- QNX/Ultimate Bots/Cognichip unless pivoting away from developer tooling.

## Reach Goal: Fetch AI
Build only after base demo is stable.

Implement:
- `RedundantAuditAgent` registered on Agentverse.
- ASI:One chat flow:
  - user asks: “Audit this trace for redundant agent spend.”
  - agent fetches or receives trace JSON
  - agent returns waste report and top fixes
- Use Fetch as user-facing auditor, not as the internal cache engine.

Acceptance:
- Agentverse profile URL exists.
- ASI:One shared chat demonstrates complete audit workflow.
- Report matches dashboard numbers.

## Reach Goal: Browserbase
Build only if runtime and Band demo are already solid.

Implement:
- Replace fake `search_docs` with Browserbase-powered browser/search actions.
- Log browser actions as Redundant tool calls:
  - `browser_search`
  - `open_page`
  - `extract_page_text`
  - `summarize_page`
- Detect repeated page visits and repeated page summaries.

Acceptance:
- Demo shows Redundant saving repeated browser-agent work.
- Browserbase is central to at least one visible workflow, not just a background fetch.

## Reach Goal: Arize
Build only after the Redis Streams live event path is stable.

Implement:
- Export baseline and Redundant-enabled run traces from the Redis Streams event log.
- Compare task quality, unsafe reuse rate, cost, latency, and duplicate-call rate.
- Use Arize as an external eval/trace view, not as the base event bus.

Acceptance:
- Arize view mirrors the same run IDs and metrics shown in Redundant.
- Demo can show trace/eval comparison, but the core product still works if Arize is unavailable.

## Demo Timeline
1. Show baseline Band run with waste enabled.
2. Agents repeat searches/summaries/repo scans.
3. Show baseline cost and latency.
4. Turn on Redundant.
5. Rerun same task.
6. Show exact reuse, semantic reuse, cross-agent reuse, unsafe semantic block, compression path.
7. Open the Redis Streams-backed live event/trace view.
8. Show Sentry waste issue.
9. End on final report:
   - attempted calls: e.g. 74
   - executed calls: e.g. 31
   - reused/blocked calls: e.g. 43
   - redundant rate: e.g. 58%
   - original cost: e.g. $1.84
   - actual cost: e.g. $0.72
   - latency saved: e.g. 90s
   - worst duplicate cluster: web/repo search

## Testing And Fallbacks
- Unit tests:
  - exact duplicate reuse
  - semantic candidate retrieval
  - unsafe semantic rejection
  - TTL stale miss
  - side-effect no-replay
  - cross-agent reuse
- Eval tests:
  - raw Redis similarity vs Terac verifier on held-out labeled pairs.
- Demo fallback:
  - Record one complete trace JSON.
  - UI can replay trace if external APIs fail.
  - Sentry screenshots or optional Arize exports are acceptable fallback only after live path is attempted.
- Hard no:
  - Do not let any side-effecting tool auto-replay.
  - Do not pitch as a dashboard; pitch as runtime prevention.

## Success Criteria
- Core demo runs end-to-end in under 5 minutes.
- Band collaboration is visible and material.
- Redis is necessary to the core architecture.
- Terac materially improves safe semantic reuse.
- UI clearly shows money/latency saved.
- Sponsor story feels like one product:
  “Band agents collaborate, Redis finds duplicate work, Redis Streams powers the live runtime feed, Terac verifies safe reuse, Token Company compresses unsafe calls, and Sentry reports the impact.”

## Assumptions
- Four people work in parallel.
- No more sponsors are added to the base stack.
- Fetch AI, Browserbase, and Arize remain reach/add-on goals.
- The product name is **Redundant** unless the team chooses a replacement before implementation.
- Primary judging pitch is developer-tooling impact, not consumer UX.
