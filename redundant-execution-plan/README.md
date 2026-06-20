# Redundant Execution Plan

This folder distills the existing CalHacks planning docs into an implementation-ready plan for the Redundant hackathon project, with special focus on:

- Dev 2: Band multi-agent workflow where cross-agent reuse is the core demo moment
- Alignment with `docs/redundant-plan.md` as the source of truth
- Current implementation status for the deterministic Band fallback demo

Source docs read:

- `README.md`
- `docs/redundant-plan.md`
- `docs/redundant-additional-context.md`
- `redundant-execution-plan/dev2-band-codex-contract.md`
- `demos/band/README.md`

## North Star

Build Redundant as a runtime cost firewall for multi-agent AI apps.

The demo should show Band agents collaborating in a shared room, accidentally repeating expensive LLM/tool work, and Redundant preventing that waste before spend happens.

The judge-visible line is:

> Band agents collaborate, Redis finds duplicate work, Redis Streams powers the live runtime feed, Terac verifies safe reuse, Token Company compresses unsafe calls, and Sentry reports the impact.

## MVP Shape

The fastest credible MVP is not a full production platform. It is a tight end-to-end path:

1. Four Band agents work on one shared research task: `ResearchAgent`, `ReportAgent`, `VerifierAgent`, and `AuditAgent`.
2. All agents call tools only through the Redundant wrappers.
3. Redundant detects exact duplicate calls across at least three distinct agents.
4. Redundant detects at least one semantic duplicate candidate and safely reuses one approved semantic match.
5. Redundant blocks one unsafe semantic candidate instead of replaying it.
6. Redundant flags a runaway verifier loop after at least 12 repeated calls.
7. A terminal report or dashboard shows attempted calls, executed calls, reused or blocked calls, dollars saved, latency saved, and cross-agent reuse.
8. A recorded trace can replay the same story if any external sponsor API fails during judging.

## Current Dev 2 Implementation

The deterministic Dev 2 Band demo now exists under:

```text
demos/band/
```

Run commands:

```bash
python demos/band/run_band_demo.py --mode baseline --run-id run-001
python demos/band/run_band_demo.py --mode redundant --run-id run-001
python demos/band/replay_trace.py demos/band/traces/band_demo_trace.json --run-id run-001 --dry-run
```

Saved traces:

- Redundant-enabled frozen trace: `demos/band/traces/band_demo_trace.json`
- Baseline trace: `demos/band/traces/band_demo_baseline_trace.json`

Validated behavior in the redundant trace:

- 34 total spans and 28 expensive `llm` or `tool` calls.
- Required visible line appears in terminal and transcript: `ReportAgent reused ResearchAgent's prior result.`
- Exact duplicate cluster includes `ResearchAgent`, `ReportAgent`, and `AuditAgent` calling `search_docs("agent cost optimization redis sentry")` with one shared input hash.
- Semantic reuse appears for `scan_repo("tool cache decorator")` reusing `scan_repo("cached tool wrapper")`.
- Summary exact reuse appears for the shared source summary.
- Unsafe semantic block appears for the Sentry alert-routing query against the Redis cache-invalidation source.
- `VerifierAgent` calls `verify_source(...)` 12 times and emits `RUNAWAY_LOOP_ALERT`.
- Waste rate is 20.4%, inside the required 20% to 40% band.
- Replay dry-run emits `XADD trace:run-001` payloads from the frozen JSON trace.

Current limitation:

The demo uses a local `FallbackBandRoom` and deterministic scripted tools/LLM responses. This is intentional for replayability and judge safety. Live Band and Dev 1's final runtime can be swapped in behind the same room adapter and wrapper-shaped runtime.

## Recommended Build Order

### Phase 1: Runtime + Redis Core

Build the runtime layer that intercepts, decides, reuses, and logs.

Deliverables:

- `redundant.llm()` wrapper around Anthropic calls
- `redundant.tool()` wrapper around demo tools
- normalization for tool args and prompt messages
- deterministic exact hash
- exact cache lookup/store
- semantic candidate lookup/store
- TTL policy by cacheability class
- Redis vector search for semantic candidates
- Redis Streams event writer
- decision engine for exact reuse, semantic reuse, stale miss, unsafe miss, and side-effect warning
- demo tools: `search_docs`, `summarize_page`, `scan_repo`, and `compare_tools`

Target behavior:

- same canonical call returns `EXACT_REUSE`
- similar call returns a candidate for verifier gating
- side-effecting call never replays
- expired freshness-sensitive result returns a stale miss

### Phase 2: Dev 2 Band Multi-Agent Workflow

Dev 2 wires the runtime into the Band workflow and makes Band central.

Deliverables:

