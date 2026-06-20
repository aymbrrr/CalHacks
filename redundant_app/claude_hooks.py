from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime import safe_payload, stable_hash, utc_now
from .storage import JsonlStore


EVENTS_FILE = "claude-code-hook-events.jsonl"
CALLS_FILE = "claude-code-captured-calls.jsonl"
LABEL_SOURCE = "claude_code_hook"


@dataclass
class CaptureResult:
    event_name: str
    captured_call: dict[str, Any] | None
    label_item: dict[str, Any] | None
    stats: dict[str, Any]


def handle_hook_stdin(argv: list[str] | None = None, stdin: str | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture Claude Code hook events for Redundant")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--context", action="store_true", help="Return additional Claude context when Redundant finds a candidate")
    parser.add_argument("--similarity-threshold", type=float, default=0.56)
    args = parser.parse_args(argv)

    raw = stdin if stdin is not None else sys.stdin.read()
    try:
        event = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        if args.context:
            print(_hook_context_json(f"Redundant could not parse hook input: {exc}"))
        return 0

    result = capture_hook_event(
        event,
        data_dir=args.data_dir,
        similarity_threshold=args.similarity_threshold,
    )
    if args.context and result.label_item:
        label = result.label_item.get("label_hint", {}).get("likely_label", "unclear")
        call = result.captured_call or {}
        text = (
            f"Redundant captured this Claude Code turn and found a prior {call.get('call_kind', 'call')} "
            f"candidate for review ({label}). Dataset now has {result.stats['total_items']} items, "
            f"{result.stats['pure_llm_items']} pure LLM."
        )
        print(_hook_context_json(text))
    return 0


def capture_hook_event(
    event: dict[str, Any],
    data_dir: str | Path = "data",
    similarity_threshold: float = 0.56,
) -> CaptureResult:
    store = JsonlStore(data_dir)
    data_path = Path(data_dir)
    _append_jsonl(data_path / EVENTS_FILE, _safe_event(event))

    event_name = event.get("hook_event_name", "unknown")
    captured = None
    if event_name == "UserPromptSubmit":
        captured = _call_from_prompt(event)
    elif event_name == "PostToolUse":
        captured = _call_from_post_tool(event)
    elif event_name == "PreToolUse":
        captured = _pre_tool_marker(event)

    label_item = None
    if captured and captured.get("recordable"):
        prior = _best_prior_call(data_path / CALLS_FILE, captured, similarity_threshold)
        if prior:
            label_item = _label_item_from_pair(event, prior, captured)
            store.append_label_item(label_item)
        _append_jsonl(data_path / CALLS_FILE, captured)

    return CaptureResult(
        event_name=event_name,
        captured_call=captured,
        label_item=label_item,
        stats=store.dataset_stats(),
    )


def _call_from_prompt(event: dict[str, Any]) -> dict[str, Any]:
    prompt = str(event.get("prompt", ""))
    safe_prompt, redacted = safe_payload({"visible_task_summary": _summarize(prompt, 600)})
    return {
        "record_id": _record_id(event, "prompt"),
        "session_id": event.get("session_id", "unknown-session"),
        "created_at": utc_now(),
        "call_kind": "llm",
        "tool_name": "none",
        "agent_id": "claude-code-user",
        "prompt_or_args": safe_prompt,
        "output_summary": "Claude Code user prompt captured before model processing; assistant output is not included in this hook.",
        "redaction_applied": redacted,
        "recordable": bool(prompt.strip()),
    }


