from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


DECISIONS = {
    "EXECUTE",
    "EXACT_REUSE",
    "SEMANTIC_REUSE",
    "COMPRESS_AND_EXECUTE",
    "BLOCK_OR_WARN",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()[:16]


def redact_text(value: str) -> tuple[str, bool]:
    patterns = [
        r"sk-[A-Za-z0-9_\-]{12,}",
        r"Bearer\s+[A-Za-z0-9._\-]{12,}",
        r"[\w.\-]+@[\w.\-]+\.\w+",
        r"https://[^\s]*(token|key|auth|private)[^\s]*",
    ]
    redacted = value
    changed = False
    for pattern in patterns:
        new = re.sub(pattern, "[REDACTED]", redacted, flags=re.IGNORECASE)
        changed = changed or new != redacted
        redacted = new
    return redacted[:600], changed


def safe_payload(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("token", "secret", "password", "cookie", "api_key")):
                out[key] = "[REDACTED]"
                changed = True
            else:
                out[key], item_changed = safe_payload(item)
                changed = changed or item_changed
        return out, changed
    if isinstance(value, list):
        items = []
        changed = False
        for item in value[:20]:
            safe, item_changed = safe_payload(item)
            items.append(safe)
            changed = changed or item_changed
        return items, changed or len(value) > 20
    return value, False


def words(value: Any) -> list[str]:
    text = stable_json(value).lower()
    return [w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 2]


def embedding(value: Any) -> dict[str, float]:
    counts: dict[str, float] = {}
    for word in words(value):
        stem = word[:-1] if word.endswith("s") and len(word) > 4 else word
        counts[stem] = counts.get(stem, 0.0) + 1.0
    return counts


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(weight * right.get(key, 0.0) for key, weight in left.items())
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return round(dot / (left_norm * right_norm), 4)


def estimate_tokens(value: Any) -> int:
    return max(12, len(words(value)) * 2)


def classify_cacheability(call_kind: str, tool_name: str, prompt_or_args: Any) -> str:
    text = stable_json({"call_kind": call_kind, "tool_name": tool_name, "args": prompt_or_args}).lower()
    if any(word in text for word in ("send ", "create issue", "write ", "purchase", "book ", "delete ", "post message")):
        return "side_effecting"
    if any(word in text for word in ("private", "account", "inbox", "calendar", "branch", "user-specific", "my repo")):
        return "state_bound"
    if any(word in text for word in ("today", "current", "pricing", "availability", "news", "latest")):
        return "freshness_sensitive"
    return "pure"


def likely_label(cacheability: str, similarity: float, exact: bool) -> str:
    if cacheability == "side_effecting":
        return "side_effect_risk"
    if cacheability == "state_bound":
        return "state_specific"
    if cacheability == "freshness_sensitive":
        return "needs_freshness_check"
    if exact or similarity >= 0.82:
        return "safe_reuse"
    if similarity >= 0.62:
        return "unclear"
    return "not_equivalent"


def label_reason(label: str, similarity: float, cacheability: str) -> str:
    if label == "safe_reuse":
        return "The later call appears to ask for the same reusable work as an earlier pure call."
    if label == "needs_freshness_check":
        return "The calls overlap, but current or time-sensitive facts may require a fresh run."
    if label == "state_specific":
        return "The calls overlap, but account, branch, repo, or user state may change the answer."
    if label == "side_effect_risk":
        return "The call may create or change external state, so reuse should be reviewed carefully."
    if label == "not_equivalent":
        return "The calls share vocabulary but appear to ask for materially different work."
    return f"Similarity {similarity:.2f} makes this useful for human cache-safety labeling."


@dataclass
class CacheEntry:
    call_id: str
    run_id: str
    agent_id: str
    call_kind: str
    tool_name: str
    prompt_or_args: Any
    normalized_input: str
    input_hash: str
    output: str
    output_summary: str
    cacheability: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    created_at: str
    vector: dict[str, float] = field(default_factory=dict)


class RedundantRuntime:
    def __init__(
        self,
        store: Any,
        run: dict[str, Any],
        semantic_threshold: float = 0.72,
        label_candidate_threshold: float = 0.45,
        dataset_check_every: int = 3,
    ):
        self.store = store
        self.run = run
        self.run_id = run["run_id"]
        self.mode = run["mode"]
        self.semantic_threshold = semantic_threshold
        self.label_candidate_threshold = label_candidate_threshold
        self.dataset_check_every = dataset_check_every
        self.entries: list[CacheEntry] = []
        self.events: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.label_items: list[dict[str, Any]] = []
        self.band_messages: list[dict[str, Any]] = []
        self.counter = 0
        self.baseline_cost = 0.0
        self.actual_cost = 0.0
        self.saved_cost = 0.0
        self.saved_latency = 0
        self.saved_tokens = 0

    def band_publish(self, agent_id: str, message: str) -> None:
        self.band_messages.append({"agent_id": agent_id, "message": message, "ts": utc_now()})

    def llm(self, agent_id: str, prompt: str, output_fn: Callable[[Any], str] | None = None) -> str:
        return self.call("llm", agent_id, "llm", {"visible_task_summary": prompt}, output_fn)

    def tool(self, agent_id: str, tool_name: str, args: dict[str, Any], output_fn: Callable[[Any], str] | None = None) -> str:
        return self.call("tool", agent_id, tool_name, args, output_fn)

    def call(
        self,
        call_kind: str,
        agent_id: str,
        tool_name: str,
        prompt_or_args: Any,
        output_fn: Callable[[Any], str] | None = None,
    ) -> str:
        self.counter += 1
        requested_at = utc_now()
        normalized_input = stable_json({"call_kind": call_kind, "tool_name": tool_name, "payload": prompt_or_args}).lower()
        input_hash = stable_hash(normalized_input)
        call_id = f"{self.run_id}-call-{self.counter:03d}"
        cacheability = classify_cacheability(call_kind, tool_name, prompt_or_args)
        input_tokens = estimate_tokens(prompt_or_args)
        estimated_output_tokens = max(24, input_tokens // 3)
        estimated_cost = round((input_tokens * 0.000003) + (estimated_output_tokens * 0.000012), 6)
        estimated_latency = min(3200, 320 + input_tokens * 14)
        self.baseline_cost += estimated_cost

        exact = next((entry for entry in self.entries if entry.input_hash == input_hash), None)
        candidate, similarity = self._nearest_candidate(prompt_or_args, call_kind, tool_name)
        plausible_candidate = candidate if candidate and similarity >= self.label_candidate_threshold else None
        source = exact or plausible_candidate
        exact_match = exact is not None
        if exact_match:
            similarity = 1.0

        if source:
            self._record_label_item(
                pair_id=f"{self.run_id}-{source.call_id}-{call_id}",
                new_call={
                    "agent_id": agent_id,
                    "call_kind": call_kind,
                    "tool_name": tool_name,
                    "prompt_or_args": prompt_or_args,
                    "requested_at": requested_at,
                },
                cached_call=source,
                cacheability=cacheability,
                similarity=similarity,
                exact_match=exact_match,
            )

        decision = "EXECUTE"
        verifier_score: float | None = None
        explanation = "No safe duplicate found."
        output: str
        saved_cost = 0.0
        saved_latency = 0
        saved_tokens = 0

        if self.mode == "redundant" and source and cacheability == "side_effecting":
            decision = "BLOCK_OR_WARN"
            output = f"Blocked duplicate side-effect risk for {tool_name}; human review required."
            verifier_score = 0.08
            explanation = "Similar side-effect action already happened; do not replay automatically."
            saved_cost, saved_latency, saved_tokens = estimated_cost, estimated_latency, input_tokens + estimated_output_tokens
        elif self.mode == "redundant" and exact and cacheability != "side_effecting":
            decision = "EXACT_REUSE"
            output = exact.output
            verifier_score = 1.0
            explanation = f"Redis exact cache hit from {exact.call_id}."
            saved_cost, saved_latency, saved_tokens = estimated_cost, estimated_latency, input_tokens + estimated_output_tokens
        elif self.mode == "redundant" and candidate and similarity >= self.semantic_threshold:
            hint = likely_label(cacheability, similarity, False)
            verifier_score = self._verifier_score(hint, similarity)
            if hint == "safe_reuse" and verifier_score >= 0.75:
                decision = "SEMANTIC_REUSE"
                output = candidate.output
                explanation = f"Redis semantic candidate approved by Terac-style verifier at {verifier_score:.2f}."
                saved_cost, saved_latency, saved_tokens = estimated_cost, estimated_latency, input_tokens + estimated_output_tokens
            elif input_tokens > 90 and cacheability != "side_effecting":
                decision = "COMPRESS_AND_EXECUTE"
                prompt_or_args = self._compress_payload(prompt_or_args)
                output = self._execute(prompt_or_args, output_fn, tool_name)
                explanation = "Reuse was unsafe, so Token Company-style compression was applied before execution."
                self.actual_cost += round(estimated_cost * 0.62, 6)
            else:
                output = self._execute(prompt_or_args, output_fn, tool_name)
                explanation = f"Verifier blocked semantic reuse as {hint}."
                self.actual_cost += estimated_cost
        elif input_tokens > 120 and cacheability != "side_effecting" and self.mode == "redundant":
            decision = "COMPRESS_AND_EXECUTE"
            prompt_or_args = self._compress_payload(prompt_or_args)
            output = self._execute(prompt_or_args, output_fn, tool_name)
            explanation = "No reusable candidate found; Token Company-style compression reduced prompt cost."
            self.actual_cost += round(estimated_cost * 0.62, 6)
        else:
            output = self._execute(prompt_or_args, output_fn, tool_name)
            self.actual_cost += estimated_cost

        if decision in {"EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN"}:
            self.saved_cost += saved_cost
            self.saved_latency += saved_latency
            self.saved_tokens += saved_tokens

        output_summary = self._summarize(output)
        if decision in {"EXECUTE", "COMPRESS_AND_EXECUTE"}:
            self.entries.append(
                CacheEntry(
                    call_id=call_id,
                    run_id=self.run_id,
                    agent_id=agent_id,
                    call_kind=call_kind,
                    tool_name=tool_name,
                    prompt_or_args=prompt_or_args,
                    normalized_input=normalized_input,
                    input_hash=input_hash,
                    output=output,
                    output_summary=output_summary,
                    cacheability=cacheability,
                    input_tokens=input_tokens,
                    output_tokens=estimate_tokens(output),
                    cost_usd=estimated_cost,
                    latency_ms=estimated_latency,
                    created_at=requested_at,
                    vector=embedding(prompt_or_args),
                )
            )

        call_record = {
            "call_id": call_id,
            "run_id": self.run_id,
            "agent_id": agent_id,
            "call_type": call_kind,
            "tool_name": tool_name,
            "cacheability": cacheability,
            "normalized_input": normalized_input,
            "input_hash": input_hash,
            "output": output_summary,
            "input_tokens": input_tokens,
            "output_tokens": estimate_tokens(output),
            "cost_usd": 0.0 if decision in {"EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN"} else estimated_cost,
            "latency_ms": 0 if decision in {"EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN"} else estimated_latency,
            "created_at": requested_at,
            "decision": decision,
            "reuse_source_call_id": source.call_id if source else None,
            "verifier_score": verifier_score,
            "explanation": explanation,
        }
        self.calls.append(call_record)
        self.store.append_call(self.run_id, call_record)
        event = self._event(call_record, source, saved_cost, saved_latency, saved_tokens)
        self.events.append(event)
        self.store.append_event(self.run_id, event)
        self._maybe_dataset_check(agent_id)
        return output

    def finish(self) -> dict[str, Any]:
        report = self.report()
        self.store.save_report(self.run_id, report)
        self.store.complete_run(self.run_id)
        return report

    def report(self) -> dict[str, Any]:
        attempted = len(self.calls)
        executed = sum(1 for call in self.calls if call["decision"] in {"EXECUTE", "COMPRESS_AND_EXECUTE"})
        reused = attempted - executed
        clusters = self._clusters()
        return {
            "run_id": self.run_id,
            "task": self.run["task"],
            "mode": self.mode,
            "status": "complete",
            "attempted_calls": attempted,
            "executed_calls": executed,
            "reused_or_blocked_calls": reused,
            "redundant_rate": round(reused / attempted, 3) if attempted else 0,
            "estimated_baseline_cost_usd": round(self.baseline_cost, 6),
            "actual_cost_usd": round(self.actual_cost, 6),
            "saved_cost_usd": round(max(self.baseline_cost - self.actual_cost, self.saved_cost), 6),
            "saved_latency_ms": self.saved_latency,
            "saved_tokens": self.saved_tokens,
            "worst_duplicate_cluster": clusters[0]["cluster_id"] if clusters else None,
            "clusters": clusters,
            "fixes": self._fixes(),
            "dataset": {
                "labelable_items_generated": len(self.label_items),
                "pure_llm_items_generated": sum(
                    1 for item in self.label_items if item["new_call"]["call_kind"] == "llm"
                ),
                "jsonl_path": str(self.store.label_data_path),
            },
            "band_messages": self.band_messages,
        }

    def _execute(self, prompt_or_args: Any, output_fn: Callable[[Any], str] | None, tool_name: str) -> str:
        if output_fn:
            return output_fn(prompt_or_args)
        return f"{tool_name} result for {stable_json(prompt_or_args)[:180]}"

    def _nearest_candidate(self, prompt_or_args: Any, call_kind: str, tool_name: str) -> tuple[CacheEntry | None, float]:
        target = embedding(prompt_or_args)
        best: tuple[CacheEntry | None, float] = (None, 0.0)
        for entry in self.entries:
            if entry.call_kind != call_kind:
                continue
            score = cosine(target, entry.vector)
            if tool_name == entry.tool_name:
                score = min(1.0, score + 0.08)
            if score > best[1]:
                best = (entry, score)
        return best

    def _record_label_item(
        self,
        pair_id: str,
        new_call: dict[str, Any],
        cached_call: CacheEntry,
        cacheability: str,
        similarity: float,
        exact_match: bool,
    ) -> None:
        safe_new_args, new_redacted = safe_payload(new_call["prompt_or_args"])
        safe_cached_args, cached_redacted = safe_payload(cached_call.prompt_or_args)
        label = likely_label(cacheability, similarity, exact_match)
        item = {
            "pair_id": pair_id,
            "trace_id": self.run_id,
            "created_at": utc_now(),
            "task_context": self.run["task"],
            "new_call": {
                "agent_id": new_call["agent_id"],
                "call_kind": new_call["call_kind"],
                "tool_name": new_call["tool_name"],
                "prompt_or_args": safe_new_args,
                "requested_at": new_call["requested_at"],
            },
            "candidate_cached_call": {
                "agent_id": cached_call.agent_id,
                "call_kind": cached_call.call_kind,
                "tool_name": cached_call.tool_name,
                "prompt_or_args": safe_cached_args,
                "output_summary": cached_call.output_summary,
                "cached_at": cached_call.created_at,
            },
            "runtime_signals": {
                "redis_similarity": similarity,
                "exact_key_match": exact_match,
                "cache_age_seconds": 0,
                "tool_has_side_effects": cacheability == "side_effecting",
                "contains_user_state": cacheability == "state_bound",
                "proposed_ttl_seconds": 300 if cacheability == "freshness_sensitive" else 3600,
            },
            "label_hint": {
                "likely_label": label,
                "why_labelable": label_reason(label, similarity, cacheability),
            },
            "privacy": {
                "redaction_applied": new_redacted or cached_redacted,
                "notes": "Visible prompt/output summaries only; hidden reasoning and internal prompts are excluded.",
            },
        }
        self.label_items.append(item)
        self.store.append_label_item(item)

    def _event(
        self,
        call: dict[str, Any],
        source: CacheEntry | None,
        saved_cost: float,
        saved_latency: int,
        saved_tokens: int,
    ) -> dict[str, Any]:
        hooks = ["Redis", "Redis Streams"]
        if call["call_type"] == "llm":
            hooks.append("Anthropic")
        if call["decision"] == "SEMANTIC_REUSE":
            hooks.append("Terac")
        if call["decision"] == "COMPRESS_AND_EXECUTE":
            hooks.append("Token Company")
        if call["decision"] == "BLOCK_OR_WARN":
            hooks.append("Sentry")
        hooks.append("Band")
        return {
            "event_id": self.store.next_event_id(self.run_id),
            "run_id": self.run_id,
            "ts": utc_now(),
            "agent_id": call["agent_id"],
            "call_id": call["call_id"],
            "call_type": call["call_type"],
            "tool_name": call["tool_name"],
            "decision": call["decision"],
            "cacheability": call["cacheability"],
            "summary": call["output"],
            "explanation": call["explanation"],
            "saved_cost_usd": round(saved_cost, 6),
            "saved_latency_ms": saved_latency,
            "saved_tokens": saved_tokens,
            "source_call_id": source.call_id if source else None,
            "verifier_score": call["verifier_score"],
            "cluster_id": self._cluster_id(call),
            "sponsor_hooks": sorted(set(hooks)),
        }

    def _maybe_dataset_check(self, agent_id: str) -> None:
        if self.counter % self.dataset_check_every:
            return
        event = {
            "event_id": self.store.next_event_id(self.run_id),
            "run_id": self.run_id,
            "ts": utc_now(),
            "agent_id": "dataset-monitor",
            "call_id": f"{self.run_id}-dataset-check-{self.counter:03d}",
            "call_type": "llm",
            "tool_name": "dataset_monitor",
            "decision": "EXECUTE",
            "cacheability": "pure",
            "summary": f"Dataset check after {self.counter} calls: {len(self.label_items)} labelable items generated.",
            "explanation": "Periodic verification that REDUNDANT_LABEL_DATA-style items are being produced.",
            "saved_cost_usd": 0,
            "saved_latency_ms": 0,
            "saved_tokens": 0,
            "source_call_id": None,
            "verifier_score": None,
            "cluster_id": "dataset-monitor",
            "sponsor_hooks": ["Terac", "Redis Streams"],
        }
        self.events.append(event)
        self.store.append_event(self.run_id, event)

    def _verifier_score(self, hint: str, similarity: float) -> float:
        if hint == "safe_reuse":
            return round(min(0.98, 0.68 + similarity * 0.24), 3)
        if hint == "unclear":
            return round(0.45 + similarity * 0.12, 3)
        return round(max(0.05, 0.28 - similarity * 0.08), 3)

    def _summarize(self, output: str) -> str:
        clean = " ".join(output.split())
        return clean[:260] + ("..." if len(clean) > 260 else "")

    def _compress_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            compressed = dict(value)
            for key, item in list(compressed.items()):
                if isinstance(item, str) and len(item) > 220:
                    compressed[key] = item[:160] + " ... [compressed]"
            compressed["compression"] = "token-company-style"
            return compressed
        if isinstance(value, str):
            return value[:180] + " ... [compressed]"
        return value

    def _cluster_id(self, call: dict[str, Any]) -> str:
        text = call["normalized_input"]
        if "redis" in text or "langcache" in text:
            return "cluster-redis-cache"
        if "terac" in text or "label" in text:
            return "cluster-terac-labels"
        if "sentry" in text or "issue" in text:
            return "cluster-sentry-side-effects"
        if "repo" in text or "branch" in text:
            return "cluster-state-bound-repo"
        if call["call_type"] == "llm":
            return "cluster-llm-planning"
        return "cluster-general-tools"

    def _clusters(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for call in self.calls:
            grouped.setdefault(self._cluster_id(call), []).append(call)
        clusters = []
        for cluster_id, calls in grouped.items():
            saved = sum(event["saved_cost_usd"] for event in self.events if event.get("cluster_id") == cluster_id)
            agents = sorted({call["agent_id"] for call in calls})
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "label": cluster_id.replace("cluster-", "").replace("-", " ").title(),
                    "calls": len(calls),
                    "unique_needed": max(1, sum(1 for call in calls if call["decision"] in {"EXECUTE", "COMPRESS_AND_EXECUTE"})),
                    "waste_percent": round((1 - (1 / max(1, len(calls)))) * 100, 1),
                    "saved_cost_usd": round(saved, 6),
                    "saved_latency_ms": sum(event["saved_latency_ms"] for event in self.events if event.get("cluster_id") == cluster_id),
                    "agent_ids": agents,
                }
            )
        return sorted(clusters, key=lambda item: (item["calls"], item["saved_cost_usd"]), reverse=True)

    def _fixes(self) -> list[dict[str, Any]]:
        return [
            {
                "fix_id": "fix-redis-ttl",
                "title": "Cache stable sponsor research with Redis TTLs",
                "description": "Use longer TTLs for pure Redis/Band/Terac summaries and short TTLs for pricing/current availability.",
                "sponsor_hook": "Redis",
                "code_hint": '@redundant.cached_tool(ttl="1h")',
            },
            {
                "fix_id": "fix-terac-verifier",
                "title": "Gate semantic reuse with Terac labels",
                "description": "Feed generated review items into Terac so the verifier learns which semantic hits are unsafe.",
                "sponsor_hook": "Terac",
                "code_hint": "CacheReuseReviewItem -> TeracReuseAnswer",
            },
            {
                "fix_id": "fix-side-effect-sentry",
                "title": "Report repeated side effects to Sentry",
                "description": "Treat repeated issue creation or posting as a warning, not as an automatic replay.",
                "sponsor_hook": "Sentry",
                "code_hint": "decision == BLOCK_OR_WARN",
            },
            {
                "fix_id": "fix-prompt-compression",
                "title": "Compress long unsafe prompts",
                "description": "When reuse is unsafe, keep savings by compressing stable context before execution.",
                "sponsor_hook": "Token Company",
                "code_hint": "COMPRESS_AND_EXECUTE",
            },
        ]
