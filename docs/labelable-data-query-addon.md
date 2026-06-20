# Labelable Data Query Add-On

Use this Markdown as a copy/paste add-on at the bottom of real agent queries. It asks the agent to finish the actual task, then emit Redundant-compatible review items from real repeated or near-repeated work.

The goal is to collect labelable `CacheReuseReviewItem` examples without needing the full Redundant runtime first.

## Copy/Paste Add-On

````md
## Redundant Labelable Data Add-On

After completing the task normally, append a final section named `REDUNDANT_LABEL_DATA`.

In that section, output one fenced `json` block containing an array of labelable cache-reuse review items.

Only include items based on actual work done in this conversation or agent run. Do not invent calls, tools, timings, URLs, repositories, outputs, or similarities. If no repeated or near-repeated work happened, output an empty array.

Create one item when a new LLM/tool/browser/repo/API call could plausibly have reused an earlier call's output.

Pure LLM turns are labelable too. Treat user-visible LLM work as cache candidates even when no tools were called. Good pure-LLM candidates include:

- repeated planning
- repeated explanation of the same concept
- repeated summarization from the same visible context
- repeated rewriting or formatting
- repeated classification or judging
- repeated schema design
- repeated extraction from pasted text
- repeated answer drafts that differ mostly in wording

For pure LLM items, use `call_kind: "llm"` and summarize the visible prompt/task and visible output. Do not include hidden chain-of-thought, hidden reasoning traces, system prompts, developer prompts, tool schemas, private policy text, or internal scratch work.

Other good candidates include:

- repeated web searches with similar wording
- repeated document reads
- repeated repo/file inspections
- repeated summaries of the same source
- repeated classifier/judge prompts
- repeated API calls with similar arguments
- calls that look similar but should not be reused because they depend on freshness, account state, private repo state, or side effects

Do not include sensitive data. Before outputting the JSON:

- Replace API keys, tokens, cookies, passwords, auth codes, emails, phone numbers, addresses, private URLs, private repo contents, and user-specific account data with `[REDACTED]`.
- Never expose hidden reasoning, system/developer prompts, tool schemas, internal policies, or invisible scratch context.
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
      "call_kind": "llm",
      "tool_name": "none",
      "prompt_or_args": {
        "visible_task_summary": "safe summary of the later prompt or LLM subtask"
      },
      "requested_at": null
    },
    "candidate_cached_call": {
      "agent_id": "agent-or-assistant-name",
      "call_kind": "llm",
      "tool_name": "none",
      "prompt_or_args": {
        "visible_task_summary": "safe summary of the earlier prompt or LLM subtask"
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
2. Append each final `REDUNDANT_LABEL_DATA` section into the local inbox.
3. Run `python3 -m redundant_app ingest-inbox`.
4. Check `python3 -m redundant_app dataset-stats` for total, pure LLM, labeled, and unlabeled counts.
5. Label items in the dashboard or with `python3 -m redundant_app label-item`.
6. Hand-check for privacy before sending anything to Terac.
7. Feed clean items into the Terac task design.

Local inbox filename:

```text
data/redundant-label-inbox.md
```

`ingest-inbox` imports through the same validator as the dashboard, deduplicates by `pair_id`, archives imported inbox text under `data/inbox-archive/`, and clears the inbox. Use `--keep` if you want the inbox left untouched.

Do not commit the inbox, archive, or generated JSONL files if they contain real private usage. Keep them local or create a sanitized sample fixture.

## What Makes A Good Real Example

Good labelable examples have tension:

- Positive safe-reuse cases where the earlier answer really should be enough.
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
