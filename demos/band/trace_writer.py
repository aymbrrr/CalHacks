from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


BASE_TIME = datetime(2026, 6, 20, 19, 0, 0, tzinfo=timezone.utc)
BASE_TIME_MS = int(BASE_TIME.timestamp() * 1000)


REQUIRED_SPAN_FIELDS = {
    "span_id",
    "parent_span_id",
    "kind",
    "name",
    "tool_name",
    "agent_name",
    "input",
    "output",
    "input_hash",
    "start_time",
    "end_time",
    "tokens",
    "model",
}


def normalize_for_hash(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return re.sub(r"\s+", " ", value.lower().strip())


def input_hash(value: Any) -> str:
    return hashlib.sha256(normalize_for_hash(value).encode("utf-8")).hexdigest()[:12]


def estimate_tokens(input_value: Any, output_value: Any) -> dict[str, int]:
    input_text = input_value if isinstance(input_value, str) else json.dumps(input_value, sort_keys=True)
    output_text = output_value if isinstance(output_value, str) else json.dumps(output_value, sort_keys=True)
    return {
        "input": max(12, len(input_text) // 4 + 24),
        "output": max(8, len(output_text) // 4 + 12),
    }


class TraceWriter:
    def __init__(self, run_id: str, mode: str, task: str) -> None:
        self.run_id = run_id
        self.mode = mode
        self.task = task
        self.room_id = f"band-room-{run_id}"
        self.cursor_ms = BASE_TIME_MS
        self._span_counter = 0
        self._event_counter = 0
        self._message_counter = 0
        self.spans: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def iso_at(self, offset_ms: int | None = None) -> str:
        when_ms = self.cursor_ms if offset_ms is None else offset_ms
        when = BASE_TIME + timedelta(milliseconds=when_ms - BASE_TIME_MS)
        return when.isoformat().replace("+00:00", "Z")

    def next_span_id(self) -> str:
        self._span_counter += 1
        return f"s_{self._span_counter:03d}"

    def next_event_id(self) -> str:
        self._event_counter += 1
        return f"e_{self._event_counter:03d}"

    def next_message_id(self) -> str:
        self._message_counter += 1
        return f"m_{self._message_counter:03d}"

    def start_agent_span(self, agent_name: str, parent_span_id: str | None, input_value: str) -> str:
        span_id = self.next_span_id()
        self.spans.append(
            {
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "kind": "agent",
                "name": f"agent:{agent_name}",
                "tool_name": None,
                "agent_name": agent_name,
                "input": input_value,
                "output": "",
                "input_hash": input_hash(input_value),
                "start_time": self.cursor_ms,
                "end_time": self.cursor_ms,
                "tokens": None,
                "model": None,
                "decision": None,
                "cacheability": None,
                "cost_usd": 0.0,
                "baseline_cost_usd": 0.0,
                "latency_ms": 0,
                "metadata": {"room_id": self.room_id},
            }
        )
        self.cursor_ms += 35
        return span_id

    def finish_agent_span(self, span_id: str, output: str) -> None:
        span = self.find_span(span_id)
        span["output"] = output
        span["end_time"] = max(self.cursor_ms, span["start_time"] + 25)
        span["latency_ms"] = span["end_time"] - span["start_time"]
        self.cursor_ms += 20

    def record_call_span(
        self,
        *,
        kind: str,
        name: str,
        agent_name: str,
        parent_span_id: str,
        input_value: Any,
        output_value: str,
        tool_name: str | None,
        model: str,
        decision: str,
        cacheability: str,
        cost_usd: float,
        baseline_cost_usd: float,
        latency_ms: int,
        metadata: dict[str, Any] | None = None,
        source_call_id: str | None = None,
        cluster_id: str | None = None,
    ) -> dict[str, Any]:
        self.cursor_ms += 45
        start_time = self.cursor_ms
        end_time = start_time + latency_ms
        self.cursor_ms = end_time
        call_input = input_value if isinstance(input_value, str) else json.dumps(input_value, sort_keys=True)
        span = {
            "span_id": self.next_span_id(),
            "parent_span_id": parent_span_id,
            "kind": kind,
            "name": name,
            "tool_name": tool_name,
            "agent_name": agent_name,
            "input": call_input,
            "output": output_value,
            "input_hash": input_hash(call_input),
            "start_time": start_time,
            "end_time": end_time,
            "tokens": estimate_tokens(call_input, output_value),
            "model": model,
            "decision": decision,
            "cacheability": cacheability,
            "cost_usd": round(cost_usd, 4),
            "baseline_cost_usd": round(baseline_cost_usd, 4),
            "latency_ms": latency_ms,
            "source_call_id": source_call_id,
            "cluster_id": cluster_id,
            "metadata": metadata or {},
        }
        self.spans.append(span)
        return span

    def add_event(
        self,
        *,
        agent_id: str,
        call_id: str,
        call_type: str,
        tool_name: str | None,
        decision: str,
        cacheability: str,
        summary: str,
        explanation: str,
        saved_cost_usd: float = 0.0,
        saved_latency_ms: int = 0,
        saved_tokens: int = 0,
        source_call_id: str | None = None,
        verifier_score: float | None = None,
        cluster_id: str | None = None,
        sponsor_hooks: list[str] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": self.next_event_id(),
            "run_id": self.run_id,
            "ts": self.iso_at(),
            "agent_id": agent_id,
            "call_id": call_id,
            "call_type": call_type,
            "tool_name": tool_name,
            "decision": decision,
            "cacheability": cacheability,
            "summary": summary,
            "explanation": explanation,
            "saved_cost_usd": round(saved_cost_usd, 4),
            "saved_latency_ms": saved_latency_ms,
            "saved_tokens": saved_tokens,
            "source_call_id": source_call_id,
            "verifier_score": verifier_score,
            "cluster_id": cluster_id,
            "sponsor_hooks": sponsor_hooks or ["Band", "Redis Streams"],
        }
        self.events.append(event)
        return event

    def add_room_message(
        self,
        *,
        speaker: str,
        content: str,
        kind: str = "message",
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        message = {
            "message_id": self.next_message_id(),
            "room_id": self.room_id,
            "run_id": self.run_id,
            "ts": self.iso_at(),
            "speaker": speaker,
            "kind": kind,
            "content": content,
            "references": references or [],
        }
        self.messages.append(message)
        return message

    def find_span(self, span_id: str) -> dict[str, Any]:
        for span in self.spans:
            if span["span_id"] == span_id:
                return span
        raise KeyError(f"Unknown span_id: {span_id}")

    def validate(self) -> list[str]:
        errors: list[str] = []
        for index, span in enumerate(self.spans):
            missing = REQUIRED_SPAN_FIELDS - set(span)
            if missing:
                errors.append(f"span {index} missing fields: {sorted(missing)}")
            if span.get("kind") not in {"agent", "llm", "tool"}:
                errors.append(f"{span.get('span_id')} invalid kind {span.get('kind')}")
            if span.get("kind") != "tool" and span.get("tool_name") is not None:
                errors.append(f"{span.get('span_id')} has tool_name outside tool span")
            if span.get("kind") in {"llm", "tool"}:
                if not span.get("model"):
                    errors.append(f"{span.get('span_id')} missing model")
                tokens = span.get("tokens")
                if not isinstance(tokens, dict) or "input" not in tokens or "output" not in tokens:
                    errors.append(f"{span.get('span_id')} missing token counts")
        return errors

    def build_trace(
        self,
        *,
        agent_prompts: dict[str, str],
        report: dict[str, Any],
        duplicate_clusters: list[dict[str, Any]],
        known_fallback_limitations: list[str],
    ) -> dict[str, Any]:
        completed_at = self.iso_at()
        return {
            "schema_version": "band-demo-trace-v1",
            "run": {
                "run_id": self.run_id,
                "task": self.task,
                "mode": self.mode,
                "status": "complete",
                "room_id": self.room_id,
                "band_adapter": "fallback",
                "started_at": BASE_TIME.isoformat().replace("+00:00", "Z"),
                "completed_at": completed_at,
            },
            "agents": [
                {"agent_name": agent_name, "prompt": prompt}
                for agent_name, prompt in agent_prompts.items()
            ],
            "room_transcript": self.messages,
            "spans": self.spans,
            "events": self.events,
            "duplicate_clusters": duplicate_clusters,
            "report": report,
            "commands": {
                "baseline": f"python demos/band/run_band_demo.py --mode baseline --run-id {self.run_id}",
                "redundant": f"python demos/band/run_band_demo.py --mode redundant --run-id {self.run_id}",
                "replay": f"python demos/band/replay_trace.py demos/band/traces/band_demo_trace.json --run-id {self.run_id}",
            },
            "known_fallback_limitations": known_fallback_limitations,
        }

    def write_trace(self, path: Path, trace: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._push_to_backend(path, trace)

    def _push_to_backend(self, path: Path, trace: dict[str, Any]) -> None:
        # The run is already registered by RedundantRuntime.__init__ via the real
        # backend's store.save_run().  Do NOT call /api/runs/start here — that would
        # create a separate run with a new UUID and lose the Band run_id.
        try:
            from demos.band.redundant_client import ingest_trace_file
        except ImportError:
            return
        result = ingest_trace_file(path)
        if result:
            print(f"[redundant_client] backend ingested trace: {result.get('span_count')} spans, "
                  f"wasted ${result.get('wasted_cost_usd', 0):.2f} / ${result.get('total_cost_usd', 0):.2f}")

