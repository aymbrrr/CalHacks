from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .scripted_tools import TOOL_REGISTRY
from .trace_writer import TraceWriter, input_hash


# Real model name used for LLM calls; can be overridden via REDUNDANT_DEFAULT_MODEL.
LLM_MODEL = os.getenv("REDUNDANT_DEFAULT_MODEL", "gpt-4o-mini")
TOOL_MODEL = "tool:scripted"

# How many identical calls in a row trigger a loop block in the local shim
# (mirrors backend/redundant/config.py loop_threshold).
_SHIM_LOOP_THRESHOLD = 3

# Try to import the real Redundant runtime once at module level.
try:
    from redundant.runtime import Redundant as _RealRedundant
    from redundant.config import SETTINGS as _SETTINGS
    from redundant.schema import (
        Run as _BackendRun,
    )
    _REAL_BACKEND_AVAILABLE = True
except ImportError:
    _RealRedundant = None  # type: ignore[assignment,misc]
    _SETTINGS = None  # type: ignore[assignment]
    _REAL_BACKEND_AVAILABLE = False


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


def _log_integrations() -> None:
    """Log which integrations are active without printing secret values."""
    if not _REAL_BACKEND_AVAILABLE or _SETTINGS is None:
        print("[redundant_runtime] Redundant backend not importable — using local shim")
        return
    redis_url = _SETTINGS.redis_url
    if "@" in redis_url:
        prefix = redis_url.split("://")[0]
        host_port = redis_url.split("@")[-1]
        masked_redis = f"{prefix}://***@{host_port}"
    else:
        masked_redis = redis_url
    has_openai = bool(_SETTINGS.openai_api_key)
    print(
        f"[redundant_runtime] Config — "
        f"Redis: {masked_redis} | "
        f"OpenAI: {'yes' if has_openai else 'no (local fallback)'}"
    )


