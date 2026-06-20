from __future__ import annotations

import itertools
import uuid
from pathlib import Path
from typing import Any

from .runtime import RedundantRuntime, stable_hash
from .storage import JsonlStore


DEFAULT_TASK = "Research agent cost optimization tools, compare Redis and Sentry-style approaches, and produce a short recommendation."


def run_demo(task: str = DEFAULT_TASK, mode: str = "redundant", store: JsonlStore | None = None) -> dict[str, Any]:
    store = store or JsonlStore()
    run_id = f"run-{stable_hash({'task': task, 'mode': mode})}-{uuid.uuid4().hex[:8]}"
    run = store.start_run(task=task, mode=mode, run_id=run_id)
    runtime = RedundantRuntime(store=store, run=run, dataset_check_every=3)

    runtime.band_publish("research-agent", "Starting sponsor research and sharing notes through the Band room.")
    runtime.llm(
        "research-agent",
        "Plan research for a multi-agent cost firewall using Redis Streams, Terac labels, Sentry warnings, and Band coordination.",
        lambda _: "Plan: collect sponsor docs, find repeated agent calls, measure duplicate cost, and prepare reuse recommendations.",
    )
    runtime.band_publish("report-agent", "I will use the shared research notes and avoid repeating expensive work where possible.")
    runtime.llm(
        "report-agent",
        "Plan a report for a multi-agent cost firewall using Redis Streams, Terac labels, Sentry warnings, and Band coordination.",
        lambda _: "Report plan: summarize runtime, cache, verifier, warnings, and demo metrics.",
    )

    runtime.tool(
        "research-agent",
        "search_docs",
        {"query": "Redis semantic cache pricing and use cases"},
        search_docs,
    )
    runtime.tool(
        "report-agent",
        "search_docs",
        {"query": "Redis LangCache pricing and examples"},
        search_docs,
    )
    runtime.llm(
        "research-agent",
        "Summarize Redis semantic caching for an AI agent cost firewall in three bullets.",
        lambda _: "Redis can store normalized calls, support vector similarity, and publish runtime decisions through Streams.",
    )
    runtime.llm(
        "report-agent",
        "Summarize Redis LangCache and semantic caching for an AI cost firewall in three bullets.",
        lambda _: "Redis LangCache-style semantic caching avoids repeated model/tool spend while preserving latency.",
    )

    runtime.tool(
        "research-agent",
        "scan_repo",
        {"topic": "public redundant demo cache wrapper contract"},
        scan_repo,
    )
    runtime.tool(
        "report-agent",
        "scan_repo",
        {"topic": "public redundant demo cache wrapper contract"},
        scan_repo,
    )
    runtime.tool(
        "research-agent",
        "query_repo",
        {"query": "private repo failing tests on branch codex/redundant-plan"},
        scan_repo,
    )
    runtime.tool(
        "report-agent",
        "query_repo",
        {"query": "private repo failing tests on branch main"},
        scan_repo,
    )

    long_context = " ".join(
        [
            "Classify repeated agent calls for safe reuse, freshness risk, state-bound behavior, and side-effect risk."
            for _ in range(18)
        ]
    )
    runtime.llm(
        "verifier-agent",
        long_context,
        lambda _: "Verifier rubric: allow pure reuse, refresh current facts, require state fingerprints, and block side effects.",
    )
    runtime.llm(
        "verifier-agent",
        long_context.replace("safe reuse", "cache reuse"),
        lambda _: "Verifier rubric variant: allow stable pure calls and block side effects.",
    )

    runtime.tool(
        "report-agent",
        "create_sentry_issue",
        {"title": "Agent repeated expensive call", "action": "create issue in demo project"},
        create_sentry_issue,
    )
    runtime.tool(
        "research-agent",
        "create_sentry_issue",
        {"title": "Agent repeated expensive call", "action": "create issue in demo project"},
        create_sentry_issue,
    )
    runtime.llm(
        "report-agent",
        "Write the final recommendation for Redundant using the shared Band room notes and verifier results.",
        lambda _: "Recommendation: ship Redundant with Redis cache/Streams, Terac verifier data, Sentry warnings, and Band-visible collaboration.",
    )

    return runtime.finish()


def search_docs(args: dict[str, Any]) -> str:
    query = args.get("query", "")
    if "redis" in query.lower() or "langcache" in query.lower():
        return "Redis supports exact and semantic caching patterns for AI apps, plus Streams for live event feeds."
    return f"Search result summary for {query}."


def scan_repo(args: dict[str, Any]) -> str:
    topic = args.get("topic") or args.get("query")
    return f"Repo scan summary for {topic}: wrappers, endpoints, and tests should share one stable contract."


def create_sentry_issue(args: dict[str, Any]) -> str:
    return f"Sentry issue would be created for: {args.get('title', 'untitled')}"


def export_sample(store: JsonlStore, destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    items = store.list_label_items(limit=12)
    with destination.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(__import__("json").dumps(item, sort_keys=True) + "\n")
    return destination


def unique_run_id(prefix: str = "run") -> str:
    counter = next(unique_run_id.counter)
    return f"{prefix}-{counter:03d}"


unique_run_id.counter = itertools.count(1)
