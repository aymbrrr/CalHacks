# Redundant — Hackathon Planning Document
### The cost firewall for AI agents

---

## The Problem

AI agents are burning money silently. A single research agent run can make 70+ tool and LLM calls — and in practice, 40–60% of those calls are semantically identical to ones already made earlier in the same run, or in runs made seconds ago by another agent on the same task. The developer never sees it. The bill just climbs.

Research shows 31% of LLM queries exhibit semantic similarity to previous requests, representing massive inefficiency in deployments without caching infrastructure. For agentic workloads, that number is substantially worse — agents loop, retry, and re-discover the same context repeatedly. At 50 requests per day, a single user pays $26–32/month in API costs alone; service providers report losses of $10–20K/month at modest scale.

The existing tools don't solve this. Provider-level prompt caching only covers stable prefixes. GPTCache handles chatbot-style LLM responses. Nobody intercepts **tool calls** — web searches, SQL reads, RAG retrievals, GitHub lookups — which is where agents actually waste the most money.

Redundant sits in that gap.

---

## What Redundant Does

Redundant is a runtime optimizer that wraps both LLM calls and tool calls, intercepts them before execution, and asks: **"Have we already done something semantically equivalent, recently enough, under equivalent state?"**

If yes: serve the cached result.
If partially: compress, route to a cheaper model, or flag the stale component.
If the agent is looping: detect it and interrupt.

The dashboard is the receipt. The product is the interception.

---

## Target Audience

**Primary**: Platform/infra engineers at AI-native companies running multi-step agentic pipelines (LangGraph, AutoGen, CrewAI, custom agents). They have LLM bills and no visibility into where the waste comes from.

**Secondary**: AI product teams building on top of foundation models who want to ship cheaper and faster without changing their agent logic.

**Hackathon judge lens**: Redis engineers who want to see deep, non-obvious use of Redis Iris — not just "we put responses in a hash." Agent Memory for cross-run deduplication, LangCache for semantic matching, Vector Search for clustering waste, and TTL-aware freshness policies for tool output invalidation.

---

## Pitch

> "Your agent made 74 calls. It only needed 29. Redundant caught the other 45 and saved you $1.13 and 93 seconds — in a single run. Here's exactly where the waste came from, and here's the one-line fix."

Redundant is not a dashboard. It's a proxy layer that sits between your agent and every expensive action it takes — LLM calls, web searches, SQL reads, RAG retrievals, GitHub lookups — and blocks the ones that already happened. It uses Redis Iris as its memory and matching layer: LangCache for semantic deduplication, Agent Memory for cross-session and cross-agent awareness, and vector search for clustering waste patterns into actionable fixes.

---

## Redis Iris Integration (Prize Track Alignment)

This is the core technical story for the Redis track. We use **all four Iris capabilities** in a non-trivial way:

| Redis Iris Service | How Redundant Uses It |
|---|---|
| **LangCache** | Semantic caching for both LLM responses *and* normalized tool call outputs. Configurable similarity threshold per tool cacheability class. |
| **Agent Memory (Session)** | Track call graph within a single agent run — detect loops where the same intent → tool → result cycle repeats. |
| **Agent Memory (Long-Term)** | Cross-run and cross-agent deduplication. If Agent B is about to search what Agent A already found in the last hour, serve Agent A's result. TTL-controlled freshness. |
| **Vector Search / RedisVL** | Cluster near-duplicate calls into waste groups. Surface the top offender clusters with cost and latency impact. Power the "semantic equivalence verifier" that confirms a cache hit is truly safe to serve. |

This goes well beyond caching responses in a hash. We're using Redis as a **runtime decision layer** for agent behavior.

---

## Technical Architecture

