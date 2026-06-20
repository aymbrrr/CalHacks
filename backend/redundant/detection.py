"""Detection engine: repetition, cycle, and cost attribution.

§7.2 + §7.3 of DESIGN_redis.md.
"""
from __future__ import annotations
import uuid
from collections import defaultdict

import networkx as nx

from redundant.span_schema import Evidence, Finding, Span, TokenCost

# ---------------------------------------------------------------------------
# Price table (USD per 1M tokens) — §7.3
# ---------------------------------------------------------------------------
_PRICE: dict[str, tuple[float, float]] = {
    "gpt-4o":       (5.0, 15.0),
    "gpt-4o-mini":  (0.15, 0.6),
    "claude-opus-4-8":  (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (0.80, 4.0),
}
_DEFAULT_PRICE = (3.0, 15.0)

R_MAX = 10  # repetition count that tips "runaway"

# Read-only tool allowlist for cacheability gate
READ_ONLY_TOOLS = {"web_search", "search_docs", "scan_repo", "summarize_page",
                   "fetch_data", "compare_tools", "llm"}


def _span_cost(span: Span) -> float:
    price = _PRICE.get(span.model or "", _DEFAULT_PRICE)
    return round(
        span.tokens.input / 1_000_000 * price[0]
        + span.tokens.output / 1_000_000 * price[1],
        6,
    )


def _sum_tokens(spans: list[Span]) -> TokenCost:
    return TokenCost(
        input=sum(s.tokens.input for s in spans),
        output=sum(s.tokens.output for s in spans),
    )


# ---------------------------------------------------------------------------
# A. Repetition detector
# ---------------------------------------------------------------------------

def detect_repetition(spans: list[Span]) -> list[Finding]:
    """Group tool spans by (tool_name, input_hash); group size ≥ 2 → Finding."""
    groups: dict[tuple[str, str], list[Span]] = defaultdict(list)
    for s in spans:
        if s.kind == "tool" and s.tool_name:
            groups[(s.tool_name, s.input_hash)].append(s)

    findings: list[Finding] = []
    for (tool_name, _hash), group in groups.items():
        if len(group) < 2:
            continue
        agents = {s.agent_name for s in group}
        cross = len(agents) > 1
        unit_cost = _span_cost(group[0])
        wasted_cost = unit_cost * (len(group) - 1)
        desc = (
            f"{tool_name} called {len(group)}x with identical args"
            + (f" across {len(agents)} agents: {', '.join(sorted(agents))}" if cross else "")
        )
        findings.append(Finding(
            finding_id=f"f_{uuid.uuid4().hex[:6]}",
            type="repetition",
            span_ids=[s.span_id for s in group],
            representative_span_id=group[0].span_id,
            count=len(group),
            description=desc,
            token_cost=_sum_tokens(group[1:]),  # wasted = all but first
            dollar_cost=round(wasted_cost, 6),
            severity="runaway" if len(group) >= R_MAX else "wasteful",
            route="alert" if len(group) >= R_MAX else "cache",
            cacheable=(tool_name in READ_ONLY_TOOLS),
            evidence=Evidence(convergence="converged" if len(set(s.output for s in group)) == 1 else "none"),
        ))
    return findings


# ---------------------------------------------------------------------------
# B. Cycle detector
# ---------------------------------------------------------------------------

def detect_cycles(spans: list[Span]) -> list[Finding]:
    """Build directed call graph from parent-child edges; find simple cycles."""
    G = nx.DiGraph()
    span_map = {s.span_id: s for s in spans}
    for s in spans:
        G.add_node(s.span_id, span=s)
    for s in spans:
        if s.parent_span_id and s.parent_span_id in span_map:
            G.add_edge(s.parent_span_id, s.span_id)

    findings: list[Finding] = []
    seen: set[frozenset] = set()
    for cycle in nx.simple_cycles(G):
        key = frozenset(cycle)
        if key in seen or len(cycle) < 2:
            continue
        seen.add(key)
        cycle_spans = [span_map[n] for n in cycle if n in span_map]
        cost = sum(_span_cost(s) for s in cycle_spans) * (len(cycle) - 1)
        findings.append(Finding(
            finding_id=f"f_{uuid.uuid4().hex[:6]}",
            type="cycle",
            span_ids=cycle,
            representative_span_id=cycle[0],
            count=len(cycle),
            description=f"Execution cycle detected: {' -> '.join(cycle)} -> {cycle[0]}",
            token_cost=_sum_tokens(cycle_spans),
            dollar_cost=round(cost, 6),
            severity="runaway",
            route="alert",
            cacheable=False,
            evidence=Evidence(cycle_path=cycle + [cycle[0]], convergence="none"),
        ))
    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(spans: list[Span]) -> dict:
    """Run all detectors and return findings + cost rollup."""
    findings: list[Finding] = []
    findings.extend(detect_repetition(spans))
    findings.extend(detect_cycles(spans))

    total_cost = sum(_span_cost(s) for s in spans)
    wasted_cost = sum(f.dollar_cost for f in findings)
    return {
        "findings": findings,
        "total_cost_usd": round(total_cost, 6),
        "wasted_cost_usd": round(wasted_cost, 6),
        "waste_pct": round(wasted_cost / total_cost * 100, 1) if total_cost else 0,
    }
