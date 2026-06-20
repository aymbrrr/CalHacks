# Terac Task Design for Redundant

## Objective

Use Terac to answer one product question:

```text
When Redis finds a semantically similar cached agent call, is it safe for Redundant to reuse the cached output?
```

The Terac task should produce human labels that make Redundant's semantic cache less reckless. The point is not to ask annotators whether two strings are similar. Redis already does that. The point is to ask whether reuse would be safe in an agent runtime.

## Product Flow

1. Redundant records every expensive LLM or tool call.
2. Redis finds exact or semantic cache candidates for new calls.
3. Redundant creates a `CacheReuseReviewItem` for ambiguous semantic candidates.
4. Terac annotators label whether the cached result is safe to reuse.
5. Redundant turns the labels into verifier examples, threshold tuning, and demo metrics.
6. The UI shows the before/after:
   - raw Redis semantic match
   - human-trained verifier decision
   - unsafe reuse blocked
   - savings retained

## Annotator Job

Annotators are reviewing pairs of agent calls. They should answer:

```text
Could an AI agent safely reuse the cached output for the new call?
```

They are not judging whether the cached output is beautifully written. They are judging whether reuse would preserve correctness and avoid unsafe side effects.

## Batch Plan

Pilot batch:

- 12 items
- 2 annotators per item
- Purpose: catch confusing instructions and validate label distribution
- Launch only after the seed examples render correctly in the annotation UI

Main batch:

- 48 more items
- 2-3 annotators per item depending on available credit and turnaround
- Purpose: enough labels for an eval table and a few-shot verifier prompt

Fallback batch:

- 12 hand-labeled seed items
- Used if Terac submissions arrive late
- Same schema as Terac results so the product path does not fork

## Item Selection

Build items from a scripted Redundant run where agents intentionally repeat work.

For real-use collection before the runtime is ready, use the [labelable data query add-on](labelable-data-query-addon.md).

Include five buckets:

- `safe_reuse`: same task, same public information, no side effect.
- `not_equivalent`: similar words, different actual question.
- `needs_freshness_check`: reuse may be okay only if data is still fresh.
- `state_specific`: answer depends on account, repo, user, branch, or other private state.
- `side_effect_risk`: call creates or changes something and should not be replayed/reused.

Recommended mix for the first 60 items:

| Label Bucket | Count | Why |
| --- | ---: | --- |
| `safe_reuse` | 24 | Proves savings are real, not just blocked everything. |
| `not_equivalent` | 12 | Catches semantic false positives. |
| `needs_freshness_check` | 10 | Supports TTL policy. |
| `state_specific` | 8 | Protects personalized/private context. |
| `side_effect_risk` | 6 | Shows agent safety awareness. |

Use synthetic or public examples only. Do not send private repo contents, personal account data, credentials, API keys, emails, calendar contents, or user-specific logs to Terac.

## Review Item Schema

```ts
type CallKind = "llm" | "tool" | "browser" | "repo" | "api";

type CacheReuseReviewItem = {
  pair_id: string;
  trace_id: string;
  created_at: string;
  task_context: string;
  new_call: {
    agent_id: string;
    call_kind: CallKind;
    tool_name?: string;
    prompt_or_args: unknown;
    requested_at: string;
  };
  candidate_cached_call: {
    agent_id: string;
    call_kind: CallKind;
    tool_name?: string;
    prompt_or_args: unknown;
    output_summary: string;
    cached_at: string;
  };
  runtime_signals: {
    redis_similarity: number;
    exact_key_match: boolean;
    cache_age_seconds: number;
    tool_has_side_effects: boolean;
    contains_user_state: boolean;
    proposed_ttl_seconds?: number;
  };
};
```

## Annotator Answer Schema

```ts
type TeracReuseLabel =
  | "safe_reuse"
  | "not_equivalent"
  | "needs_freshness_check"
  | "state_specific"
  | "side_effect_risk";

type TeracReuseAnswer = {
  pair_id: string;
  label: TeracReuseLabel;
  confidence: 1 | 2 | 3 | 4 | 5;
  short_reason: string;
};
```

## Annotator Instructions

Show this instruction block above every item:

```text
You are helping evaluate an AI agent cache.

A new agent call is about to run. Redundant found a cached call that looks semantically similar. Decide whether the agent can safely reuse the cached output instead of running the new call.

Choose exactly one label:

safe_reuse:
The cached output directly answers the new call, does not depend on private state, does not need very fresh data, and has no side effects.

not_equivalent:
The calls look related but ask for materially different information.

needs_freshness_check:
The cached output may be useful, but the answer depends on current pricing, availability, news, time, or another freshness-sensitive fact.

state_specific:
The answer depends on a specific user, account, repository, branch, inbox, calendar, file, or private state.

side_effect_risk:
The call creates or changes something, such as sending a message, creating an issue, writing to a database, booking something, or making a purchase.

If two labels seem possible, choose the more cautious label.
```

## Example Review Item

