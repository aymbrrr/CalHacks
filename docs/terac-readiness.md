# Terac Readiness for Redundant

## What Terac Is For

Use Terac to collect real human labels for Redundant's semantic cache verifier.

Redis can find likely duplicate calls. Terac gives us human labels for whether a cached result is actually safe to reuse.

## Track Fit

Terac's Berkeley challenge is to:

1. Build an annotation environment.
2. Call the Terac API or MCP to bring annotators.
3. Fine-tune or improve a model using the collected labels.
4. Show measurable improvement over the base model.

Judging emphasis:

- Model improvement: 40%
- Annotation environment: 35%
- Use of human data: 25%

Prize notes from the starter pack:

- 1st: $1000 cash + Terac interviews
- 2nd: $500 cash + Terac interviews
- Teams get $250 in Terac credit after signing in and messaging Terac on Slack.

## Account And Access Checklist

These steps require a human because they involve login, OAuth, or messaging a sponsor.

1. Sign in as a Terac researcher:
   - https://terac.com/researchers/login
2. Message Terac in the hackathon Slack to request team credits.
   - Suggested message:

```text
Hi Terac team, we are building Redundant, a multi-agent cost firewall. We want to use Terac to collect labels for whether semantically similar LLM/tool calls are safe to reuse from cache. Could you enable our team's $250 Terac credit and let us know the fastest way to launch this annotation task?
```

3. Choose integration mode:
   - MCP for fastest agent-driven launch.
   - REST API for custom backend integration.

## MCP Setup

MCP URL:

```text
https://terac.com/api/mcp
```

Claude Code setup:

```bash
claude mcp add --transport http terac https://terac.com/api/mcp
```

Then run `/mcp` inside Claude Code and authenticate with OAuth.

ChatGPT connector setup:

1. Settings
2. Apps & Connectors
3. Enable Developer mode
4. Add connector
5. Paste `https://terac.com/api/mcp`

Terac MCP tools advertised by the Terac MCP page:

- `terac_list_opportunities`
- `terac_create_quote`
- `terac_launch_opportunity`
- `terac_get_submissions`
- `terac_get_context`
- `terac_pause_opportunity`

## REST API Setup

Base URL:

```text
https://terac.com/api/external/v2
```

Authentication:

```http
Authorization: Bearer YOUR_API_KEY
```

API keys are generated from organization settings in the Terac dashboard. Rate limit is 100 requests/minute per API key.

Main resources to use:

- Projects: create/list/update project containers.
- Opportunities: create draft opportunities, launch, pause, resume, stop.
- Submissions: list/retrieve/approve/reject submissions.
- Filters: list filters and filter options.

## Redundant Annotation Task

Detailed task design: [Terac task design](terac-task-design.md).

Task name:

```text
Redundant Semantic Cache Safety Labels
```

Goal:

Given a new agent call and a candidate cached call, decide whether Redundant can safely reuse the cached output.

Annotator type:

General-population annotators are fine. We should avoid specialist requirements to keep turnaround fast and conserve credit.

Recommended sample size:

- MVP: 30 labeled pairs
- Better: 60 labeled pairs
- Demo fallback: 12 hand-labeled seed pairs plus Terac submissions as they arrive

## Annotation UI Fields

Each labeling item should show:

```json
{
  "pair_id": "pair_001",
  "run_context": "The agents are researching AI agent cost optimization tools.",
  "new_call": {
    "agent_id": "report-agent",
    "call_type": "tool",
    "tool_name": "search_docs",
    "args": {
      "query": "Redis semantic cache pricing and use cases"
    }
  },
  "candidate_cached_call": {
    "agent_id": "research-agent",
    "call_type": "tool",
    "tool_name": "search_docs",
    "args": {
      "query": "Redis LangCache pricing and examples"
    },
    "output_summary": "Redis LangCache supports semantic caching for LLM apps and is part of Redis' AI tooling."
  },
  "system_recommendation": {
    "similarity": 0.91,
    "proposed_decision": "SEMANTIC_REUSE"
  }
}
```

Required annotator labels:

