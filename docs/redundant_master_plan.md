# Redundant — Master Planning Document
### Trace-level profiler and cost firewall for multi-agent AI runs

---

## 1. One-Liner

Redundant reads an agent's entire execution trace as a process over time, surfaces behavioral waste that call-level tools structurally can't see — repeated tool calls, re-derived subgoals, redundant sub-agents — pins a dollar cost to each, and routes it to the right fix.

---

## 2. The Problem

AI agents burn money silently. A single multi-agent research run can make 70+ tool and LLM calls, and in practice 40–60% of those calls are redundant — the same tool called by multiple agents independently, the same subgoal re-derived through differently-worded prompts, a flaky tool retried a dozen times with no progress. The developer never sees it. The bill just climbs.

The existing tools don't solve this. Provider-level prompt caching only covers stable prefixes. Call-level semantic caches like Redis LangCache answer "is this one query similar to a past one?" — but they can't see structure. They can't see that three agents independently asked the same question, or that an agent is stuck in a loop, or that two differently-worded LLM calls are pursuing identical intent. Those pathologies are only visible when you read the whole run as a process over time.

Redundant sits one level above the cache. It's the diagnosis layer that decides *what* should be cached and *what* should be paged on.

---

## 3. Core Insight — Protect This

There are two kinds of repeated work in an agent run, and they are not the same problem:

- **Harmless-but-wasteful redundancy** → a caching problem → **LangCache**
- **A genuine runaway loop** → a reliability incident → **Sentry alert**

A stuck agent isn't something you cache around. It's something you page someone about. That fork is the entire point of the product. Everything else is plumbing in service of making that distinction visible and cheap.

---

## 4. Positioning

```
Band (agent run)
   │  XADD span events
   ▼
Redis Streams ──────────▶ Redundant ──────────┬──▶ LangCache (cache the waste)
 (trace bus)        ingest + diagnose          └──▶ Sentry    (alert the runaways)
```

Redis appears at both ends: as the **trace bus** (Streams) and as the **cache** (LangCache). Redundant is the layer in the middle that decides which fix is right for which finding.

No Arize dependency. Arize is removed from the critical path entirely. Band emits spans directly to Redis Streams. The OTel-compatible span schema means Arize could consume it as a reach goal, but nothing in the core product depends on it.

---

## 5. What Redundant Detects

Three distinct pathologies, detected by two distinct methods:

**A. Repetition (frequency detector)**
Group spans by `(tool_name, input_hash)`. A group of N ≥ 2 is a repetition finding. If those N spans come from different `agent_name`s, it's a *redundant sub-agent* finding — multiple agents independently asked the same question. Waste = cost of (N−1) instances.

**B. Structural cycles (cycle detector)**
Build a directed graph over the call tree. Run cycle detection (`networkx.simple_cycles`). Catches A→B→A ping-pong that the frequency pass misses because the inputs may differ slightly each iteration.

**C. Semantic duplicates (clustering — careful)**
Embed each span's `input`, cluster on cosine distance. Cross-agent clusters with the same intent but different surface text = semantic-duplicate subgoals. This is the impressive, fragile third detector. Gate it behind a high similarity threshold and present outputs as *candidates*, visually distinct from deterministic findings. Hard stop at hour 14: if it's noisy on the demo trace, ship deterministic-only and frame semantic as "experimental." Never cut the deterministic detectors to make room for this.

---

## 6. What Redundant Does With Each Finding

One routing decision per finding, defined by a clear rule:

| Condition | Severity | Route |
|---|---|---|
| `count ≥ R_max` (10) | runaway | alert → Sentry |
| `evidence.convergence == "none"` (outputs not changing) | runaway | alert → Sentry |
| Any implicated tool is side-effecting (allowlist) | runaway | alert → Sentry |
| Everything else redundant (incl. all semantic dups) | wasteful | cache → LangCache |

Judge answer: *"Low-count, convergent, read-only redundancy is cacheable waste. High-count, non-converging, or side-effecting repetition is a reliability incident."*

---

## 7. The Verifier (Gating LangCache)

The verifier is not a magic side-effect detector. It is two explicit, demoable gates:

1. **Cacheability gate (write-time)** — a tool is cached only if it's in the read-only allowlist: `web_search: read`, `scan_repo: read`, `send_email: write`, `db_write: write`. Anything not explicitly read is treated as side-effecting and never cached. This is the honest answer to "how do you know it's safe to cache?"