```json
{
  "pair_id": "demo_001",
  "trace_id": "trace_calhacks_demo_01",
  "created_at": "2026-06-20T21:00:00Z",
  "task_context": "Two agents are researching sponsor tools for an AI cost optimization demo.",
  "new_call": {
    "agent_id": "report-agent",
    "call_kind": "tool",
    "tool_name": "search_docs",
    "prompt_or_args": {
      "query": "Redis semantic cache pricing and use cases"
    },
    "requested_at": "2026-06-20T21:05:12Z"
  },
  "candidate_cached_call": {
    "agent_id": "research-agent",
    "call_kind": "tool",
    "tool_name": "search_docs",
    "prompt_or_args": {
      "query": "Redis LangCache pricing and examples"
    },
    "output_summary": "Redis LangCache supports semantic caching for LLM apps and is part of Redis AI tooling.",
    "cached_at": "2026-06-20T21:04:50Z"
  },
  "runtime_signals": {
    "redis_similarity": 0.91,
    "exact_key_match": false,
    "cache_age_seconds": 22,
    "tool_has_side_effects": false,
    "contains_user_state": false,
    "proposed_ttl_seconds": 3600
  }
}
```

Expected answer:

```json
{
  "pair_id": "demo_001",
  "label": "safe_reuse",
  "confidence": 4,
  "short_reason": "Both calls ask for Redis semantic caching information and the cached result addresses the new query."
}
```

## Aggregation Logic

Use this rule before feeding labels into the verifier:

1. If both annotators agree, accept the label.
2. If labels disagree but both are blocking labels, accept the more specific blocking label.
3. If one label is `safe_reuse` and the other is blocking, mark the item `needs_review`.
4. If confidence average is below 3, mark the item `needs_review`.
5. Hand-review `needs_review` items before using them in the final eval.

Blocking labels:

- `not_equivalent`
- `needs_freshness_check`
- `state_specific`
- `side_effect_risk`

Derived runtime policy:

| Human Label | Runtime Policy |
| --- | --- |
| `safe_reuse` | Allow reuse when verifier confidence is high. |
| `not_equivalent` | Block reuse. |
| `needs_freshness_check` | Allow only with short TTL or live refresh. |
| `state_specific` | Block unless state fingerprint exactly matches. |
| `side_effect_risk` | Never reuse as a completed action. |

## Verifier Prompt Shape

The minimum viable verifier can be an LLM judge using labeled examples:

```text
You are Redundant's cache safety verifier.

Given a new agent call, a candidate cached call, and runtime signals, decide whether cached reuse is safe.

Return:
- decision: allow_reuse | block_reuse | allow_with_freshness_check
- label: safe_reuse | not_equivalent | needs_freshness_check | state_specific | side_effect_risk
- confidence: 0.0 to 1.0
- reason: one sentence

Prefer blocking when the candidate depends on private state, current facts, or side effects.
```

Use 6-10 Terac-labeled examples as few-shot examples. Evaluate against the remaining labels.

## Redis Streams Events

Emit these events so the UI and demo can show the Terac path without waiting on live annotations:

```text
redundant.calls
redundant.cache_candidates
redundant.terac.review_requested
redundant.terac.label_received
redundant.verifier.decided
```

Example `redundant.terac.label_received` event:

```json
{
  "pair_id": "demo_001",
  "label": "safe_reuse",
  "confidence": 4,
  "short_reason": "Both calls ask for Redis semantic caching information.",
  "source": "terac",
  "received_at": "2026-06-20T21:12:00Z"
}
```

## Demo Evaluation

Run the same cached-candidate set through two policies:

Raw Redis policy:

- Reuse every candidate above similarity threshold.
- Count unsafe reuses using held-out human labels.

Terac-gated policy:

- Reuse only if Redis finds a candidate and verifier allows it.
- Count unsafe reuses using the same held-out labels.

Demo table:

| Policy | Reused Calls | Unsafe Reuses | Savings Retained |
| --- | ---: | ---: | ---: |
| Raw Redis similarity | 18 | 4 | 100% |
| Terac-gated verifier | 15 | 0 | 83% |

Narrative:

```text
Redis found the savings. Terac taught Redundant which savings were safe to keep.
```

## Single-Owner Scope

This Terac workstream should have one owner. That person is responsible for turning human labels into a working verifier/evaluation story without depending on the rest of the team to build Terac-specific pieces.

Terac owner responsibilities:

- Own the seed dataset and label taxonomy.
- Own the annotation instructions and Terac task shape.
- Own the import/export format for `CacheReuseReviewItem` and `TeracReuseAnswer`.
- Own the hand-labeled fallback dataset.
- Own the aggregation logic for multiple annotator responses.
- Own the verifier prompt or lightweight classifier.
- Own the before/after eval table.
- Own the demo examples that show unsafe semantic reuse being blocked.

Interfaces with the other workstreams:

- Backend provides ambiguous Redis cache candidates in the `CacheReuseReviewItem` shape.
- UI reads label and verifier status from Redis Streams events.
- Agents/demo provides traces that intentionally create repeated calls.

The Terac owner should not wait on perfect backend/UI support. They can use JSON fixtures first, then swap in live Redis/Streams data once the contracts are available.

## Launch Readiness Checklist

- Seed dataset has at least 12 examples.
- No private data is included in review items.
- Annotation UI shows all fields without leaking raw credentials or account data.
- Pilot batch instructions are understandable without sponsor context.
- Results can be imported without changing the backend contract.
- Demo can run from hand-labeled fallback data.
