from __future__ import annotations


SAME_SOURCE = "https://redundant.dev/examples/agent-cost-caching"


def search_docs(query: str) -> str:
    responses = {
        "agent cost optimization redis sentry": (
            "Redis is the best fit for exact reuse because stable tool inputs can map to a cache key. "
            "Redis Streams gives the live timeline. Sentry is strongest for alert routing and triage "
            "when agents repeat work or run away."
        ),
        "LangChain agent tracing cost optimization": (
            "LangChain-style tracing helps expose repeated tool calls, but it normally reports waste "
            "after execution. Redundant should prevent safe duplicates before cost is spent."
        ),
        "Sentry performance monitoring agent failures": (
            "Sentry is useful for surfacing runaway agent loops, grouping repeated failures, and "
            "routing alerts to the team that owns the workflow."
        ),
        "Redis cache invalidation strategies for agent tool calls": (
            "For agent tool calls, Redis cache entries should include tool name, normalized input hash, "
            "cacheability class, source span, TTL, and freshness metadata."
        ),
        "Sentry alert routing strategies for runaway agents": (
            "Runaway agent alerts should be grouped by run, agent, tool, and repeated input hash, then "
            "routed by owner with enough trace context to stop the loop."
        ),
    }
    return responses.get(query, f"Scripted documentation result for: {query}")


def scan_repo(topic: str) -> str:
    responses = {
        "cached tool wrapper": (
            "Repository scan: a cached wrapper should canonicalize tool args, look up exact reuse first, "
            "ask the semantic verifier only for near matches, and always emit a span."
        ),
        "tool cache decorator": (
            "Repository scan: a tool cache decorator should canonicalize arguments, check exact hits, "
            "verify semantic matches, and emit reusable trace spans."
        ),
    }
    return responses.get(topic, f"Scripted repository scan for: {topic}")


def summarize_page(url_or_text: str) -> str:
    if url_or_text == SAME_SOURCE:
        return (
            "Summary: Redundant wraps expensive agent calls, records spans, reuses exact duplicates, "
            "verifies semantic reuse, and reports saved cost by source call."
        )
    return f"Summary for {url_or_text}: no live network was used in this deterministic demo."


def compare_tools(tool_a: str, tool_b: str) -> str:
    return (
        f"{tool_a} should own low-latency cache and stream primitives. {tool_b} should own incident "
        "visibility, alert routing, and follow-up workflow for repeated failures."
    )


def verify_source(source_or_claim: str, attempt: int) -> str:
    return (
        f"attempt {attempt}: verifier still cannot converge on source quality for '{source_or_claim}'. "
        "Uncertainty remains unchanged at medium risk."
    )


TOOL_REGISTRY = {
    "search_docs": search_docs,
    "scan_repo": scan_repo,
    "summarize_page": summarize_page,
    "compare_tools": compare_tools,
    "verify_source": verify_source,
}