- `ResearchAgent`
- `ReportAgent`
- `VerifierAgent`
- `AuditAgent`
- shared run ID across agents
- visible room/context exchange
- repeated searches, summaries, repo scans, and one loop-like duplicate
- exact duplicate across three distinct agents
- semantic reuse
- unsafe semantic block
- 12-call runaway loop alert
- frozen trace JSON
- replay command

Required demo moment:

> `ReportAgent reused ResearchAgent's prior result`

If the Band SDK or credentials are not ready, implement a `BandRoom` adapter interface plus a local `FallbackBandRoom`. The actual Band integration can then swap in behind the same interface.

Status: implemented in fallback mode under `demos/band/`.

### Phase 3: Terac Verifier + Evaluation

Build the semantic reuse safety story from `docs/redundant-plan.md`.

Deliverables:

- small annotation dataset of call pairs
- labels for safe reuse, not equivalent, freshness checks, state specificity, and side-effect risk
- Terac annotation app or simulated lightweight verifier flow
- eval table comparing raw Redis similarity vs verifier-gated reuse
- one unsafe semantic match that Redis finds but the verifier blocks

### Phase 4: Dashboard + Sponsor Polish + Pitch

Make the value obvious.

Deliverables:

- terminal summary or dashboard
- duplicate cluster table
- final savings report
- fallback trace replay
- sponsor-specific tabs or sections if UI time allows

Do not block the project on a polished UI. The runtime interception and savings number are the product.

## What You Need To Do

These are the steps that require human decisions, accounts, credentials, or sponsor-specific setup:

1. Confirm the scope freeze: base stack only, with Fetch AI and Browserbase as reach goals.
2. Create or confirm sponsor accounts/projects for Redis, Band, Anthropic, Terac, Sentry, and The Token Company. Treat Arize as optional add-on setup.
3. Collect API keys locally in `.env`; do not commit them.
4. Find the current Band SDK/API docs and decide whether the demo runs with live Band or a local adapter first.
5. Decide whether the hackathon demo will lead with terminal output, dashboard, or both.
6. Assign owners:
   - Dev 1: Runtime + Redis Core
   - Dev 2: Band Multi-Agent Workflow
   - Dev 3: Terac Verifier + Evaluation
   - Dev 4: Dashboard + Sponsor Polish + Pitch
7. Record one complete successful trace as soon as the demo works once. The fallback trace currently exists at `demos/band/traces/band_demo_trace.json`.
8. Prepare the 30-second pitch around money saved, not around the dashboard.

## What Codex Has Implemented

Implemented in this repository:

- Python deterministic demo package under `demos/band/`
- `redundant.llm()` and `redundant.tool()` wrapper-shaped runtime shim
- explicit `agent_id` handling through agent context or call args
- canonicalizer and deterministic hash
- cacheability model for pure and state-bound calls
- rules-first exact reuse, semantic reuse, unsafe block, and runaway alert decisions
- in-memory backend
- RedundantEvent-compatible event payload format
- wasteful demo tools
- Band room adapter interface
- local `FallbackBandRoom` for development and fallback
- ResearchAgent, ReportAgent, VerifierAgent, and AuditAgent demo flow
- trace replay JSON and replay script
- terminal savings report
- frozen baseline and redundant traces

Codex can still implement next:

- Redis backend interface and live Redis Streams writer
- Dev 1 runtime integration once the final module path is available
- live Band SDK adapter once credentials and docs are available
- tests for exact reuse, stale miss, side-effect no-replay, semantic candidate gating, and cross-agent reuse
- dashboard scaffold if desired after the runtime path is working
- real sponsor SDK wiring once dependency names, install commands, and credentials are available locally

## Acceptance Checklist

- Done: wrapped tool and LLM calls always include an explicit `agent_id`.
- Done: every call decision emits a RedundantEvent-compatible payload.
- Done: exact duplicate is blocked or reused end-to-end in redundant mode.
- Done: exact duplicate cluster spans three agents with one `tool_name` and one normalized `input_hash`.
- Done: similar-but-not-identical call becomes a semantic candidate.
- Done: semantic reuse is gated by a verifier-style decision.
- Done: unsafe semantic reuse is blocked.
- Done: 12-call runaway loop emits an alert event.
- Done: all Band agents use the same Redundant runtime shim.
- Done: cross-agent reuse appears in logs and terminal.
- Done: final report includes attempted calls, executed calls, reused or blocked calls, cost saved, latency saved, and duplicate clusters.
- Done: demo can run from a single command and replay a saved trace.
- Pending: live Redis Streams writer.
- Pending: live Band SDK adapter.
- Pending: final Dev 1 runtime integration.

## Proposed Repository Target

The current deterministic demo implementation lives under:

```text
demos/band/
```

When the product runtime implementation starts, create the reusable product code under:

```text
redundant/
```

This planning folder should stay as the coordination artifact. Demo code and future product code should live separately so docs and implementation do not blur together.
