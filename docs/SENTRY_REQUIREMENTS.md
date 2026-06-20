# Sentry Section — Requirements

*The alert arm. Turns runaway-loop findings into reliability incidents — the half of remediation that says "a stuck agent isn't a caching problem, page someone."*

Companion to `DESIGN_redis.md`. Consumes the Finding schema (§6.2) defined there.

---

## 1. Purpose

When the routing brain classifies a finding as `route == "alert"` — a runaway loop or a side-effecting redundancy — the Sentry section fires a **Sentry event rich enough to act on**: which agent, which tool, how many iterations, how many dollars burned, and that it isn't converging. This is the second remediation arm; LangCache absorbs the harmless waste, Sentry escalates the dangerous repetition.

The core owner *classifies*; this section *fires*. The UI *reflects* the fired state. Keep that split clean.

## 2. Dependencies & position

- **Upstream:** the core router hands off `route == "alert"` findings (interface in §4).
- **Downstream:** the UI shows the runaway as a fired incident (UR-12). This section must make the fired state observable to the UI.
- **External:** a Sentry project + DSN.

## 3. What it consumes

Alert-routed findings, per `DESIGN_redis.md §6.2`. The fields this section reads:
`finding_id`, `type`, `span_ids`, `representative_span_id`, `count`, `description`, `dollar_cost`, `severity` (`runaway`), `route` (`alert`), `cacheable` (`false` for side-effecting), `evidence.convergence`, plus the owning `agent_name` / `tool_name` from the representative span.

Two reasons a finding routes to alert, which produce **different** incidents:
1. **Runaway loop** — `count ≥ R_max` or `convergence == "none"`.
2. **Side-effecting redundancy** — a redundant call to a write tool the verifier refused to cache.

## 4. Interface with the core (pick one, lock it hour 0)

- **Option A (simple, default):** the core router calls an in-process `dispatch_alert(finding) -> ack`.
- **Option B (decoupled, on-theme):** the core router writes alert findings to a Redis stream/channel `alerts:{run_id}`; this section consumes them (`XREADGROUP` / pub-sub) and fires. Fits the Redis-centric design and enables live mode cleanly.

Either way, define `dispatch_alert(finding)` as the contract and agree it with the core owner before building.

## 5. Functional requirements

- **SR-1 · SDK init.** Initialize the Sentry SDK (`sentry-sdk`) from a `SENTRY_DSN` env var at startup. No DSN → fall back to mock mode (SR-9), never crash.

- **SR-2 · Consume alert findings.** Accept every `route == "alert"` finding via the §4 interface and fire exactly one incident per finding (subject to dedup, SR-6).

- **SR-3 · Rich event content.** Each event MUST carry:
  - **Message** — a plain-language incident title, e.g. *"Runaway agent loop: fact_checker retried verify_source 12× — $0.30 burned, no convergence."*
  - **Level** — `error` for runaways (`fatal` if cost or count is extreme); `warning` for side-effecting redundancy.
  - **Tags** (for filtering): `run_id`, `agent`, `tool`, `finding_type`, `severity`.
  - **Context** — a `redundant_finding` block with `finding_id`, `count`, `dollar_cost`, `convergence`, `span_ids`.

- **SR-4 · Distinguish the two alert reasons.** Runaway loops and side-effecting redundancies MUST produce visibly different incidents (different message + fingerprint), so the demo can show "this one's an incident because it's stuck" vs "this one's an incident because it's an un-cacheable write."

- **SR-5 · Fingerprinting.** Set an explicit fingerprint so events group predictably — e.g. `["runaway-loop", tool_name, run_id]`. The demo should show one clean issue per runaway, not a noisy pile.

- **SR-6 · Idempotency.** Fire **once** per finding. Track fired `finding_id`s (a Redis SET `sentry:fired:{run_id}` fits the stack) so live mode (SR-7), which sees a loop grow across reads, doesn't re-fire on every increment.

- **SR-7 · Live-mode firing (upside).** In live mode, fire the moment a loop crosses `R_max` — *while the agent is still running* — so the demo can say "we caught it mid-run and killed it" rather than diagnosing a corpse. Batch firing (after diagnosis) is the must-have; live is the flourish.