class RedundantRuntime:
    def __init__(self, *, run_id: str, mode: str, writer: TraceWriter, store: Any = None) -> None:
        self.run_id = run_id
        self.mode = mode
        self.writer = writer
        # Local shim state (used only when real backend is unavailable).
        self._cache: dict[tuple[str, str], CacheRecord] = {}
        self._call_counts: dict[tuple[str, str], int] = {}
        # Maps (tool_name, canonical_input) → agent_name for EXACT_REUSE attribution.
        self._source_agents: dict[tuple[str, str], str] = {}

        _log_integrations()

        # Try to wire up the real Redundant runtime for live Redis events.
        # If `store` is provided (from the backend API thread), pass it through so
        # _RealRedundant emits to the same store the API's SSE endpoint reads from.
        self._real: Any | None = None
        if _REAL_BACKEND_AVAILABLE:
            try:
                self._real = _RealRedundant(run_id=run_id, store=store)
                run_obj = _BackendRun(
                    run_id=run_id,
                    task="Band multi-agent demo",
                    mode=mode,
                    status="running",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                self._real.store.save_run(run_obj)
                print(f"[redundant_runtime] Real Redundant backend active — run_id={run_id!r}")
                print(f"[redundant_runtime] Live stream: GET /api/runs/{run_id}/stream")
                print(f"[redundant_runtime] Events:      GET /api/runs/{run_id}/events")
                print(f"[redundant_runtime] Report:      GET /api/runs/{run_id}/report")
            except Exception as exc:
                print(f"[redundant_runtime] Real backend unavailable, using local shim: {exc}")
                self._real = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def llm(self, payload: dict[str, Any]) -> WrappedResult:
        self._require_payload(payload, {"runId", "agentId", "messages", "model", "metadata"})
        agent_name = payload["agentId"]
        messages = payload["messages"]
        model = payload.get("model") or LLM_MODEL
        parent_span_id = payload["metadata"]["parent_span_id"]
        purpose = payload["metadata"].get("purpose", "llm")

        # Route through real backend — real Anthropic call + Redis Streams event.
        if self._real is not None:
            try:
                event = self._real.llm(agent_name, messages, model=model)
                output = event._output or ""
                decision_str = event.decision.value
                cost = event.actual_cost_usd
                latency = CALL_LATENCIES_MS["llm"] if decision_str == "EXECUTE" else event.saved_latency_ms
                span = self.writer.record_call_span(
                    kind="llm",
                    name=f"llm:{purpose}",
                    agent_name=agent_name,
                    parent_span_id=parent_span_id,
                    input_value=messages,
                    output_value=output,
                    tool_name=None,
                    model=model,
                    decision=decision_str,
                    cacheability="state_bound",
                    cost_usd=cost,
                    baseline_cost_usd=CALL_COSTS["llm"],
                    latency_ms=latency or CALL_LATENCIES_MS["llm"],
                    metadata={"purpose": purpose, "room_id": self.writer.room_id},
                )
                self.writer.add_event(
                    agent_id=agent_name,
                    call_id=span["span_id"],
                    call_type="llm",
                    tool_name=None,
                    decision=decision_str,
                    cacheability="state_bound",
                    summary=event.summary or f"{agent_name} generated {purpose.replace('_', ' ')}.",
                    explanation=event.explanation or "LLM via real Redundant runtime with Anthropic.",
                    saved_cost_usd=event.saved_cost_usd,
                    saved_latency_ms=event.saved_latency_ms,
                    saved_tokens=event.saved_tokens,
                    source_call_id=event.source_call_id,
                    sponsor_hooks=["Band", "Anthropic", "Redis Streams"],
                )
                return WrappedResult(output=output, decision=decision_str, span_id=span["span_id"])
            except Exception as exc:
                print(f"[redundant_runtime] Real runtime llm error: {exc!r}, falling back to direct OpenAI")

        # Shim path: direct OpenAI call (no Redundant backend available).
        output = self._call_anthropic_direct(messages, model)
        cost = CALL_COSTS["llm"]
        latency = CALL_LATENCIES_MS["llm"]
        span = self.writer.record_call_span(
            kind="llm",
            name=f"llm:{purpose}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=messages,
            output_value=output,
            tool_name=None,
            model=model,
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
            explanation="LLM call via direct Anthropic (Redundant backend unavailable).",
            sponsor_hooks=["Band", "Anthropic"],
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
        canon_key = (tool_name, input_value)

        # Route through real backend — normalize→exact→embed+KNN→decide→execute→persist→emit.
        if self._real is not None:
            try:
                event = self._real.tool(agent_name, tool_name, args, cacheability=cacheability)
                return self._record_backend_tool_event(
                    event=event,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    input_value=input_value,
                    canon_key=canon_key,
                    parent_span_id=parent_span_id,
                    cacheability=cacheability,
                    args=args,
                )
            except Exception as exc:
                print(f"[redundant_runtime] Real runtime tool error ({tool_name}): {exc!r}, falling back to shim")

        # Shim path (no real backend).
        return self._shim_tool(
            agent_name=agent_name,
            tool_name=tool_name,
            args=args,
            input_value=input_value,
            canon_key=canon_key,
            parent_span_id=parent_span_id,
            cacheability=cacheability,
        )

    def finalize(self) -> None:
        """Mark the run complete in the real backend store so the SSE stream closes."""
        if self._real is not None:
            try:
                run_obj = self._real.store.get_run(self.run_id)
                if run_obj is not None:
                    run_obj.status = "complete"
                    run_obj.completed_at = datetime.now(timezone.utc).isoformat()
                    self._real.store.save_run(run_obj)
            except Exception:
                pass

    def build_report(self) -> dict[str, Any]:
        self.finalize()
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
            if span["decision"] in {"EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN"}
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
            if len(spans) < 2:
                continue
            decisions = sorted({span["decision"] for span in spans})
            unique_hashes = {span["input_hash"] for span in spans}
            cluster_type = "exact" if len(unique_hashes) == 1 else "semantic"
            if any(d == "BLOCK_OR_WARN" for d in decisions):
                explanations = " ".join(
                    e.get("explanation", "")
                    for e in self.writer.events
                    if e.get("cluster_id") == cluster_id
                )
                if "RUNAWAY_LOOP_DETECTED" in explanations:
                    cluster_type = "runaway_loop"
                elif "UNSAFE_SEMANTIC_REUSE_REJECTED" in explanations:
                    cluster_type = "unsafe_semantic_block"
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "type": cluster_type,
                    "tool_name": spans[0]["tool_name"],
                    "input_hashes": sorted(unique_hashes),
                    "agents": sorted({span["agent_name"] for span in spans}),
                    "decisions": decisions,
                    "call_ids": [span["span_id"] for span in spans],
                }
            )
        return clusters

    # -------------------------------------------------------------------------
    # Private: real backend event recording
    # -------------------------------------------------------------------------

    def _record_backend_tool_event(
        self,
        *,
        event: Any,
        agent_name: str,
        tool_name: str,
        input_value: str,
        canon_key: tuple[str, str],
        parent_span_id: str,
        cacheability: str,
        args: dict[str, Any],
    ) -> WrappedResult:
        decision_str: str = event.decision.value
        output: str = event._output or ""
        cost = CALL_COSTS.get(tool_name, 0.05)
        latency = CALL_LATENCIES_MS.get(tool_name, 500)
        is_reuse = decision_str in ("EXACT_REUSE", "SEMANTIC_REUSE")
        cluster_id = event.cluster_id

        # Track source agent for EXACT_REUSE attribution.
        if decision_str == "EXECUTE":
            self._source_agents[canon_key] = agent_name
        source_agent = self._source_agents.get(canon_key) if decision_str == "EXACT_REUSE" else None
        if source_agent == agent_name:
            source_agent = None

        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value=output,
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision=decision_str,
            cacheability=cacheability,
            cost_usd=0.0 if is_reuse else event.actual_cost_usd,
            baseline_cost_usd=cost,
            latency_ms=35 if is_reuse else latency,
            metadata={"args": args, "room_id": self.writer.room_id},
            source_call_id=event.source_call_id,
            cluster_id=cluster_id,
        )
        explanation = event.explanation or f"Via real Redundant runtime. Decision: {decision_str}."
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision=decision_str,
            cacheability=cacheability,
            summary=event.summary or f"{agent_name} {decision_str} {tool_name}.",
            explanation=explanation,
            saved_cost_usd=event.saved_cost_usd,
            saved_latency_ms=event.saved_latency_ms,
            saved_tokens=event.saved_tokens,
            source_call_id=event.source_call_id,
            verifier_score=event.verifier_score,
            cluster_id=cluster_id,
            sponsor_hooks=["Band", "Redis", "Redis Streams"],
        )
        return WrappedResult(
            output=output,
            decision=decision_str,
            span_id=span["span_id"],
            source_call_id=event.source_call_id,
            source_agent_name=source_agent,
            cluster_id=cluster_id,
        )

    # -------------------------------------------------------------------------
    # Private: local shim path (no real backend)
    # -------------------------------------------------------------------------

    def _shim_tool(
        self,
        *,
        agent_name: str,
        tool_name: str,
        args: dict[str, Any],
        input_value: str,
        canon_key: tuple[str, str],
        parent_span_id: str,
        cacheability: str,
    ) -> WrappedResult:
        key = (tool_name, input_hash(input_value))
        cost = CALL_COSTS.get(tool_name, 0.05)
        latency = CALL_LATENCIES_MS.get(tool_name, 500)
        cluster_id = f"cl:{tool_name}:{input_hash(input_value)}"

        # Count this attempt (before deciding, to match the backend's loop_count semantics).
        self._call_counts[key] = self._call_counts.get(key, 0) + 1
        count = self._call_counts[key]

        # 1. Loop detection — same hash hammered repeatedly.
        if self.mode == "redundant" and count >= _SHIM_LOOP_THRESHOLD:
            return self._shim_block(
                agent_name=agent_name,
                tool_name=tool_name,
                input_value=input_value,
                parent_span_id=parent_span_id,
                cacheability=cacheability,
                cluster_id=cluster_id,
                reason=f"RUNAWAY_LOOP_DETECTED: identical call attempted {count}x (threshold={_SHIM_LOOP_THRESHOLD}).",
                source_call_id=self._cache.get(key, CacheRecord("", "", "", 0.0, 0, {}, "")).span_id or None,
            )

        # 2. Exact reuse (pure calls only).
        if self.mode == "redundant" and cacheability == "pure" and key in self._cache:
            source = self._cache[key]
            source_agent = self._source_agents.get(canon_key)
            if source_agent == agent_name:
                source_agent = None
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
                explanation="Same tool name and normalized input hash already present in this run (shim exact cache).",
                saved_cost_usd=source.cost_usd,
                saved_latency_ms=source.latency_ms,
                saved_tokens=source.tokens.get("input", 0) + source.tokens.get("output", 0),
                source_call_id=source.span_id,
                cluster_id=cluster_id,
                sponsor_hooks=["Band", "Redis Streams"],
            )
            return WrappedResult(
                output=source.output,
                decision="EXACT_REUSE",
                span_id=span["span_id"],
                source_call_id=source.span_id,
                source_agent_name=source_agent,
                cluster_id=cluster_id,
            )

        # 3. Semantic reuse: not available in shim (no embeddings/vector search).
        if self.mode == "redundant":
            print(
                f"[redundant_runtime] Shim: skipping semantic reuse for {tool_name!r} — "
                "no OpenAI embeddings or Redis vector search available; returning EXECUTE."
            )

        # 4. Execute.
        output = self._execute_scripted_tool(tool_name, args, input_value)
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
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="EXECUTE",
            cacheability=cacheability,
            summary=f"{agent_name} executed {tool_name}.",
            explanation="No safe reusable result available (shim path, no vector search).",
            cluster_id=cluster_id,
            sponsor_hooks=["Band", "Redis Streams"],
        )
        self._remember_executed_call(tool_name, input_value, cacheability, canon_key, agent_name, span)
        return WrappedResult(output=output, decision="EXECUTE", span_id=span["span_id"], cluster_id=cluster_id)

    def _shim_block(
        self,
        *,
        agent_name: str,
        tool_name: str,
        input_value: str,
        parent_span_id: str,
        cacheability: str,
        cluster_id: str,
        reason: str,
        source_call_id: str | None,
    ) -> WrappedResult:
        cost = CALL_COSTS.get(tool_name, 0.05)
        latency = CALL_LATENCIES_MS.get(tool_name, 500)
        span = self.writer.record_call_span(
            kind="tool",
            name=f"tool:{tool_name}",
            agent_name=agent_name,
            parent_span_id=parent_span_id,
            input_value=input_value,
            output_value="[blocked]",
            tool_name=tool_name,
            model=TOOL_MODEL,
            decision="BLOCK_OR_WARN",
            cacheability=cacheability,
            cost_usd=0.0,
            baseline_cost_usd=cost,
            latency_ms=35,
            metadata={"reason": reason, "room_id": self.writer.room_id},
            source_call_id=source_call_id,
            cluster_id=cluster_id,
        )
        self.writer.add_event(
            agent_id=agent_name,
            call_id=span["span_id"],
            call_type="tool",
            tool_name=tool_name,
            decision="BLOCK_OR_WARN",
            cacheability=cacheability,
            summary=f"{agent_name} blocked {tool_name}: {reason.split(':')[0]}.",
            explanation=reason,
            saved_cost_usd=cost,
            saved_latency_ms=latency,
            source_call_id=source_call_id,
            cluster_id=cluster_id,
            sponsor_hooks=["Band", "Redis Streams", "Sentry"],
        )
        return WrappedResult(
            output="[blocked]",
            decision="BLOCK_OR_WARN",
            span_id=span["span_id"],
            source_call_id=source_call_id,
            cluster_id=cluster_id,
        )

    # -------------------------------------------------------------------------
    # Private: utilities
    # -------------------------------------------------------------------------

    def _call_anthropic_direct(self, messages: list[dict[str, Any]], model: str) -> str:
        """Direct OpenAI call used when the real Redundant backend is unavailable."""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("[redundant_runtime] OPENAI_API_KEY not set; returning placeholder LLM response")
            return "[LLM response unavailable: OPENAI_API_KEY not configured]"
        # Always use OpenAI regardless of what model name was requested
        oai_model = "gpt-4o-mini"
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(model=oai_model, max_tokens=512, messages=messages)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            print(f"[redundant_runtime] Direct OpenAI call failed: {exc!r}")
            return f"[LLM error: {exc}]"

    def _execute_scripted_tool(self, tool_name: str, args: dict[str, Any], input_value: str) -> str:
        spec = TOOL_REGISTRY.get(tool_name)
        if spec is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        fn = spec.fn if hasattr(spec, "fn") else spec
        if tool_name == "compare_tools":
            return fn(args.get("tool_a", ""), args.get("tool_b", ""))
        if tool_name == "verify_source":
            key = (tool_name, input_hash(input_value))
            attempt = self._call_counts.get(key, 1)
            try:
                return fn(args.get("source_or_claim", ""), attempt)
            except TypeError:
                return fn(source_or_claim=args.get("source_or_claim", ""))
        arg_map = {
            "search_docs": "query",
            "scan_repo": "topic",
            "summarize_page": "url_or_text",
        }
        if tool_name in arg_map:
            return fn(args.get(arg_map[tool_name], ""))
        return fn(**(args or {}))

    def _remember_executed_call(
        self,
        tool_name: str,
        input_value: str,
        cacheability: str,
        canon_key: tuple[str, str],
        agent_name: str,
        span: dict[str, Any],
    ) -> None:
        key = (tool_name, input_hash(input_value))
        self._source_agents[canon_key] = agent_name
        if self.mode == "redundant" and cacheability == "pure" and span["decision"] == "EXECUTE":
            self._cache[key] = CacheRecord(
                span_id=span["span_id"],
                agent_name=agent_name,
                output=span["output"],
                cost_usd=span["cost_usd"],
                latency_ms=span["latency_ms"],
                tokens=span["tokens"],
                input_value=input_value,
            )

    def _canonical_tool_input(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "compare_tools":
            return json.dumps(args, sort_keys=True, separators=(",", ":"))
        arg_name = {
            "search_docs": "query",
            "scan_repo": "topic",
            "summarize_page": "url_or_text",
            "verify_source": "source_or_claim",
        }.get(tool_name)
        if arg_name and arg_name in args:
            return str(args[arg_name])
        return json.dumps(args, sort_keys=True, separators=(",", ":"))

    def _require_payload(self, payload: dict[str, Any], required: set[str]) -> None:
        missing = required - set(payload)
        if missing:
            raise ValueError(f"wrapper payload missing fields: {sorted(missing)}")