2. **Staleness gate (read-time)** — each cache entry carries a TTL and an `input_hash`. A read is served only on exact `input_hash` match within TTL. Otherwise it's a miss and the call runs for real.

LangCache is keyed on `(tool_name, input_hash)`. Both gates wrap every read and write. No inference, no guessing.

---

## 8. Data Contracts — Lock at Hour 0

These two shapes are the contract between all four sections. Lock them before anyone writes real logic. Everyone mocks against them from hour 0.

### 8.1 Span (emitted by Band → Redis Streams)

```json
{
  "span_id": "s_07",
  "parent_span_id": "s_03",
  "kind": "tool",
  "name": "tool:web_search",
  "tool_name": "web_search",
  "agent_name": "researcher_a",
  "input": "population of france 2024",
  "output": "~68 million",
  "input_hash": "a1b2c3",
  "start_time": 1718877601200,
  "end_time": 1718877602900,
  "tokens": { "input": 1800, "output": 320 },
  "model": "gpt-4o"
}
```

Stream key: `trace:{run_id}`. One `XADD` entry per span, span JSON in a single `data` field.

**Critical hour-0 check**: confirm `tokens` and `model` survive Band's instrumentation. The entire dollar story depends on these two fields. If Band can't capture real token usage, decide the fallback (estimate from text length) at hour 0, not hour 16.

### 8.2 Finding (produced by Redundant, consumed by UI)

```json
{
  "finding_id": "f_12",
  "type": "repetition",
  "span_ids": ["s_07", "s_11", "s_15"],
  "representative_span_id": "s_07",
  "count": 3,
  "description": "web_search called 3× with identical args across 3 sub-agents",
  "token_cost": { "input": 5400, "output": 960 },
  "dollar_cost": 0.21,
  "severity": "wasteful",
  "route": "cache",
  "cacheable": true,
  "evidence": {
    "similarity": 0.94,
    "cycle_path": null,
    "convergence": "none"
  }
}
```

### 8.3 Cost Rollup (served by FastAPI, displayed by UI)

```json
{ "total_cost": 1.42, "wasted_cost": 0.42, "wasted_pct": 0.30, "finding_count": 3 }
```

### 8.4 Re-run / Savings Response

```json
{
  "run_id": "run-001",
  "original_cost": 1.42,
  "cached_cost": 1.21,
  "saved": 0.21,
  "cache_hits": [
    { "finding_id": "f_12", "tool": "web_search", "served_from_cache": true, "saved": 0.21 }
  ]
}
```

---

## 9. Architecture

```
Band agents (research-assistant team)
  │
  │  XADD spans to Redis Streams: trace:{run_id}
  ▼
┌─────────────────────────────────────────────┐
│  Redis Streams                               │  ordered, timestamped, persistent
│  stream key: trace:{run_id}                  │  one entry per span
└─────────────────────┬───────────────────────┘
                      │
                      │  XRANGE (batch) / XREADGROUP (live — stretch)
                      ▼
┌─────────────────────────────────────────────┐
│  Ingestion → Normalized Trace                │  spans → in-memory tree + directed call graph
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│  Detection Engine                            │
│  A. Repetition detector  (frequency)         │  group by (tool_name, input_hash)
│  B. Cycle detector       (structure)         │  networkx.simple_cycles
│  C. Semantic clustering  (careful — §5)      │  sentence-transformers + cosine distance
│  D. Cost attribution                         │  span_cost = tokens × price_table(model)
│  E. Routing brain        (wasteful/runaway)  │  R_max + convergence + allowlist
└──────────────┬──────────────────────────────┘
               │  Findings[]
    ┌──────────┴──────────┐
    ▼                     ▼
┌───────────┐    ┌────────────────────────────┐
│  FastAPI  │    │  Remediation Router         │
│ /findings │    │  route=="cache" → LangCache │
│ /rerun    │    │  route=="alert" → Sentry    │
└─────┬─────┘    └────────────┬───────────────┘
      │                       │
      ▼                  ┌────┴──────────────────────┐
┌──────────────┐         ▼                           ▼
│  Flamegraph  │  ┌─────────────────┐    ┌──────────────────────┐
│  UI (React)  │  │  LangCache       │    │  Sentry               │
│  red=finding │  │  + verifier gate │    │  alert / incident     │
└──────────────┘  └─────────────────┘    └──────────────────────┘
```