def _call_from_post_tool(event: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(event.get("tool_name", "unknown"))
    safe_args, args_redacted = safe_payload(_tool_input_summary(tool_name, event.get("tool_input", {})))
    safe_response, response_redacted = safe_payload(_tool_response_summary(event.get("tool_response", {})))
    return {
        "record_id": _record_id(event, f"tool-{tool_name}"),
        "session_id": event.get("session_id", "unknown-session"),
        "created_at": utc_now(),
        "call_kind": _call_kind_for_tool(tool_name),
        "tool_name": tool_name,
        "agent_id": "claude-code",
        "prompt_or_args": safe_args,
        "output_summary": _summarize(safe_response, 260),
        "redaction_applied": args_redacted or response_redacted,
        "duration_ms": event.get("duration_ms"),
        "recordable": True,
    }


def _pre_tool_marker(event: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(event.get("tool_name", "unknown"))
    safe_args, redacted = safe_payload(_tool_input_summary(tool_name, event.get("tool_input", {})))
    return {
        "record_id": _record_id(event, f"pre-{tool_name}"),
        "session_id": event.get("session_id", "unknown-session"),
        "created_at": utc_now(),
        "call_kind": _call_kind_for_tool(tool_name),
        "tool_name": tool_name,
        "agent_id": "claude-code",
        "prompt_or_args": safe_args,
        "output_summary": "Claude Code tool input captured before execution.",
        "redaction_applied": redacted,
        "recordable": False,
    }


def _best_prior_call(path: Path, call: dict[str, Any], threshold: float) -> dict[str, Any] | None:
    best: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for prior in _read_jsonl(path):
        if prior.get("record_id") == call.get("record_id"):
            continue
        if prior.get("call_kind") != call.get("call_kind"):
            continue
        if prior.get("tool_name") != call.get("tool_name"):
            continue
        score = _similarity(prior.get("prompt_or_args", {}), call.get("prompt_or_args", {}))
        if score > best[1]:
            best = (prior, score)
    if best[0] and best[1] >= threshold:
        matched = dict(best[0])
        matched["redis_similarity"] = best[1]
        return matched
    return None


def _label_item_from_pair(event: dict[str, Any], prior: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    similarity = float(prior.get("redis_similarity", 0.0))
    exact = stable_hash(prior.get("prompt_or_args")) == stable_hash(call.get("prompt_or_args"))
    label = _likely_label(call, similarity, exact)
    return {
        "pair_id": f"claude_code_{prior['record_id']}_{call['record_id']}",
        "trace_id": event.get("session_id", "claude-code-session"),
        "created_at": utc_now(),
        "task_context": "Claude Code hook captured a repeated or near-repeated visible prompt/tool call.",
        "source": LABEL_SOURCE,
        "new_call": {
            "agent_id": call.get("agent_id", "claude-code"),
            "call_kind": call["call_kind"],
            "tool_name": call["tool_name"],
            "prompt_or_args": call["prompt_or_args"],
            "requested_at": call.get("created_at"),
        },
        "candidate_cached_call": {
            "agent_id": prior.get("agent_id", "claude-code"),
            "call_kind": prior["call_kind"],
            "tool_name": prior["tool_name"],
            "prompt_or_args": prior["prompt_or_args"],
            "output_summary": prior.get("output_summary", "Prior Claude Code call captured by Redundant."),
            "cached_at": prior.get("created_at"),
        },
        "runtime_signals": {
            "redis_similarity": similarity,
            "exact_key_match": exact,
            "cache_age_seconds": None,
            "tool_has_side_effects": _tool_has_side_effects(call.get("tool_name", "")),
            "contains_user_state": _contains_user_state(call.get("prompt_or_args", {})),
            "proposed_ttl_seconds": 300 if label == "needs_freshness_check" else 3600,
            "cache_backend": "claude-code-hook",
        },
        "label_hint": {
            "likely_label": label,
            "why_labelable": _label_reason(label),
        },
        "privacy": {
            "redaction_applied": bool(prior.get("redaction_applied")) or bool(call.get("redaction_applied")),
            "notes": "Claude Code hook captures visible user prompts and summarized tool metadata only.",
        },
    }


def _tool_input_summary(tool_name: str, tool_input: Any) -> dict[str, Any]:
    if not isinstance(tool_input, dict):
        return {"input_summary": _summarize(tool_input)}
    if tool_name in {"Write", "Edit", "MultiEdit"}:
        out = {key: value for key, value in tool_input.items() if key not in {"content", "old_string", "new_string", "edits"}}
        for key in ("content", "old_string", "new_string"):
            if key in tool_input:
                out[f"{key}_summary"] = f"{len(str(tool_input[key]))} chars"
        if "edits" in tool_input:
            out["edits_summary"] = f"{len(tool_input.get('edits') or [])} edits"
        return out
    return tool_input


def _tool_response_summary(tool_response: Any) -> Any:
    if isinstance(tool_response, dict):
        out: dict[str, Any] = {}
        for key, value in tool_response.items():
            if key in {"stdout", "stderr", "content"}:
                out[key] = _summarize(value, 260)
            else:
                out[key] = value
        return out
    return _summarize(tool_response, 260)


def _call_kind_for_tool(tool_name: str) -> str:
    if tool_name in {"Read", "Write", "Edit", "MultiEdit", "Glob", "Grep"}:
        return "repo"
    if tool_name in {"WebFetch", "WebSearch"}:
        return "browser"
    return "tool"


def _tool_has_side_effects(tool_name: str) -> bool:
    return tool_name in {"Write", "Edit", "MultiEdit", "Bash"}


def _contains_user_state(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, default=str).lower()
    return any(word in text for word in ("private", "account", "token", "secret", "cookie", "my repo", "local"))


def _likely_label(call: dict[str, Any], similarity: float, exact: bool) -> str:
    if _tool_has_side_effects(call.get("tool_name", "")):
        return "side_effect_risk"
    if _contains_user_state(call.get("prompt_or_args", {})):
        return "state_specific"
    if _freshness_sensitive(call.get("prompt_or_args", {})):
        return "needs_freshness_check"
    if exact or similarity >= 0.82:
        return "safe_reuse"
    if similarity >= 0.62:
        return "unclear"
    return "not_equivalent"


def _freshness_sensitive(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, default=str).lower()
    return any(word in text for word in ("latest", "current", "today", "pricing", "news", "availability"))


def _label_reason(label: str) -> str:
    reasons = {
        "safe_reuse": "The later Claude Code call appears reusable from the earlier captured call.",
        "side_effect_risk": "The later call may mutate files or execute commands, so it needs human review.",
        "state_specific": "The later call depends on local or user-specific state.",
        "needs_freshness_check": "The later call may depend on current information.",
        "unclear": "The calls are similar enough to label, but safety is uncertain.",
        "not_equivalent": "The calls overlap lexically but likely ask for different work.",
    }
    return reasons.get(label, reasons["unclear"])


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    safe, _ = safe_payload(event)
    if isinstance(safe, dict) and "tool_input" in safe:
        safe["tool_input"] = _tool_input_summary(str(safe.get("tool_name", "")), safe["tool_input"])
    return {"captured_at": utc_now(), "event": safe}


def _record_id(event: dict[str, Any], prefix: str) -> str:
    raw = {
        "prefix": prefix,
        "session_id": event.get("session_id"),
        "tool_use_id": event.get("tool_use_id"),
        "prompt": event.get("prompt"),
        "tool_name": event.get("tool_name"),
        "tool_input": event.get("tool_input"),
    }
    return f"{prefix}_{stable_hash(raw)}"


def _summarize(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    clean = " ".join(str(text).split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def _similarity(left: Any, right: Any) -> float:
    left_words = _tokens(left)
    right_words = _tokens(right)
    if not left_words or not right_words:
        return 0.0
    intersection = len(left_words & right_words)
    union = len(left_words | right_words)
    return round(intersection / union, 4)


def _tokens(value: Any) -> set[str]:
    text = json.dumps(value, sort_keys=True, default=str).lower()
    return {word for word in re.findall(r"[a-z0-9]+", text) if len(word) > 2}


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _hook_context_json(text: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            }
        },
        sort_keys=True,
    )