```
Agent Runtime (LangGraph / AutoGen / custom)
          │
          ▼
  ┌─────────────────────────────────────┐
  │        Redundant SDK Wrapper        │
  │   @redundant.cached_tool(ttl=1h)   │
  │   with redundant.trace("run-id")   │
  └────────────────┬────────────────────┘
                   │
          ┌────────▼────────┐
          │  Canonicalizer  │  normalize args, strip whitespace,
          │                 │  sort keys, lowercase SQL
          └────────┬────────┘
                   │
         ┌─────────▼──────────┐
         │  Exact Hash Lookup │  Redis key: hash(tool+args+tenant)
         └─────────┬──────────┘
                   │ miss
         ┌─────────▼──────────┐
         │ Semantic Vector     │  Redis LangCache / RedisVL
         │ Search (Redis Iris) │  embedding of normalized call
         └─────────┬──────────┘
                   │ candidate found
         ┌─────────▼──────────┐
         │  Safety Verifier   │  cacheability class check
         │                    │  freshness / TTL check
         │                    │  state fingerprint match
         │                    │  lightweight LLM judge (optional)
         └─────────┬──────────┘
                   │
         ┌─────────▼─────────────────────┐
         │  Decision Engine              │
         │  SERVE_CACHE                  │
         │  COMPRESS_AND_CALL            │
         │  ROUTE_CHEAPER_MODEL          │
         │  EXECUTE_ORIGINAL             │
         │  BLOCK_SIDE_EFFECT (warn)     │
         └─────────┬─────────────────────┘
                   │
         ┌─────────▼──────────┐
         │  Redis Agent       │  write call event to session memory
         │  Memory (Iris)     │  check cross-agent LTM for dedup
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Event Stream      │  Redis Streams for live UI
         │  + Cost Logger     │  tokens saved, latency avoided, $
         └────────────────────┘
```

### Tool Cacheability Classes

| Class | Examples | Behavior |
|---|---|---|
| **Pure** | RAG search, SQL read, GitHub issue lookup | Cache aggressively, long TTL |
| **Freshness-sensitive** | Web search, news, stock price | Short TTL + staleness warning |
| **State-bound** | Calendar, inbox, user-specific CRM | Cache only with user+state fingerprint |
| **Side-effecting** | Send email, create ticket, write DB | Never replay — only warn "similar action already executed" |

### Redis Schema

```
# Exact cache entries
call:{sha256(canonical_call)}
  provider, model, tool_name
  normalized_args (JSON)
  output (JSON)
  input_tokens, output_tokens, cost_usd
  latency_ms, created_at, ttl
  tenant_id, agent_id, run_id
  cacheability_class
  verifier_score
  embedding_id -> points to vector index entry

# Agent Memory (via Redis Iris Agent Memory API)
Session memory: ordered event log scoped by run_id
Long-term memory: cross-run facts + call results, vector-backed retrieval

# Vector index (RedisVL)
Fields: embedding, tool_name, tenant_id,
        cacheability_class, cost_usd, created_at,
        agent_id, state_fingerprint

# Event stream (Redis Streams)
stream:cost_events:{tenant_id}
  run_id, call_id, action (SERVE_CACHE | EXECUTE | BLOCK)
  tokens_saved, latency_saved_ms, cost_saved_usd
  cluster_id (for grouping into waste clusters)
```

### Loop Detection (Agent Memory)

Using Redis Agent Memory's session memory as an ordered event log, Redundant watches for the pattern:

```
same_intent → same_tool → same_result → same_next_prompt (×N)
```

When detected (N ≥ 3 by default), surface an interrupt:

```
⚠ Loop detected: agent has queried GitHub issues for "redis vector bug" 5 times.
  All 5 returned identical results.
  Terminate loop? Summarize and continue? Pass through?
```

This is demoed live in the terminal/UI.

### Cross-Agent Deduplication (Long-Term Memory)

Redis Agent Memory's LTM layer (with configurable TTL and vector-backed retrieval) lets Agent B discover what Agent A already found:

```python
# Before executing tool call:
ltm_hit = await agent_memory.search_long_term(
    query=canonical_call_embedding,
    filters={"tool_name": tool_name, "tenant_id": tenant_id},
    top_k=1
)
if ltm_hit and ltm_hit.similarity > THRESHOLD:
    return ltm_hit.output  # Agent B reuses Agent A's result
```

This surfaces in the UI as: `Agent B reused Agent A's GitHub scan → saved 42k tokens.`

---

## Demo Script (The "Live Bill" Moment)

Run a single wasteful research agent task:

> *"Research 10 Redis competitors, summarize their pricing, and verify each source."*