FastAPI serves `Findings[]` as JSON. The UI and the router both consume that one contract. The UI never reads Redis directly.

---

## 10. The Demo Trace (Band's Job)

A "research-assistant team" with scripted pathologies — one cacheable redundancy, one semantic duplicate, one runaway loop, and enough legitimate work that waste is a clear slice of total cost (target: waste ≈ 20–40% of total).

| Agent | Action | Pathology |
|---|---|---|
| `planner` | 1 LLM call — decompose task | baseline |
| `researcher_a` | `web_search("population of france 2024")` | BR-1 — exact match |
| `researcher_b` | `web_search("population of france 2024")` | BR-1 — exact match |
| `researcher_c` | `web_search("population of france 2024")` | BR-1 — exact match |
| `researcher_a` | `web_search("france gdp 2024")` | baseline — distinct |
| `writer` | LLM: *"summarize France's population trend"* | BR-2 — semantic A |
| `writer` | LLM: *"overview of how France's population is changing"* | BR-2 — semantic A reworded |
| `writer` | LLM: draft the report | baseline — distinct |
| `fact_checker` | `verify_source(...)` ×12, non-converging output | BR-3 — runaway → alert |

The run MUST be frozen to a JSON file that replays cleanly via `XADD`. The live demo cannot depend on an LLM behaving identically each attempt. Freeze the trace by hour 6 at the latest — everything downstream (UI, detection, demo rehearsal) is blocked until this exists.

Total spans: ~30–60. Big enough to look real, small enough that the flamegraph is legible and the loop is visually obvious.

---

## 11. The Demo (3-Minute Storyboard)

**0:00** — "Here's a multi-agent research run. Looks fine. Cost $1.42 and nobody knows why." Flamegraph loads. Spans render gray.

**0:30** — Red bars light up. Headline reveals: **"$0.42 wasted of $1.42 — 30%."** Three findings listed in the sidebar.

**1:00** — Click the red sub-agent cluster: "3 agents asked the same question — $0.21 — cache candidate." Show it routed to LangCache. Hit Re-run. Cost drops from $1.42 → $1.21. Green delta.

**1:45** — Click the deep-red wall: "verify_source called 12 times, outputs not changing — this isn't caching, it's an incident." Sentry alert fires on screen. Incident badge on the flamegraph.

**2:30** — Land the stack: "Band ran the agents. Redis Streams carried the trace. Redundant diagnosed it. LangCache absorbed the waste. Sentry caught the runaway. The dollars saved are the payoff of the diagnosis, not the headline."

Record a backup video by hour 22. Live demos die.

---

## 12. Sponsor Integration Story

Every sponsor has a clear, one-sentence role in the product. No bolted-on integrations.

| Sponsor | Role |
|---|---|
| **Band** | Generates the demo trace — the multi-agent run that produces every pathology Redundant detects |
| **Redis Streams** | The trace bus — every span arrives here; Redundant reads it with `XRANGE` (batch) or `XREADGROUP` (live) |
| **Redis LangCache** | Absorbs wasteful-redundancy findings after the verifier gates them |
| **Terac** | Human-labeled annotation dataset that validates the verifier's decisions on held-out call pairs; the eval story |
| **Sentry** | Receives `sentry_sdk.capture_message()` when a runaway finding fires; alert visible on screen during demo |
| **The Token Company** | Compression path: when a call is unsafe to cache but its prompt is bloated, compress before executing |
| **Anthropic** | Claude is the LLM being called in the demo; prompt-cache layout recommendation appears in fix suggestions |

**Arize: removed from core.** No Arize dependency anywhere in the critical path. If the core Redis Streams path is stable with hours to spare, Arize can receive a mirrored OTel export as a reach goal tab — but nothing builds toward or depends on that.

---

## 13. Four-Person Work Split (24 Hours)

### Owner 1 — Redis Core + Detection Engine
*Owns: ingestion, detection, cost attribution, routing, LangCache, FastAPI backend.*

