"""RunReport aggregation from the run's event stream.

Reads the emitted RedundantEvents back and rolls them up into the report shape
the UI/Devpost screenshot consumes. Clusters are grouped by cluster_id (set by
the runtime per normalized hash / semantic group).
"""

from __future__ import annotations

from collections import defaultdict

from redundant.schema import (
    Decision,
    NON_EXECUTED_DECISIONS,
    RedundantEvent,
    RunReport,
    DuplicateCluster,
    SuggestedFix,
)

# Static, demo-friendly fix catalogue (matches docs Fix suggestions section).
DEFAULT_FIXES = [
    SuggestedFix(
        fix_id="cache-tool",
        title="Cache pure tools",
        description="Wrap repeated pure tool calls so identical inputs reuse results.",
        sponsor_hook="Redis",
        code_hint='@redundant.cached_tool(ttl="1h")',
    ),
    SuggestedFix(
        fix_id="stable-prefix",
        title="Stabilize prompt prefix",
        description="Move timestamps/IDs out of the stable prompt prefix to hit the exact cache.",
        sponsor_hook="OpenAI",
        code_hint="# keep volatile fields in metadata, not the prompt",
    ),
    SuggestedFix(
        fix_id="compress-context",
        title="Compress bloated context",
        description="Compress large unsafe-to-reuse prompts before executing.",
        sponsor_hook="Token Company",
        code_hint="redundant uses Compressor on COMPRESS_AND_EXECUTE",
    ),
    SuggestedFix(
        fix_id="embed-lookup",
        title="Replace repeated classifier with embedding lookup",
        description="Swap a repeated LLM classification for a vector lookup.",
        sponsor_hook="Redis",
        code_hint="redundant.tool(... cacheability='pure')",
    ),
]


def build_report(run_id: str, events: list[RedundantEvent]) -> RunReport:
    attempted = len(events)
    executed = sum(1 for e in events if e.decision == Decision.EXECUTE
                   or e.decision == Decision.COMPRESS_AND_EXECUTE)
    reused_or_blocked = sum(1 for e in events if e.decision in NON_EXECUTED_DECISIONS)

    saved_cost = round(sum(e.saved_cost_usd for e in events), 6)
    saved_latency = sum(e.saved_latency_ms for e in events)
    saved_tokens = sum(e.saved_tokens for e in events)

    # Actual cost = what we really spent (executed/compressed calls).
    # Baseline = what it would have cost with no reuse = actual + avoided (saved).
    actual_cost = round(sum(e.actual_cost_usd for e in events), 6)
    estimated_baseline = round(actual_cost + saved_cost, 6)

    redundant_rate = round(reused_or_blocked / attempted, 4) if attempted else 0.0

    clusters = _clusters(events)
    worst = max(clusters, key=lambda c: c.saved_cost_usd).label if clusters else None

    return RunReport(
        run_id=run_id,
        attempted_calls=attempted,
        executed_calls=executed,
        reused_or_blocked_calls=reused_or_blocked,
        redundant_rate=redundant_rate,
        estimated_baseline_cost_usd=estimated_baseline,
        actual_cost_usd=actual_cost,
        saved_cost_usd=saved_cost,
        saved_latency_ms=saved_latency,
        saved_tokens=saved_tokens,
        worst_duplicate_cluster=worst,
        clusters=clusters,
        fixes=DEFAULT_FIXES,
    )


def _clusters(events: list[RedundantEvent]) -> list[DuplicateCluster]:
    groups: dict[str, list[RedundantEvent]] = defaultdict(list)
    for e in events:
        if e.cluster_id:
            groups[e.cluster_id].append(e)
    clusters: list[DuplicateCluster] = []
    for cid, evs in groups.items():
        if len(evs) < 2:
            continue  # not a duplicate cluster
        saved_cost = round(sum(e.saved_cost_usd for e in evs), 6)
        saved_latency = sum(e.saved_latency_ms for e in evs)
        agent_ids = sorted({e.agent_id for e in evs})
        label = evs[0].tool_name
        calls = len(evs)
        waste = round((calls - 1) / calls * 100, 1) if calls else 0.0
        clusters.append(
            DuplicateCluster(
                cluster_id=cid,
                label=label,
                calls=calls,
                unique_needed=1,
                waste_percent=waste,
                saved_cost_usd=saved_cost,
                saved_latency_ms=saved_latency,
                agent_ids=agent_ids,
            )
        )
    clusters.sort(key=lambda c: c.saved_cost_usd, reverse=True)
    return clusters
