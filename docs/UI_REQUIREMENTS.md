# UI / Dashboard Section — Requirements

*The flamegraph dashboard. The demo surface where the diagnosis becomes visible and the dollar payoff lands.*

Companion to `DESIGN_redis.md`. Consumes the Span schema (§6.1) and Finding schema (§6.2) defined there; restated here as the hard contract.

---

## 1. Purpose

Render an agent run as a **flamegraph with every loop and duplicate lit up red and a dollar cost pinned to each**, so a viewer instantly sees *where* the waste is, *what kind* it is, and *how much it cost* — then watches it get cached or alerted on. This is the screen the demo is driven through; if the waste isn't visually obvious here, the whole diagnosis falls flat.

The design principle: **the dollars are the payoff of the diagnosis, not the headline.** Lead with the lit-up run, then reveal the cost.

## 2. Dependencies & position

The UI is **downstream of the core owner**. It consumes:
- `GET /findings` → the normalized trace + `Findings[]` (+ the cost rollup).
- `POST /rerun` (or equivalent) → the cache-hit savings response.

The demo is presented *through* this UI, so it's the integration endpoint where everyone's work becomes visible. It MUST be able to render from a **static JSON file** too (see UR-13), so it's never blocked on the live backend.

## 3. Data it consumes

### 3.1 Spans (for the flamegraph tree)
Per `DESIGN_redis.md §6.1` — key fields the UI reads: `span_id`, `parent_span_id`, `kind`, `name`, `tool_name`, `agent_name`, `input`/`output` (for tooltips), `start_time`/`end_time` (bar width), `tokens`, `model`.

### 3.2 Findings (the red overlay)
Per `DESIGN_redis.md §6.2` — key fields: `type`, `span_ids`, `count`, `description`, `dollar_cost`, `severity`, `route`, `cacheable`, `evidence`.

### 3.3 Cost rollup (the headline)
```json
{ "total_cost": 1.42, "wasted_cost": 0.42, "wasted_pct": 0.30, "finding_count": 3 }
```

### 3.4 Re-run / savings response (coordinate exact shape with core owner)
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

## 4. Functional requirements

### Flamegraph

- **UR-1 · Tree rendering.** Render spans as a flamegraph: **depth = call nesting** (from `parent_span_id`), **x-axis = time/order** (from `start_time`/`end_time`), bar labeled with `name` (and `agent_name`). Sub-agent spans nest under their spawning agent.
- **UR-2 · Don't collapse repeats.** Repeated tool calls MUST render as **individual sibling bars**, not merged. The 12× runaway loop should read as a visible *wall* of identical bars — that wall is the money shot.
- **UR-3 · Cost on hover.** Hovering a bar shows `name`, `model`, `tokens`, duration, and that span's dollar cost.

### Findings overlay & color semantics

- **UR-4 · Light up findings.** Every span in any finding's `span_ids` MUST be visually marked. Color carries meaning:
  - Neutral / legitimate work → muted gray-blue.
  - **Wasteful redundancy (`route=="cache"`)** → red; intensity scales with `dollar_cost`.
  - **Runaway (`severity=="runaway"`, `route=="alert"`)** → deepest red + an **incident badge**.
  - **Semantic-duplicate candidate (`type=="semantic_duplicate"`)** → amber / hatched fill (signals lower confidence, distinct from deterministic red).
- **UR-5 · Cycle annotation.** A flamegraph is a tree and can't natively show a back-edge. For `type=="cycle"`, overlay an explicit marker on the involved spans (badge or connecting arc) using `evidence.cycle_path`.
- **UR-6 · Legend.** A small always-visible legend explaining the color/badge semantics.

### Headline & root cause

- **UR-7 · Headline banner.** Persistent banner: **"$X wasted of $Y total"** (+ `wasted_pct`, `finding_count`). This is the one number judges remember — make it prominent but reveal it *after* the run renders, not before.
- **UR-8 · Root-cause panel.** Clicking a marked span (or a findings-list item) opens a panel with the finding's `description`, `type`, `count`, `dollar_cost`, `route`, and `evidence`. Plain-language, e.g. *"3 sub-agents asked the same question — $0.21 — cache candidate."*
- **UR-9 · Findings list.** A side list of all findings, grouped by `route` (cache vs alert), each clickable to focus/highlight its spans in the graph.

### Remediation visualization

- **UR-10 · Route badges.** Each finding visibly shows its destination — a **cache** icon (→ LangCache) or an **alert** icon (→ Sentry).
- **UR-11 · Cache-hit savings view.** A control to trigger the re-run; on response, show the duplicated calls **served from cache**, the per-finding `saved`, and the total cost dropping from `original_cost` → `cached_cost`. Animate or clearly delta the savings in **green**. This is a core demo beat — without it the cache work is invisible.
- **UR-12 · Alert state.** The runaway finding MUST visibly read as an incident ("Sentry alert fired") — the actual firing is the Sentry owner's; the UI reflects the state.