**Hours 0–2 (Setup)**
Lock the Finding schema (§8.2) with the team. Define the `XADD` span convention for Band. Hand-author a frozen trace JSON with all 3 pathologies. Scaffold FastAPI `/findings` returning mock Findings[]. Smoke-test Redis: `XADD`/`XRANGE` round-trip and `SET`/`GET`.

**Hours 2–6 (Deterministic core — unblocks everyone)**
Trace loader: spans → in-memory tree + directed call graph. Repetition detector (group by tool+input_hash; cross-agent tag). Cycle detector (`networkx.simple_cycles`). Cost attribution + `$wasted/$total` rollup. Done when: frozen trace → real Findings[] with dollars, live on `/findings`. This unblocks the UI and the router.

**Hours 6–9 (Redis Streams ingestion)**
Batch consumer: `XRANGE trace:{run} - +` → same normalized spans the detector already eats. Swap frozen trace for live stream read. Done when: a real Band stream flows end-to-end into Findings[].

**Hours 9–12 (LangCache + verifier skeleton)**
Cache key `(tool_name, input_hash)`. Write path caches a wasteful finding's result. Read path looks it up. Stubbed verifier = hardcoded read-only allowlist. Done when: a wasteful finding round-trips through the cache.

**Hours 12–14 (Routing brain)**
Wasteful-vs-runaway logic: `R_max`, convergence check, side-effect override → set `severity` + `route` on every finding. Emit `route=="alert"` findings for Sentry owner. Done when: every finding carries correct severity + route.

**Hours 14–17 (Real verifier + visible savings)**
Two gates: read-only allowlist (write-time) + TTL/input_hash (read-time). Tool registry. Re-run path: duplicated call served from cache → cost drops → savings land in UI. Done when: re-run shows cache HIT and dollars saved on screen.

**Hours 17–20 (Optional depth — only if core is solid)**
Semantic clustering (candidates). Live mode: `XREADGROUP` incremental detection → fire Sentry mid-run. Only pursue if deterministic core is bulletproof.

**Hours 20–24 (Freeze + demo)**
Feature freeze. Bulletproof the one golden demo path. Help record backup video. Prep judge answers.

**Degradation ladder (cut in this order):** semantic clustering → live XREADGROUP mode → managed LangCache (drop to DIY `SET/GET EX`) → convergence sophistication (fall back to plain `R_max`) → TTL staleness (exact-hash only). **Never cut:** deterministic detectors, cost attribution, `/findings`, one visible cache hit, one `route=="alert"` handoff to Sentry.

---

### Owner 2 — Band Multi-Agent Workflow
*Owns: the demo trace generator — the input that makes everything else visible.*

**Hours 0–2 (Contracts)**
Agree on span schema and `XADD` convention with Owner 1. Resolve the Band instrumentation question: how does Band expose per-span token usage? If it doesn't, decide the fallback estimation now. This is the hour-0 check — nothing dollar-denominated works without it.

**Hours 2–8 (Build the messy run)**
Band room with agents: `planner`, `researcher_a/b/c`, `writer`, `fact_checker`. Wire all agents through the same Redundant-aware XADD span emission. Produce all three pathologies (exact-match cross-agent redundancy, semantic duplicate, 12× runaway loop) plus enough distinct legitimate work that waste is ~20–40% of total cost.

**Hours 8–12 (Freeze and validate)**
Freeze the trace to a canonical JSON file. Validate against the span schema — every span has non-null `tokens` and `model`. Validate `input_hash` normalization matches what Owner 1's detector expects (same function, same output). Confirm the frozen trace replays cleanly end-to-end through the detection engine and produces the expected three findings.

**Hours 12–16 (Harden + stretch)**
Validate demo timing: run completes in under 2 minutes live, loop is visually obvious in flamegraph (~12 sibling bars), waste fraction reads correctly in the headline. Stretch: live emission mode — emit spans to stream as they happen rather than batch-at-end, so XREADGROUP detection can fire the Sentry alert mid-run.

**Hours 16–24 (Support + freeze)**
Help rehearse the demo. Record the backup video of a clean run. Stay available for schema questions from other owners.

**Acceptance criteria before handing off the frozen trace:**
- Detector reports ≥1 redundant sub-agent finding (3 cross-agent, same input_hash)
- Detector reports ≥1 semantic-duplicate candidate
- Detector reports ≥1 runaway finding (count ≥ 12, non-converging) routed to alert
- Total cost > wasted cost; waste ≈ 20–40%
- Every span validates against schema — non-null tokens and model on every llm/tool span
- Frozen trace replays cleanly via XADD