- **SR-8 · Ack the fired state.** After firing, make the state observable to the UI — set `finding.alert_fired = true` (so `/findings` reflects it) or write `alerts:{run_id}` for the UI to read. This is what powers UR-12.

- **SR-9 · Demo-safe fallback.** If `SENTRY_DSN` is unset or the Sentry API is unreachable, a **mock dispatcher** records the event locally (list/file) and still sets the fired state, so the UI shows "alert fired" even with no network. Mirrors the DIY-cache and static-JSON fallbacks elsewhere — the demo never depends on a live external call.

## 6. Reference event (build to this)

For the runaway in the Band reference scenario (`fact_checker`, `verify_source` ×12):

```python
with sentry_sdk.push_scope() as scope:
    scope.set_tag("run_id", "run-001")
    scope.set_tag("agent", "fact_checker")
    scope.set_tag("tool", "verify_source")
    scope.set_tag("finding_type", "repetition")
    scope.set_tag("severity", "runaway")
    scope.set_context("redundant_finding", {
        "finding_id": "f_31",
        "count": 12,
        "dollar_cost": 0.30,
        "convergence": "none",
        "span_ids": ["s_40", "s_41", "...", "s_51"],
    })
    scope.fingerprint = ["runaway-loop", "verify_source", "run-001"]
    scope.level = "error"
    sentry_sdk.capture_message(
        "Runaway agent loop: fact_checker retried verify_source 12× — "
        "$0.30 burned, no convergence"
    )
```

## 7. Demo-beat mapping

| Beat (DESIGN §9 storyboard) | Sentry requirement |
|---|---|
| Click deep-red bar → "12× loop, this is an incident, not caching" | SR-2, SR-3 |
| Sentry alert fires on screen (open the Sentry issue) | SR-3, SR-5 |
| UI shows "alert fired" | SR-8 |
| (live flourish) "caught mid-run" | SR-7 |
| (stretch) side-effecting write refused cache → alert instead | SR-4 |

## 8. Non-functional requirements

- **SR-10 · No spam.** Idempotency + fingerprinting keep the demo Sentry project to a small, legible set of issues.
- **SR-11 · Non-blocking.** Firing MUST NOT block detection or the API response; failures degrade to mock mode (SR-9), never stall the pipeline.
- **SR-12 · Fast & legible.** The fired issue should be openable on the Sentry dashboard during the demo with a clear, screenshot-worthy title.

## 9. Acceptance criteria (definition of done)

- [ ] SDK initializes from `SENTRY_DSN`; missing DSN falls back to mock, no crash — SR-1, SR-9.
- [ ] A `route=="alert"` finding produces a Sentry event with message, level, tags, and context — SR-2, SR-3.
- [ ] Runaway vs side-effecting alerts are visibly distinct — SR-4.
- [ ] Events group via explicit fingerprint; one clean issue per runaway — SR-5.
- [ ] No double-firing across live-mode reads — SR-6.
- [ ] Fired state is observable to the UI (`alert_fired` / `alerts:{run_id}`) — SR-8.
- [ ] (Upside) live mode fires mid-run when the loop crosses `R_max` — SR-7.
- [ ] Pipeline never blocks or crashes on a Sentry failure — SR-11.

## 10. Tech stack

| Concern | Choice |
|---|---|
| SDK | `sentry-sdk` (Python) |
| Dedup store | Redis SET `sentry:fired:{run_id}` |
| Interface to core | in-process `dispatch_alert(finding)` (default) or Redis `alerts:{run_id}` stream |
| Fallback | local mock dispatcher (records events, sets fired state) |

## 11. Open questions / TBD

- In-process call vs Redis-channel handoff from the core router (§4) — confirm with core owner.
- Exact ack mechanism for the UI (`/findings` flag vs `alerts:{run_id}` key) — confirm with core + UI owners.
- `level` policy: is any runaway `fatal`, or only above a cost/count ceiling?
- Do we demo against a **real** Sentry project (best visual) or rely on mock mode (safest)? Ideally real, with mock armed as fallback.
- Side-effecting-redundancy alert (SR-4) depends on the Band stretch goal BR-14 existing — coordinate so the demo can show it.