```ts
type TeracReuseLabel =
  | "safe_reuse"
  | "not_equivalent"
  | "needs_freshness_check"
  | "state_specific"
  | "side_effect_risk"
```

Required annotator answer shape:

```json
{
  "pair_id": "pair_001",
  "label": "safe_reuse",
  "confidence": 4,
  "short_reason": "Both calls ask for current Redis semantic caching/LangCache information and the cached output answers the new query."
}
```

Confidence scale:

- 1: unsure
- 2: weak confidence
- 3: moderate confidence
- 4: strong confidence
- 5: obvious

## Labeling Instructions For Annotators

Use `safe_reuse` when:

- The new call asks for substantially the same thing.
- The cached output directly answers the new call.
- There is no important missing user-specific state.
- The answer does not depend on minute-by-minute freshness.
- The call is not side-effecting.

Use `not_equivalent` when:

- The calls look similar but ask for materially different information.
- The cached output would answer the wrong question.

Use `needs_freshness_check` when:

- The topic may change quickly, such as pricing, news, or current availability.
- Reuse may be safe only with a short TTL or live refresh.

Use `state_specific` when:

- The answer depends on a user, account, private repo, inbox, calendar, or other state fingerprint.

Use `side_effect_risk` when:

- The call creates or changes something.
- Examples: sending email, creating a ticket, writing to a database, making a purchase.

## Seed Dataset

Use these as starter pairs before Terac submissions arrive.

```json
[
  {
    "pair_id": "seed_001",
    "expected_label": "safe_reuse",
    "new_call": "search_docs('Redis semantic cache pricing and use cases')",
    "cached_call": "search_docs('Redis LangCache pricing and examples')"
  },
  {
    "pair_id": "seed_002",
    "expected_label": "not_equivalent",
    "new_call": "search_docs('Sentry API for creating issues')",
    "cached_call": "search_docs('Sentry pricing plans')"
  },
  {
    "pair_id": "seed_003",
    "expected_label": "needs_freshness_check",
    "new_call": "web_search('current Browserbase pricing today')",
    "cached_call": "web_search('Browserbase pricing from last month')"
  },
  {
    "pair_id": "seed_004",
    "expected_label": "state_specific",
    "new_call": "query_repo('private repo failing tests on branch codex/redundant-plan')",
    "cached_call": "query_repo('public main branch failing tests')"
  },
  {
    "pair_id": "seed_005",
    "expected_label": "side_effect_risk",
    "new_call": "create_github_issue('agent repeated expensive call')",
    "cached_call": "create_github_issue('agent repeated expensive call')"
  }
]
```

## How To Use Labels In Redundant

Minimum viable verifier:

1. Redis finds semantic candidates.
2. Rules reject obvious `side_effecting`, stale, or state-bound mismatches.
3. Terac-labeled examples calibrate the verifier prompt or classifier.
4. Redundant allows semantic reuse only when verifier confidence is high.

Demo metric:

```text
Raw Redis similarity:
- 18 semantic hits
- 4 unsafe false positives

Terac-gated verifier:
- 15 semantic hits
- 0 unsafe false positives
- 83% of savings retained
```

## Demo Script

1. Show Redis finding a high-similarity cached call.
2. Show one pair where raw similarity would incorrectly reuse.
3. Show the Terac-trained verifier blocking it.
4. Show the final report:
   - unsafe cache hits before verifier
   - unsafe cache hits after verifier
   - savings retained
   - example human label reasons

## Implementation Notes

- Hold the credit request until the annotation task design is agreed by the team.
- Do not wait for Terac to finish before building the rest of Redundant.
- Build the annotation UI and seed dataset first.
- Feed Terac results into the same `TeracReuseLabel` shape.
- The product must still work with hand-labeled fallback data if submissions arrive late.

## Links

- Terac starter pack: https://glistening-larch-a23.notion.site/Terac-Berkeley-AI-Hackathon-2202f66e615383478a7b01c4b20df8e5
- Terac researcher login: https://terac.com/researchers/login
- Terac MCP: https://terac.com/mcp
- Terac API docs: https://terac.com/docs/developers
- Terac API base URL: `https://terac.com/api/external/v2`