### Robustness

- **UR-13 · Static-JSON fallback.** The UI MUST render fully from a **local findings JSON** (no backend). This decouples it from the core during build and protects the demo if the live backend wobbles — the UI equivalent of the frozen trace.

## 5. Demo-beat mapping (the UI must support each)

| Beat (DESIGN §9 storyboard) | UI requirement |
|---|---|
| Run loads, "looks fine, cost $Y" | UR-1, UR-7 (banner pre-reveal) |
| Red lights up: "$X wasted" | UR-4, UR-7 |
| Click sub-agent cluster → "same question 3×, cache" | UR-8, UR-10 |
| Re-run → cost drops | UR-11 |
| Click deep-red bar → "12× loop, incident" | UR-2, UR-8, UR-12 |
| Land the stack | UR-9, UR-10 |

## 6. Non-functional requirements

- **UR-14 · Legible at demo scale.** Clean and readable at ~30–60 spans; the loop must be obvious without zooming.
- **UR-15 · Fast.** Renders in well under a second from loaded data; no jank when opening panels.
- **UR-16 · Screenshot-beautiful.** This screen goes on slides. Intentional typography, spacing, and color — not default-template look. Follow good frontend-design practice.
- **UR-17 · Presenter-ready.** Works at the presentation resolution/aspect; no horizontal scrolling to find the loop; high contrast for projector visibility.

## 7. Reference layout (wireframe)

```
┌───────────────────────────────────────────────────────────────┐
│  REDUNDANT            $0.42 wasted of $1.42  (30%)  · 3 findings │  ← UR-7
├──────────────────────────────────────────────┬────────────────┤
│                                                │  FINDINGS       │
│   planner ▓▓                                   │  ── cache ──    │  ← UR-9
│     researcher_a ██ web_search   (red)         │  ▸ 3× web_search│
│     researcher_b ██ web_search   (red)         │     $0.21  ⤴cache│  ← UR-10
│     researcher_c ██ web_search   (red)         │  ▸ dup subgoal  │
│   writer ▓▓ ▒▒(amber dup) ▓▓                    │     $0.06  ⤴cache│
│   fact_checker ████████████ verify ×12 (deep)  │  ── alert ──    │
│            ▲ incident badge                    │  ▸ 12× verify    │
│                                                │     loop ⚠alert │  ← UR-12
│  [ Re-run with cache ]  saved $0.21 → $1.21    │                 │  ← UR-11
├──────────────────────────────────────────────┴────────────────┤
│  Legend: ▓ legit  ██ waste(cache)  ████ runaway(alert)  ▒ semantic│  ← UR-6
└───────────────────────────────────────────────────────────────┘
```

## 8. Acceptance criteria (definition of done)

- [ ] Flamegraph renders the tree with correct nesting from `parent_span_id` — UR-1.
- [ ] Repeated calls show as individual sibling bars (visible wall) — UR-2.
- [ ] All finding spans lit, with correct color per route/severity/type — UR-4.
- [ ] Semantic candidates visually distinct from deterministic findings — UR-4.
- [ ] Cycle findings carry an explicit annotation — UR-5.
- [ ] Headline "$X of $Y" banner present and prominent — UR-7.
- [ ] Click a finding → root-cause panel with cost + plain-language cause — UR-8.
- [ ] Findings list grouped by cache vs alert, clickable — UR-9, UR-10.
- [ ] Re-run shows cache hits and total cost dropping in green — UR-11.
- [ ] Runaway reads as a fired incident — UR-12.
- [ ] Renders fully from a static findings JSON, no backend — UR-13.
- [ ] Legible, fast, and presentation-clean at demo scale — UR-14..17.

## 9. Tech stack (suggested)

| Concern | Choice |
|---|---|
| Framework | React |
| Flamegraph | `d3-flame-graph`, a speedscope-style renderer, or custom SVG (custom gives the most control over the red/amber overlay) |
| Styling | Whatever the team standardizes on; prioritize contrast + clean type |
| Data | Fetch `/findings` and `/rerun`; **also** accept a local JSON for fallback (UR-13) |

Custom SVG is often the safest bet here — off-the-shelf flamegraph libs assume time-only semantics and fight you on the per-span color overlay and the cycle annotations.

## 10. Open questions / TBD

- **Bar width: time or cost?** Default to **time** (familiar; makes the loop a long wall). Cost is shown via color intensity + tooltips + the headline. Revisit if cost-width tells the story better.
- How to render the 12× loop compactly if it dominates width — cap the visible repeats with a "×12" marker, or let the wall run?
- Re-run: live call to the core's `/rerun`, or a pre-baked "after" JSON for demo safety? (Pre-baked is the safer demo path.)
- Exact `/findings` and `/rerun` response shapes — confirm field names with the core owner before building.
