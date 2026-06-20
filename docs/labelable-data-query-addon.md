# Labelable Data Query Add-On

Use this Markdown as a copy/paste add-on at the bottom of real agent queries. It asks the agent to finish the actual task, then emit Redundant-compatible review items from real repeated or near-repeated work.

The goal is to collect labelable `CacheReuseReviewItem` examples without needing the full Redundant runtime first.

## Copy/Paste Add-On

````md
## Redundant Labelable Data Add-On

After completing the task normally, append a final section named `REDUNDANT_LABEL_DATA`.

In that section, output one fenced `json` block containing an array of labelable cache-reuse review items.

Only include items based on actual work done in this conversation or agent run. Do not invent calls, tools, timings, URLs, repositories, outputs, or similarities. If no repeated or near-repeated work happened, output an empty array.

Create one item when a new LLM/tool/browser/repo/API call could plausibly have reused an earlier call's output. Good candidates include:

- repeated web searches with similar wording
- repeated document reads
- repeated repo/file inspections
- repeated summaries of the same source
- repeated classifier/judge prompts
- repeated API calls with similar arguments
- calls that look similar but should not be reused because they depend on freshness, account state, private repo state, or side effects

Do not include sensitive data. Before outputting the JSON:

- Replace API keys, tokens, cookies, passwords, auth codes, emails, phone numbers, addresses, private URLs, private repo contents, and user-specific account data with `[REDACTED]`.
- Summarize large outputs instead of copying them.
- Do not include full private documents, full source files, full logs, or full message threads.
- If a field would require sensitive data, use a safe summary plus `"redaction_applied": true`.

Each item must match this shape:

```ts
type CacheReuseReviewItem = {
  pair_id: string;
  trace_id: string;
  created_at: string;
  task_context: string;
  new_call: {
    agent_id: string;
    call_kind: "llm" | "tool" | "browser" | "repo" | "api";
    tool_name?: string;
    prompt_or_args: unknown;
    requested_at: string | null;
  };
  candidate_cached_call: {
    agent_id: string;
    call_kind: "llm" | "tool" | "browser" | "repo" | "api";
    tool_name?: string;
    prompt_or_args: unknown;
    output_summary: string;
    cached_at: string | null;
  };
  runtime_signals: {
    redis_similarity: number | null;
    exact_key_match: boolean | null;
    cache_age_seconds: number | null;
    tool_has_side_effects: boolean;
    contains_user_state: boolean;
    proposed_ttl_seconds?: number | null;
  };
  label_hint: {
    likely_label:
      | "safe_reuse"
      | "not_equivalent"
      | "needs_freshness_check"
      | "state_specific"
      | "side_effect_risk"
      | "unclear";
    why_labelable: string;
  };
  privacy: {
    redaction_applied: boolean;
    notes: string;
  };
};
```

Use these label hints:

- `safe_reuse`: the earlier output likely answers the new call safely.
- `not_equivalent`: the calls look similar but ask for materially different things.
- `needs_freshness_check`: current pricing, availability, news, time, or other fresh data matters.
- `state_specific`: account, user, repo, branch, inbox, calendar, or private state matters.
- `side_effect_risk`: the call creates or changes something.
- `unclear`: a human should decide.

The final section should look exactly like this:

```json
[
  {
    "pair_id": "real_001",
    "trace_id": "manual_trace_YYYYMMDD_001",
    "created_at": "YYYY-MM-DDTHH:MM:SSZ",
    "task_context": "One-sentence summary of the user's real task.",
    "new_call": {
      "agent_id": "agent-or-assistant-name",
      "call_kind": "tool",
      "tool_name": "name_if_any",
      "prompt_or_args": {
        "query": "safe redacted args for the later call"
      },
      "requested_at": null
    },
    "candidate_cached_call": {
      "agent_id": "agent-or-assistant-name",
      "call_kind": "tool",
      "tool_name": "name_if_any",
      "prompt_or_args": {
        "query": "safe redacted args for the earlier call"
      },
      "output_summary": "Short summary of the earlier output, not the full output.",
      "cached_at": null
    },
    "runtime_signals": {
      "redis_similarity": null,
      "exact_key_match": null,
      "cache_age_seconds": null,
      "tool_has_side_effects": false,
      "contains_user_state": false,
      "proposed_ttl_seconds": 3600
    },
    "label_hint": {
      "likely_label": "unclear",
      "why_labelable": "Explain why this pair would teach Redundant something about reuse safety."
    },
    "privacy": {
      "redaction_applied": false,
      "notes": "No sensitive data included."
    }
  }
]
```
````

## Collection Workflow

1. Paste the add-on under normal real tasks.
2. Save each final `REDUNDANT_LABEL_DATA` JSON array.
3. Convert arrays into one JSONL file, one review item per line.
4. Deduplicate by `pair_id` and near-duplicate `prompt_or_args`.
5. Hand-check for privacy before sending anything to Terac.
6. Feed clean items into the Terac task design.

Suggested local filename:

```text
data/terac-review-items.manual.jsonl
```

Do not commit that data file if it contains real private usage. Keep it local or create a sanitized sample fixture.

## What Makes A Good Real Example

Good labelable examples have tension:

- High semantic similarity but questionable reuse.
- Same source, different question.
- Same question, stale answer risk.
- Same operation, but one is side-effecting.
- Same repo request, but different branch/private state.
- Repeated summary/classification that clearly could have been cached.

Weak examples:

- Totally unrelated calls.
- Exact duplicate safe calls with no interesting decision.
- Calls whose output cannot be summarized without exposing private data.
- Fabricated examples that did not happen in the run.

## Quick Starter Query

Use this when you specifically want to generate a batch from natural work:

```md
Do the task normally. As you work, notice repeated or near-repeated LLM/tool/browser/repo/API calls. At the end, use the Redundant Labelable Data Add-On to emit labelable cache-reuse review items from this real run.
```

## Labeling Path

The add-on produces `label_hint` only. It is not the final human label.

Final labels still come from hand review or Terac:

- `safe_reuse`
- `not_equivalent`
- `needs_freshness_check`
- `state_specific`
- `side_effect_risk`

Treat the hint as triage. The final label is what trains or evaluates the verifier.