---

### Owner 3 — Terac Verifier + Evaluation
*Owns: making semantic caching trustworthy, not hand-wavy.*

**Hours 0–4 (Annotation dataset)**
Build a small dataset of call pairs: (new call, cached candidate, candidate output, task context, human label). Labels: `safe_reuse`, `not_equivalent`, `needs_freshness_check`, `state_specific`, `side_effect_risk`. Aim for ~30–50 labeled pairs covering the demo agent's tools.

**Hours 4–10 (Verifier + eval)**
Use Terac's annotation tooling to collect labels during the sprint. Build lightweight verifier: minimum viable = rules + labeled examples + small LLM judge prompt. Evaluation: compare raw Redis similarity threshold alone vs. Terac verifier-gated reuse on held-out pairs. Produce the eval table: unsafe cache hits before verifier, unsafe cache hits after verifier, savings retained.

**Hours 10–16 (Integration + demo beat)**
Wire the verifier into Owner 1's cache path. Validate the key demo beat: one unsafe semantic match that Redis finds (similarity above threshold) but the Terac verifier blocks. This is the moment that shows judges the verification layer is real, not just a threshold. Produce the held-out eval table for the UI sponsor tab.

**Hours 16–24 (Polish + pitch support)**
Prepare the three-sentence verifier explanation for judges: "Redis finds candidates by vector similarity. Terac-labeled examples teach the verifier when reuse is actually safe. Without it, a high-similarity match on a state-bound or side-effecting call would serve a wrong or dangerous result." Help record backup video.

---

### Owner 4 — Dashboard UI
*Owns: the flamegraph dashboard — the surface where the diagnosis becomes visible and the dollar payoff lands.*

**The UI spec lives in UI_REQUIREMENTS.md. What follows is the build sequence and the decisions made in the design discussions above.**

**Hours 0–2 (Setup + mock data)**
Scaffold React + Vite app. Implement the static-JSON fallback (UR-13) first — load a local `findings.json` and render. This is the foundation: the UI must work without a live backend, always. Wire the color system and typography (see §14).

**Hours 2–6 (Flamegraph — the core view)**
Build the flamegraph as custom SVG. Off-the-shelf flamegraph libs assume time-only semantics and fight you on per-span color overlay and cycle annotations — custom SVG gives full control. Depth = call nesting from `parent_span_id`. X-axis = time from `start_time`/`end_time`. Individual sibling bars for repeated calls — the 12× loop should render as a visible wall of identical bars, not a merged node. Hover tooltip: `name`, `model`, `tokens`, duration, dollar cost.

**Hours 6–10 (Findings overlay + headline)**
Color semantics:
- Gray-blue: legitimate work
- Red (intensity scales with `dollar_cost`): wasteful redundancy (`route=="cache"`)
- Deep red + incident badge: runaway (`severity=="runaway"`, `route=="alert"`)
- Amber / hatched fill: semantic-duplicate candidate (signals lower confidence)

Headline banner: **"$X wasted of $Y total"** — prominent, revealed after the run renders, not before. Findings list sidebar: grouped by route (cache vs alert), each clickable to highlight its spans in the flamegraph. Root-cause panel: clicking a marked span opens a panel with finding `description`, `type`, `count`, `dollar_cost`, `route`, and `evidence` in plain language.

**Hours 10–14 (Remediation visualization)**
Re-run control: button triggers `POST /rerun`, on response shows duplicated calls served from cache, per-finding `saved`, and total cost dropping from `original_cost` → `cached_cost`. Animate the delta in green. This is a core demo beat — without it the cache work is invisible. Runaway finding reads as a fired incident: "Sentry alert fired" label, incident badge on the flamegraph bar.

**Hours 14–18 (Sponsor tabs + live feed)**
Sponsor tabs across the bottom or side: Redis evidence (which findings went to cache, LangCache key used), Sentry issues (runaway findings with dollar impact), Terac verifier/eval table (the held-out eval from Owner 3), Band collaboration view (which agent produced which spans). Live event feed connecting to `/stream` SSE endpoint as a secondary panel — not the primary view, but shows the run building in real time when demoed live.