The agent (intentionally written without deduplication) makes ~74 calls. Redundant intercepts in real time.

**Live terminal output:**
```
▸ Call #18: web_search("Redis vector search pricing")
  → duplicate of Call #7  [similarity: 0.97]
  → BLOCKED  ✓ saved 2.1s · $0.006

▸ Call #31: llm.summarize(same_page_content)
  → semantic match of Call #12  [similarity: 0.94]
  → verifier: APPROVED
  → SERVED FROM CACHE  ✓ saved 1,842 tokens

▸ Call #44: system prompt structure
  → volatile timestamp in stable prefix
  → prompt cache opportunity MISSED
  → projected savings if fixed: $23/day
  → one-click fix available

⚠ Loop detected at Call #51: github.search_issues queried 5× with identical results.
```

**Final summary:**
```
Agent run complete.

Total calls attempted:    74
Executed:                 29
Blocked / reused:         45
Redundant call rate:      60.8%

Estimated cost (naive):   $1.84
Actual cost:              $0.71
Saved:                    $1.13 (61%)

Latency avoided:          93.4s
Worst offender:           web_search · 17 duplicate calls
One-click fixes:          4
```

This is the "moment of money" that wins the room.

---

## Work Split (4 Devs, 12-Hour Sprint)

### Overall principle
Build the SDK wrapper + Redis integration first (hours 1–4). Everything else — demo agent, UI, verifier — is layered on top. The demo must work even if the UI is minimal. Never block on the UI.

---

### Dev 1 — Redis Integration Lead
**Hours 1–4**: Redis Iris setup (LangCache, Agent Memory, RedisVL index), exact hash cache, schema design, connection layer, Redis Streams event emitter.
**Hours 5–8**: Long-term memory cross-agent dedup logic, TTL policy per cacheability class, loop detection algorithm using session memory event log.
**Hours 9–12**: Polish Redis integration, ensure all four Iris services are visibly used, write a short explainer for judges on which Iris feature does what.

**Key deliverables**: Working cache layer with all four Iris services; loop detection; cross-agent LTM dedup.

---

### Dev 2 — SDK Wrapper + Canonicalizer
**Hours 1–4**: Python SDK: `@redundant.cached_tool()` decorator, `redundant.llm()` wrapper, call canonicalization (normalize SQL, strip whitespace, sort JSON keys), exact hash computation, cacheability class assignment.
**Hours 5–8**: Semantic equivalence verifier (rules-first: same tool + tenant + state fingerprint; then similarity threshold gate). Decision engine (SERVE_CACHE / COMPRESS / ROUTE / EXECUTE / BLOCK_SIDE_EFFECT).
**Hours 9–12**: TypeScript SDK wrapper (optional stretch); clean up decorator API; write integration docs and code samples.

**Key deliverables**: Importable Python SDK; decorator + context manager; decision engine; verifier.

---

### Dev 3 — Demo Agent + Cost Engine
**Hours 1–4**: Write the intentionally wasteful research agent (LangGraph or plain Python with tool calls). Wire in Redundant SDK. Verify intercepted calls appear in Redis.
**Hours 5–8**: Cost accounting engine: per-model token pricing table, real-time cost delta computation (saved vs spent), waste cluster grouping (aggregate near-duplicate calls into clusters with total cost and count).
**Hours 9–12**: "One-click fix" suggestions: prompt cache optimizer (detect volatile content in stable prefix), `cached_tool` decorator suggestions. Shareable end-of-run waste report (JSON + formatted summary).

**Key deliverables**: Working demo agent; real-time cost math; cluster grouping; fix suggestions.

---

### Dev 4 — Live UI
**Hours 1–4**: Set up React/Next.js app. Connect to Redis Streams for real-time call feed. Build "live terminal" component showing calls as they fire: tool name, status (BLOCKED / CACHED / EXECUTED), tokens saved, latency saved.
**Hours 5–8**: Dashboard panels: running cost meter ($ spent vs $ saved, animates in real time); worst offender table (top duplicate clusters); loop detection alert banner; cross-agent memory hit indicator.
**Hours 9–12**: Polish: final summary screen with the big "61% of calls were redundant" stat; one-click fix panel; make it demo-able from a single `npm run demo` or `python demo.py`.

