from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .scripted_tools import TOOL_REGISTRY
from .trace_writer import TraceWriter, input_hash


LLM_MODEL = "gpt-4o-mini-demo"
TOOL_MODEL = "scripted-tool-v1"


CALL_COSTS = {
    "llm": 0.15,
    "search_docs": 0.12,
    "scan_repo": 0.16,
    "summarize_page": 0.09,
    "compare_tools": 0.07,
    "verify_source": 0.03,
}


CALL_LATENCIES_MS = {
    "llm": 900,
    "search_docs": 720,
    "scan_repo": 840,
    "summarize_page": 560,
    "compare_tools": 480,
    "verify_source": 240,
}


@dataclass
class WrappedResult:
    output: str
    decision: str
    span_id: str
    source_call_id: str | None = None
    source_agent_name: str | None = None
    cluster_id: str | None = None


@dataclass
class CacheRecord:
    span_id: str
    agent_name: str
    output: str
    cost_usd: float
    latency_ms: int
    tokens: dict[str, int]
    input_value: str


class RedundantRuntime:
    def __init__(self, *, run_id: str, mode: str, writer: TraceWriter) -> None:
        self.run_id = run_id
        self.mode = mode
        self.writer = writer
        self._cache: dict[tuple[str, str], CacheRecord] = {}
        self._call_counts: dict[tuple[str, str], int] = {}
        self._loop_alerted: set[tuple[str, str]] = set()
        self._semantic_sources: dict[tuple[str, str], tuple[str, str, str]] = {}

    def llm(self, payload: dict[str, Any]) -> WrappedResult:
        self._require_payload(payload, {"runId", "agentId", "messages", "model", "metadata"})
        parent_span_id = payload["metadata"]["parent_span_id"]
        purpose = payload["metadata"].get("purpose", "llm")
        agent_name = payload["agentId"]
        output = self._script_llm_response(purpose)
        cost = CALL_COSTS["llm"]
        latency = CALL_LATENCIES_MS["llm"]
        span = self.writer.record_call_span(
            kind="llm",
            name=f"llm:{purpose}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=payload["messages"],
            output_value=output,
            tool_name=None,
            model=payload.get("model") or LLM_MODEL,
            decision="EXECUTE",
            cacheability="state_bound",
            cost_usd=cost,
            baseline_cost_usd=cost,
            latency_ms=latency,
            metadata={"purpose": purpose, "room_id": self.writer.room_id},
        )
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="llm",
            tool_name=None,
            decision="EXECUTE",
            cacheability="state_bound",
            summary=f"{agent_name} generated {purpose.replace('_', ' ')}.",
            explanation="LLM calls are recorded through redundant.llm for attribution.",
            sponsor_hooks=["Band", "OpenAI", "Redis Streams"],
        )
        return WrappedResult(output=output, decision="EXECUTE", span_id=span["span_id"])

    def tool(self, payload: dict[str, Any]) -> WrappedResult:
        self._require_payload(payload, {"runId", "agentId", "toolName", "args", "cacheability", "metadata"})
        if payload["runId"] != self.run_id:
            raise ValueError(f"payload runId {payload['runId']} does not match runtime {self.run_id}")

        agent_name = payload["agentId"]
        tool_name = payload["toolName"]
        args = payload["args"]
        cacheability = payload["cacheability"]
        parent_span_id = payload["metadata"]["parent_span_id"]
        input_value = self._canonical_tool_input(tool_name, args)
        key = (tool_name, input_hash(input_value))
        cluster_id = self._cluster_id(tool_name, input_value)
        cost = CALL_COSTS[tool_name]
        latency = CALL_LATENCIES_MS[tool_name]

        if self.mode == "redundant" and cacheability == "pure" and key in self._cache:
            return self._record_exact_reuse(
                agent_name=agent_name,
                tool_name=tool_name,
                input_value=input_value,
                parent_span_id=parent_span_id,
                cacheability=cacheability,
                source=self._cache[key],
                cluster_id=cluster_id,
            )

        semantic_result = self._maybe_semantic_reuse(
            agent_name=agent_name,
            tool_name=tool_name,
            input_value=input_value,
            parent_span_id=parent_span_id,
            cacheability=cacheability,
            cluster_id=cluster_id,
        )
        if semantic_result is not None:
            return semantic_result

        unsafe_result = self._maybe_unsafe_semantic_block(
            agent_name=agent_name,
            tool_name=tool_name,
            input_value=input_value,
            parent_span_id=parent_span_id,
            cacheability=cacheability,
            args=args,
            cluster_id=cluster_id,
        )
        if unsafe_result is not None:
            return unsafe_result

        output = self._execute_tool(tool_name, args, input_value)
        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value=output,
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision="EXECUTE",
            cacheability=cacheability,
            cost_usd=cost,
            baseline_cost_usd=cost,
            latency_ms=latency,
            metadata={"args": args, "room_id": self.writer.room_id},
            cluster_id=cluster_id,
        )
        self._remember_executed_call(tool_name, input_value, cacheability, span)
        self._record_execute_event(agent_name, tool_name, span, cacheability)
        self._maybe_record_runaway_alert(agent_name, tool_name, input_value, cacheability, span)
        return WrappedResult(output=output, decision="EXECUTE", span_id=span["span_id"], cluster_id=cluster_id)

    def build_report(self) -> dict[str, Any]:
        call_spans = [span for span in self.writer.spans if span["kind"] in {"llm", "tool"}]
        baseline_cost = round(sum(span["baseline_cost_usd"] for span in call_spans), 4)
        actual_cost = round(sum(span["cost_usd"] for span in call_spans), 4)
        saved_cost = round(max(0.0, baseline_cost - actual_cost), 4)
        saved_latency = sum(
            event["saved_latency_ms"]
            for event in self.writer.events
            if event["decision"] in {"EXACT_REUSE", "SEMANTIC_REUSE"}
        )
        saved_tokens = sum(
            event["saved_tokens"]
            for event in self.writer.events
            if event["decision"] in {"EXACT_REUSE", "SEMANTIC_REUSE"}
        )
        reused_or_blocked = sum(
            1
            for span in call_spans
            if span["decision"] in {"EXACT_REUSE", "SEMANTIC_REUSE", "UNSAFE_SEMANTIC_BLOCK"}
        )
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "attempted_calls": len(call_spans),
            "executed_calls": sum(1 for span in call_spans if span["cost_usd"] > 0),
            "reused_or_blocked_calls": reused_or_blocked,
            "redundant_rate": round(reused_or_blocked / len(call_spans), 4) if call_spans else 0.0,
            "estimated_baseline_cost_usd": baseline_cost,
            "actual_cost_usd": actual_cost,
            "saved_cost_usd": saved_cost,
            "saved_latency_ms": saved_latency,
            "saved_tokens": saved_tokens,
            "waste_rate": round(saved_cost / baseline_cost, 4) if baseline_cost else 0.0,
            "visible_line": "ReportAgent reused ResearchAgent's prior result.",
            "summary": f"${saved_cost:.2f} wasted of ${baseline_cost:.2f} total in the baseline path.",
        }

    def build_duplicate_clusters(self) -> list[dict[str, Any]]:
        spans_by_cluster: dict[str, list[dict[str, Any]]] = {}
        for span in self.writer.spans:
            if span["kind"] != "tool" or not span.get("cluster_id"):
                continue
            spans_by_cluster.setdefault(span["cluster_id"], []).append(span)

        clusters: list[dict[str, Any]] = []
        for cluster_id, spans in spans_by_cluster.items():
            if len(spans) < 2 and cluster_id != "cluster_loop_verify_source":
                continue
            decisions = sorted({span["decision"] for span in spans})
            cluster_type = "exact" if len({span["input_hash"] for span in spans}) == 1 else "semantic"
            if cluster_id == "cluster_unsafe_search_docs":
                cluster_type = "unsafe_semantic_block"
            if cluster_id == "cluster_loop_verify_source":
                cluster_type = "runaway_loop"
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "type": cluster_type,
                    "tool_name": spans[0]["tool_name"],
                    "input_hashes": sorted({span["input_hash"] for span in spans}),
                    "agents": sorted({span["agent_name"] for span in spans}),
                    "decisions": decisions,
                    "call_ids": [span["span_id"] for span in spans],
                }
            )
        return clusters

    def _record_exact_reuse(
        self,
        *,
        agent_name: str,
        tool_name: str,
        input_value: str,
        parent_span_id: str,
        cacheability: str,
        source: CacheRecord,
        cluster_id: str,
    ) -> WrappedResult:
        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value=source.output,
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision="EXACT_REUSE",
            cacheability=cacheability,
            cost_usd=0.0,
            baseline_cost_usd=source.cost_usd,
            latency_ms=35,
            metadata={"reused_from_agent": source.agent_name, "room_id": self.writer.room_id},
            source_call_id=source.span_id,
            cluster_id=cluster_id,
        )
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="EXACT_REUSE",
            cacheability=cacheability,
            summary=f"{agent_name} reused {source.agent_name}'s prior {tool_name} result.",
            explanation="Same tool name and normalized input hash were already present in this run.",
            saved_cost_usd=source.cost_usd,
            saved_latency_ms=source.latency_ms,
            saved_tokens=source.tokens["input"] + source.tokens["output"],
            source_call_id=source.span_id,
            cluster_id=cluster_id,
            sponsor_hooks=["Band", "Redis", "Redis Streams"],
        )
        return WrappedResult(
            output=source.output,
            decision="EXACT_REUSE",
            span_id=span["span_id"],
            source_call_id=source.span_id,
            source_agent_name=source.agent_name,
            cluster_id=cluster_id,
        )

    def _maybe_semantic_reuse(
        self,
        *,
        agent_name: str,
        tool_name: str,
        input_value: str,
        parent_span_id: str,
        cacheability: str,
        cluster_id: str,
    ) -> WrappedResult | None:
        if self.mode != "redundant" or tool_name != "scan_repo" or input_value != "tool cache decorator":
            return None
        source_key = ("scan_repo", input_hash("cached tool wrapper"))
        source = self._cache.get(source_key)
        if source is None:
            return None
        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value=source.output,
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision="SEMANTIC_REUSE",
            cacheability=cacheability,
            cost_usd=0.0,
            baseline_cost_usd=source.cost_usd,
            latency_ms=90,
            metadata={
                "semantic_candidate": "cached tool wrapper",
                "verifier_score": 0.92,
                "room_id": self.writer.room_id,
            },
            source_call_id=source.span_id,
            cluster_id="cluster_semantic_scan_repo",
        )
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="SEMANTIC_REUSE",
            cacheability=cacheability,
            summary="ReportAgent reused a semantically equivalent repo scan.",
            explanation="Redis vector match found the prior ResearchAgent scan and the verifier accepted it.",
            saved_cost_usd=source.cost_usd,
            saved_latency_ms=source.latency_ms,
            saved_tokens=source.tokens["input"] + source.tokens["output"],
            source_call_id=source.span_id,
            verifier_score=0.92,
            cluster_id="cluster_semantic_scan_repo",
            sponsor_hooks=["Band", "Redis", "Redis Streams", "Terac"],
        )
        return WrappedResult(
            output=source.output,
            decision="SEMANTIC_REUSE",
            span_id=span["span_id"],
            source_call_id=source.span_id,
            source_agent_name=source.agent_name,
            cluster_id="cluster_semantic_scan_repo",
        )

    def _maybe_unsafe_semantic_block(
        self,
        *,
        agent_name: str,
        tool_name: str,
        input_value: str,
        parent_span_id: str,
        cacheability: str,
        args: dict[str, Any],
        cluster_id: str,
    ) -> WrappedResult | None:
        if self.mode != "redundant":
            return None
        if tool_name != "search_docs" or input_value != "Sentry alert routing strategies for runaway agents":
            return None
        source_key = ("search_docs", input_hash("Redis cache invalidation strategies for agent tool calls"))
        source = self._cache.get(source_key)
        if source is None:
            return None

        output = self._execute_tool(tool_name, args, input_value)
        cost = CALL_COSTS[tool_name]
        latency = CALL_LATENCIES_MS[tool_name]
        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value=output,
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision="UNSAFE_SEMANTIC_BLOCK",
            cacheability=cacheability,
            cost_usd=cost,
            baseline_cost_usd=cost,
            latency_ms=latency,
            metadata={
                "blocked_source_call_id": source.span_id,
                "blocked_source_agent": source.agent_name,
                "verifier_score": 0.21,
                "room_id": self.writer.room_id,
            },
            source_call_id=source.span_id,
            cluster_id="cluster_unsafe_search_docs",
        )
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="UNSAFE_SEMANTIC_BLOCK",
            cacheability=cacheability,
            summary="Semantic candidate was blocked by the verifier.",
            explanation=(
                "The Redis cache-invalidation result looked similar, but Terac-style verification rejected "
                "reuse for Sentry alert-routing strategy."
            ),
            source_call_id=source.span_id,
            verifier_score=0.21,
            cluster_id="cluster_unsafe_search_docs",
            sponsor_hooks=["Band", "Redis", "Redis Streams", "Terac"],
        )
        self._remember_executed_call(tool_name, input_value, cacheability, span)
        return WrappedResult(
            output=output,
            decision="UNSAFE_SEMANTIC_BLOCK",
            span_id=span["span_id"],
            source_call_id=source.span_id,
            source_agent_name=source.agent_name,
            cluster_id="cluster_unsafe_search_docs",
        )

    def _record_execute_event(
        self,
        agent_name: str,
        tool_name: str,
        span: dict[str, Any],
        cacheability: str,
    ) -> None:
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="EXECUTE",
            cacheability=cacheability,
            summary=f"{agent_name} executed {tool_name}.",
            explanation="No safe reusable result was available for this call.",
            cluster_id=span.get("cluster_id"),
            sponsor_hooks=["Band", "Redis Streams"],
        )

    def _maybe_record_runaway_alert(
        self,
        agent_name: str,
        tool_name: str,
        input_value: str,
        cacheability: str,
        span: dict[str, Any],
    ) -> None:
        if tool_name != "verify_source":
            return
        key = (tool_name, input_hash(input_value))
        count = self._call_counts[key]
        if count >= 12 and key not in self._loop_alerted:
            self._loop_alerted.add(key)
            self.writer.add_event(
                agent_id=agent_name,
                call_id=span["span_id"],
                call_type="tool",
                tool_name=tool_name,
                decision="RUNAWAY_LOOP_ALERT",
                cacheability=cacheability,
                summary="VerifierAgent repeated verify_source 12 times without progress.",
                explanation="The repeated input cleared the R_max=10 threshold and routed to the alert path.",
                cluster_id="cluster_loop_verify_source",
                sponsor_hooks=["Band", "Redis Streams", "Sentry"],
            )

    def _remember_executed_call(
        self,
        tool_name: str,
        input_value: str,
        cacheability: str,
        span: dict[str, Any],
    ) -> None:
        key = (tool_name, input_hash(input_value))
        self._call_counts[key] = self._call_counts.get(key, 0) + 1
        if self.mode == "redundant" and cacheability == "pure" and span["decision"] == "EXECUTE":
            self._cache[key] = CacheRecord(
                span_id=span["span_id"],
                agent_name=span["agent_name"],
                output=span["output"],
                cost_usd=span["cost_usd"],
                latency_ms=span["latency_ms"],
                tokens=span["tokens"],
                input_value=input_value,
            )

    def _execute_tool(self, tool_name: str, args: dict[str, Any], input_value: str) -> str:
        if tool_name not in TOOL_REGISTRY:
            raise ValueError(f"Unknown scripted tool: {tool_name}")
        if tool_name == "compare_tools":
            return TOOL_REGISTRY[tool_name](args["tool_a"], args["tool_b"])
        if tool_name == "verify_source":
            key = (tool_name, input_hash(input_value))
            attempt = self._call_counts.get(key, 0) + 1
            return TOOL_REGISTRY[tool_name](args["source_or_claim"], attempt)
        arg_name = {
            "search_docs": "query",
            "scan_repo": "topic",
            "summarize_page": "url_or_text",
        }[tool_name]
        return TOOL_REGISTRY[tool_name](args[arg_name])

    def _canonical_tool_input(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "compare_tools":
            return json.dumps(args, sort_keys=True, separators=(",", ":"))
        arg_name = {
            "search_docs": "query",
            "scan_repo": "topic",
            "summarize_page": "url_or_text",
            "verify_source": "source_or_claim",
        }[tool_name]
        return str(args[arg_name])

    def _cluster_id(self, tool_name: str, input_value: str) -> str | None:
        if tool_name == "search_docs" and input_value == "agent cost optimization redis sentry":
            return "cluster_exact_search_docs"
        if tool_name == "summarize_page":
            return "cluster_exact_summary"
        if tool_name == "scan_repo" and input_value in {"cached tool wrapper", "tool cache decorator"}:
            return "cluster_semantic_scan_repo"
        if tool_name == "search_docs" and input_value in {
            "Redis cache invalidation strategies for agent tool calls",
            "Sentry alert routing strategies for runaway agents",
        }:
            return "cluster_unsafe_search_docs"
        if tool_name == "verify_source":
            return "cluster_loop_verify_source"
        return None

    def _script_llm_response(self, purpose: str) -> str:
        responses = {
            "research_plan": (
                "Plan: search the shared cost-optimization query, scan wrapper code patterns, summarize the "
                "canonical source, then post reusable findings for the other agents."
            ),
            "research_findings": (
                "Findings: Redis should handle exact cache keys and streams; semantic reuse needs verifier "
                "gating; Sentry is strongest for runaway-loop visibility."
            ),
            "report_overlap_request": (
                "I need to verify the shared search result, check an equivalent cache-wrapper repo topic, "
                "and compare Redis with Sentry before writing the recommendation."
            ),
            "audit_note": (
                "Audit note: I will intentionally repeat the canonical search query to prove the exact "
                "cross-agent duplicate cluster includes three agents."
            ),
            "final_recommendation": (
                "Recommendation: use Redis for exact and semantic reuse metadata plus Redis Streams for the "
                "live feed, gate semantic matches with verifier labels, and route runaway loops to Sentry."
            ),
        }
        return responses.get(purpose, f"Scripted LLM response for {purpose}.")

    def _require_payload(self, payload: dict[str, Any], required: set[str]) -> None:
        missing = required - set(payload)
        if missing:
            raise ValueError(f"wrapper payload missing fields: {sorted(missing)}")