**Hours 18–22 (Polish + SDK surface)**
SDK surface in fix suggestions: each `SuggestedFix` in the final report shows the `code_hint` that would prevent the waste, e.g. wrapping a tool with the cache decorator. This is where the SDK appears — as the solution to waste just demonstrated, not as a setup step. Final summary screen: redundant rate, waste breakdown by category, worst duplicate cluster, total saved. Screenshot-beautiful for Devpost.

**Hours 22–24 (Demo hardening)**
Verify full demo path works from static JSON fallback. Verify live path works with Owner 1's backend. Make demo launchable in one command. Support backup video recording.

**Degradation order (cut in this order if behind):** live SSE feed → sponsor tabs → SDK surface in fixes → semantic candidate amber hatching. **Never cut:** flamegraph with red overlay, headline banner, root-cause panel, re-run savings animation, runaway incident badge.

---

## 14. UI Design System

**Theme:** dark, dense, information-forward. Terminal that learned to show money. Not a marketing site — no gradients on backgrounds, no glass morphism. Tight spacing, hairline borders, `4px` radius on data elements, `8px` on cards.

**Color palette:**

```
Background:           #0A0A0F   near-black, slight blue tint
Surface (cards):      #111118
Border:               #1E1E2E
Muted text:           #4A4A6A   timestamps, labels
Body text:            #C8C8DC   slightly cool white

EXECUTE / legitimate: #4A4A6A   gray — unremarkable, just ran
EXACT_REUSE:          #00E5A0   mint green — money saved, no ambiguity
SEMANTIC_REUSE:       #00B8E5   cyan — saved, but with a confidence score
COMPRESS_AND_EXECUTE: #F5A623   amber — not saved but reduced, partial win
BLOCK_OR_WARN:        #FF4545   red — loop or side-effect, money at risk

Cost saved accent:    #00E5A0   same mint — savings = green
Cost spent:           #FF4545   same red — burning money = red
```

**Typography:**
- `JetBrains Mono` — all numbers, cost figures, token counts, the event feed, code hints
- `Inter` — all labels, descriptions, agent names, prose

The burn meter hero: `$1.13` in JetBrains Mono at 48px in mint green. This is the one number judges remember.

**Decision badge:** pill-shaped, filled with the decision color, white label in JetBrains Mono. The rest of each event row is quiet so the badge reads immediately.

**Dashboard type:** web app (Vite + React), served locally, demoed from the presenter's machine. Zero install friction for judges. Electron pivot is available in ~30 minutes if wanted (point Electron's BrowserWindow at the Vite dev server), but the web app is the build target.

---

## 15. Milestone Checkpoints

| Time | Gate | Owner |
|---|---|---|
| Hour 0 | Span schema + Finding schema agreed and in writing. Frozen mock trace authored. `/findings` returning mock data. `tokens`/`model` question resolved. | All |
| Hour 2 | Redis `XADD`/`XRANGE` smoke-tested. UI renders flamegraph from static JSON. Band run producing spans. | 1, 2, 4 |
| Hour 6 | Frozen trace → real Findings[] with dollars on `/findings`. UI overlays red on findings. Band trace frozen to JSON. | 1, 2, 4 |
| Hour 9 | Redis Streams batch consumer live. End-to-end: Band XADD → detection → `/findings` → UI red overlay. | 1 |
| Hour 12 | LangCache round-trip working. Routing brain emitting correct severity + route. Terac verifier blocking one unsafe hit. | 1, 3 |
| Hour 16 | Re-run shows cache hit and cost dropping in green in UI. Sentry alert fires on runaway finding. | 1, 4 |
| Hour 20 | Full demo path end-to-end: Band run → flamegraph → red overlay → click finding → re-run → cost drops → Sentry fires. | All |
| Hour 22 | Feature freeze. Backup video recorded. Pitch rehearsed. | All |
| Hour 24 | Demo. | — |

---