**Key deliverables**: Live call feed UI; cost meter; cluster leaderboard; final summary screen.

---

## Milestone Checkpoints

| Time | Gate |
|---|---|
| Hour 2 | Redis connected, exact cache returning hits in terminal |
| Hour 4 | `@redundant.cached_tool()` blocking a duplicate call end-to-end |
| Hour 6 | Semantic match working via LangCache / RedisVL |
| Hour 8 | Demo agent runs; live UI shows real-time call feed with costs |
| Hour 10 | Loop detection + cross-agent LTM dedup demonstrated |
| Hour 12 | Full demo: 74 calls → 61% blocked → $1.13 saved. UI polished. |

---

## Minimum Viable Demo (If Time Runs Short)

Ship these and nothing else:

1. `@redundant.cached_tool(ttl="1h", semantic=True)` decorator that works
2. Redis exact + semantic cache (LangCache or RedisVL)
3. Wasteful demo agent that gets measurably cheaper when Redundant is enabled
4. Terminal output showing blocked calls and final savings summary

The UI is a bonus. The cost savings number is the demo.

---

## Technical Risks + Mitigations

| Risk | Mitigation |
|---|---|
| LangCache similarity threshold too loose → wrong answers served | Build verifier as a hard gate; start with threshold 0.95 for demo |
| Redis Iris Agent Memory API latency adds overhead | Cache the LTM lookup result locally per session; only hit LTM at start of run |
| Demo agent too fast → live UI looks boring | Add `asyncio.sleep(0.3)` between calls; use Redis Streams so UI updates are event-driven, not polled |
| Cacheability class edge cases | For hackathon: hardcode a whitelist of "safe" tools (web_search, github.search_issues, rag.query); everything else defaults to EXECUTE |
| TypeScript SDK runs out of time | Ship Python only; document the pattern so TypeScript is clearly extensible |

---

## What Judges Will See

- **Redis Iris used non-trivially**: LangCache for semantic matching, Agent Memory (session + LTM) for loop detection and cross-agent dedup, RedisVL for clustering, Redis Streams for live UI. All four Iris pillars.
- **Novel angle**: tool call caching, not just LLM response caching. The agent cost problem, not the chatbot problem.
- **Correctness story**: cacheability classes + safety verifier show awareness that naive semantic caching is dangerous.
- **Fun factor**: The live "blocked" counter ticking up in real time while the agent runs. The final "you burned 60% of this run" reveal. The one-click fix suggestions.
- **Scalability angle**: Redis as the shared memory layer means this works across agents, across runs, and horizontally — the same architecture that works for a hackathon demo works for a team running 1,000 agent runs/day.

---

## Repo Structure

```
redundant/
├── sdk/
│   ├── python/
│   │   ├── redundant/
│   │   │   ├── __init__.py
│   │   │   ├── decorator.py      # @cached_tool, .llm() wrapper
│   │   │   ├── canonicalizer.py  # normalize args, compute hash
│   │   │   ├── cache.py          # exact + semantic cache logic
│   │   │   ├── verifier.py       # safety + equivalence verifier
│   │   │   ├── decision.py       # decision engine
│   │   │   ├── loop_detector.py  # session memory loop watch
│   │   │   ├── cost.py           # token pricing + savings math
│   │   │   └── redis_client.py   # Iris connections (LangCache, AgentMemory, RedisVL, Streams)
│   │   └── pyproject.toml
├── demo/
│   ├── wasteful_agent.py         # the demo agent (runs WITHOUT Redundant)
│   └── redundant_agent.py        # same agent, with Redundant wired in
├── ui/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LiveCallFeed.tsx   # real-time call stream
│   │   │   ├── CostMeter.tsx      # $ spent vs $ saved
│   │   │   ├── ClusterTable.tsx   # top duplicate clusters
│   │   │   └── FinalSummary.tsx   # end-of-run waste report
│   │   └── App.tsx
│   └── package.json
└── README.md
```

---

## One-Liner for the Pitch Deck

> **Redundant turns Redis Iris into a cost firewall for AI agents — intercepting redundant LLM calls, tool calls, and agent loops before money is spent, not after.**
