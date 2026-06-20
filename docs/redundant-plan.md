# Redundant: Multi-Agent Cost Firewall

## Summary

Redundant is a runtime layer for multi-agent AI apps that prevents wasted LLM and tool spend before it happens. The core demo uses Band as the multi-agent coordination layer: multiple agents collaborate in a shared room, accidentally repeat work, and Redundant catches and reuses safe duplicate calls across agents.

Base stack:

- Band
- Redis
- Terac
- Arize
- Sentry
- The Token Company
- Anthropic

Reach goals:

- Fetch AI for an Agentverse/ASI:One auditor agent
- Browserbase for realistic browser-agent waste

Target track:

- Primary: Ddoski's Toolbox / developer tooling
- Sponsor emphasis: Band, Redis, Terac, Arize, Sentry, The Token Company, Anthropic

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

For each call, Redundant chooses one decision:

- `EXECUTE`: no safe prior result found.
- `EXACT_REUSE`: same normalized call hash exists.
- `SEMANTIC_REUSE`: Redis finds a similar prior call and the Terac-trained verifier approves it.
- `COMPRESS_AND_EXECUTE`: reuse is unsafe, but the prompt/context is bloated enough to compress.
- `BLOCK_OR_WARN`: side-effecting or loop-like behavior is detected.

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
5. A Terac-trained verifier approves or rejects semantic reuse candidates.
6. If reuse is unsafe but the prompt is bloated, The Token Company compression path is applied.
7. Executed/reused calls are logged to Redundant, Arize, and optionally Sentry.
8. The UI shows a live burn meter, duplicate clusters, savings, and suggested fixes.

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

## Cacheability Rules

- `pure`: safe to cache aggressively. Examples: repo scan, doc search, static page summary.
- `freshness_sensitive`: cache with short TTL and stale warning. Examples: news, pricing, current docs.
- `state_bound`: cache only with state/user fingerprint. Examples: inbox, calendar, CRM, private repo.
- `side_effecting`: never replay. Examples: send email, create issue, purchase, write DB.

Side-effecting duplicate detection should only produce a warning:

> Similar side-effect action already happened; do not replay automatically.

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
- Decision engine for exact reuse, semantic reuse, stale miss, unsafe miss, and side-effect warning.

Demo tools:

- `search_docs(query)`
- `summarize_page(url_or_text)`
- `scan_repo(topic)`
- `compare_tools(tool_a, tool_b)`

Acceptance:

- Same call reuses exact cached output.
- Similar call proposes semantic reuse.
- Side-effecting call never replays.
- Every call appears in final report with dollars and latency.

### 2. Band Multi-Agent Workflow

Owner goal: make Band central, not bolted on.

Build:

- Band room with at least two agents:
  - `ResearchAgent`: searches, scans, and summarizes sources.
  - `ReportAgent`: asks for overlapping summaries and writes the final report.
- Optional third agent:
  - `VerifierAgent`: checks whether cached reuse seems valid.
- Agents exchange context through Band.
- Both agents call the same Redundant runtime so cross-agent reuse works.

Demo task:

> Research agent cost optimization tools, compare Redis/Arize/Sentry-style approaches, and produce a short recommendation.

Scripted waste:

- Both agents search similar queries.
- Both summarize the same source under slightly different wording.
- One agent scans repo/docs after another already did.
- One agent enters a small loop repeating a tool call.

Acceptance:

- UI shows `ReportAgent reused ResearchAgent's prior result`.
- Band is visibly part of the flow.
- At least two agents collaborate through Band, satisfying the Band sponsor story.

### 3. Terac Verifier + Evaluation

Owner goal: make semantic caching trustworthy, not hand-wavy.

Build:

- Small annotation dataset of call pairs:
  - new call
  - cached candidate call
  - candidate output
  - task context
  - human label
- Terac annotation app with labels:
  - `safe_reuse`
  - `not_equivalent`
  - `needs_freshness_check`
  - `state_specific`
  - `side_effect_risk`
- Lightweight verifier:
  - minimum viable: rules + labeled examples + small LLM judge prompt
  - better: fine-tuned/classifier-style model if Terac flow supports it quickly