## 16. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Band doesn't populate tokens/model per span | Resolve at hour 0; fallback = estimate tokens from text length; never leave null |
| Live Band run behaves differently each attempt | Freeze canonical trace by hour 6; demo from frozen replay; live run is a flourish |
| Semantic clustering mislabels on stage | High threshold; "candidate" framing; hard stop at hour 14; ship deterministic-only if noisy |
| LangCache managed service flaky | DIY fallback: `SET cache:{tool}:{input_hash} <result> EX <ttl>` / `GET` — fully in Owner 1's control |
| Flamegraph custom SVG takes too long | Fall back to a D3 tree layout with colored nodes — same visual effect, less SVG math |
| Demo agent run finishes before judges look up | Add `asyncio.sleep(0.3)` between span emissions in replay mode; use SSE so UI updates are event-driven |
| Four people awake 24h → broken demo at hour 23 | Staggered rest in shifts during hours 8–20; one person always awake |
| Integration between owners eats the last hours | Feature freeze at hour 20; one golden demo path made bulletproof before adding anything else |

---

## 17. What Judges Will See

- **Redis used non-trivially at both ends**: Streams as the trace bus (not just a queue — the ordered span log is the trace), LangCache as the cache with a verifier gate, DIY fallback showing Redis primitives. Not "we put responses in a hash."
- **A real diagnosis, not a dashboard**: the flamegraph shows structural waste — loops, redundant sub-agents, duplicate subgoals — that a call-level cache can't see by definition. This is the core differentiator.
- **The routing fork**: the LangCache / Sentry split shows the product understands the difference between inefficiency and failure. That's the one-sentence pitch that lands.
- **Correctness story**: the verifier's allowlist + TTL gates give an honest answer to "how do you know it's safe to cache?" No hand-waving.
- **The visual moment**: deep-red wall of 12 identical bars, incident badge, dollar cost, Sentry alert firing. Before a word is said.
- **Sponsor story that feels like one product**: Band ran it, Redis Streams carried it, Redundant diagnosed it, LangCache absorbed the waste, Terac verified the safety, Sentry caught the runaway.

---

## 18. Repo Structure

```
redundant/
├── core/
│   ├── ingestion/
│   │   ├── stream_consumer.py     # XRANGE batch + XREADGROUP live
│   │   └── normalizer.py          # spans → normalized trace + call graph
│   ├── detection/
│   │   ├── repetition.py          # frequency detector — group by (tool, input_hash)
│   │   ├── cycles.py              # structural cycle detector — networkx
│   │   ├── semantic.py            # embedding + cosine clustering — careful
│   │   └── cost.py                # token pricing + dollar attribution
│   ├── routing/
│   │   ├── brain.py               # wasteful vs runaway decision
│   │   └── allowlist.py           # read-only tool registry
│   ├── cache/
│   │   ├── langcache.py           # LangCache write + read path
│   │   ├── verifier.py            # cacheability gate + staleness gate
│   │   └── fallback.py            # DIY SET/GET EX if LangCache flaky
│   └── api/
│       └── main.py                # FastAPI: /findings, /rerun, /stream SSE
├── band/
│   ├── agents/
│   │   ├── planner.py
│   │   ├── researcher.py          # researcher_a, _b, _c
│   │   ├── writer.py
│   │   └── fact_checker.py        # the looper
│   ├── span_emitter.py            # XADD wrapper used by all agents
│   └── traces/
│       └── frozen_run_001.json    # canonical frozen trace — committed to repo
├── eval/
│   ├── annotations/               # Terac-labeled call pairs
│   ├── verifier_eval.py           # raw threshold vs verifier on held-out pairs
│   └── results/
│       └── eval_table.json        # the held-out eval table for UI sponsor tab
├── ui/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Flamegraph.tsx      # custom SVG flamegraph, red overlay
│   │   │   ├── FindingsSidebar.tsx # grouped cache/alert list, clickable
│   │   │   ├── RootCausePanel.tsx  # finding detail on span click
│   │   │   ├── HeadlineBanner.tsx  # $X wasted of $Y
│   │   │   ├── RerunSavings.tsx    # cache hit + cost drop animation
│   │   │   ├── LiveEventFeed.tsx   # SSE event stream panel
│   │   │   └── SponsorTabs.tsx     # Redis / Sentry / Terac / Band tabs
│   │   ├── App.tsx
│   │   └── mockData.ts            # static findings JSON for fallback
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

---

## 19. One-Liner for the Pitch

> **Redundant reads your agent's entire run as a process, finds the loops and duplicate reasoning your cache can't see, and routes each finding to the right fix — LangCache for the waste, Sentry for the runaways.**