- Evaluation comparing:
  - raw Redis similarity threshold
  - Terac verifier-gated reuse

Acceptance:

- Held-out eval table shows unsafe cache hits before and after verifier.
- Demo includes one unsafe semantic match that Redis finds but the Terac verifier blocks.
- Explain the sponsor fit as: Redis finds candidates; Terac teaches Redundant when reuse is safe.

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
  - Terac verifier/eval
  - Arize trace comparison
  - Sentry issues
  - Band agent collaboration

Integrations:

- Arize: log traces for baseline run and Redundant run.
- Sentry: create/report issues for duplicate clusters or agent loops.
- The Token Company: compress bloated prompts when reuse is unsafe.
- Anthropic: use Claude and include prompt-cache-layout recommendations.

Acceptance:

- Judge can understand value in 30 seconds from UI.
- Final report can be screenshotted for Devpost.
- Demo works with live run or replayed trace fallback.

## Sponsor Integration Plan

- Band: base multi-agent system; at least two agents collaborate through Band.
- Redis: exact cache, vector search, TTL/staleness, duplicate clusters.
- Terac: human labels for semantic reuse safety verifier.
- Arize: baseline vs optimized traces/evals.
- Sentry: waste/loop issues with dollar and latency impact.
- The Token Company: compression path for unsafe-to-cache bloated prompts.
- Anthropic: Claude calls plus prompt-cache optimization suggestions.

Avoid adding:

- Pika/Midjourney unless making pitch assets after product is done.
- Deepgram unless voice becomes a UX goal.
- QNX/Ultimate Bots/Cognichip unless pivoting away from developer tooling.

## Reach Goal: Fetch AI

Build only after the base demo is stable.

Implement:

- `RedundantAuditAgent` registered on Agentverse.
- ASI:One chat flow:
  - user asks: `Audit this trace for redundant agent spend.`
  - agent fetches or receives trace JSON
  - agent returns waste report and top fixes
- Use Fetch as the user-facing auditor, not as the internal cache engine.

Acceptance:

- Agentverse profile URL exists.
- ASI:One shared chat demonstrates a complete audit workflow.
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

## Demo Timeline

1. Show baseline Band run with waste enabled.
2. Agents repeat searches, summaries, and repo scans.
3. Show baseline cost and latency.
4. Turn on Redundant.
5. Rerun the same task.
6. Show exact reuse, semantic reuse, cross-agent reuse, unsafe semantic block, and compression path.
7. Open Arize trace comparison.
8. Show Sentry waste issue.
9. End on final report:
   - attempted calls, e.g. 74
   - executed calls, e.g. 31
   - reused/blocked calls, e.g. 43
   - redundant rate, e.g. 58%
   - original cost, e.g. $1.84
   - actual cost, e.g. $0.72
   - latency saved, e.g. 90s
   - worst duplicate cluster, e.g. web/repo search

## Testing And Fallbacks

Unit tests:

- exact duplicate reuse
- semantic candidate retrieval
- unsafe semantic rejection
- TTL stale miss
- side-effect no-replay
- cross-agent reuse

Eval tests:

- raw Redis similarity vs Terac verifier on held-out labeled pairs

Demo fallback:

- Record one complete trace JSON.
- UI can replay trace if external APIs fail.
- Sentry/Arize screenshots or mocked exports are acceptable fallback only after the live path is attempted.

Hard no:

- Do not let any side-effecting tool auto-replay.
- Do not pitch as a dashboard; pitch as runtime prevention.

## Success Criteria

- Core demo runs end-to-end in under 5 minutes.
- Band collaboration is visible and material.
- Redis is necessary to the core architecture.
- Terac materially improves safe semantic reuse.
- UI clearly shows money and latency saved.
- Sponsor story feels like one product:

> Band agents collaborate, Redis finds duplicate work, Terac verifies safe reuse, The Token Company compresses unsafe calls, Arize/Sentry prove and report the impact.

## Assumptions

- Four people work in parallel.
- No more sponsors are added to the base stack.
- Fetch AI and Browserbase remain reach goals.
- The product name is Redundant unless the team chooses a replacement before implementation.
- Primary judging pitch is developer-tooling impact, not consumer UX.

