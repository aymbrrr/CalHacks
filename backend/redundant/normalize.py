"""Normalization + deterministic hashing.

Turns tool args / LLM messages into a canonical string so that calls that are
*semantically the same* but textually different (reordered keys, volatile
timestamps, whitespace, casing) collapse to the same exact-cache hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Keys that should never affect the cache identity of a call.
VOLATILE_KEYS = {
    "timestamp",
    "ts",
    "time",
    "now",
    "request_id",
    "requestid",
    "trace_id",
    "traceid",
    "nonce",
    "idempotency_key",
    "_meta",
}

_WS = re.compile(r"\s+")


def _canon_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return _WS.sub(" ", value.strip()).lower()
    return value


def _canon(value: Any) -> Any:
    """Recursively canonicalize a JSON-like value: drop volatile keys, sort keys,
    trim/lowercase strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in VOLATILE_KEYS:
                continue
            out[str(k)] = _canon(v)
        return {k: out[k] for k in sorted(out)}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return _canon_scalar(value)


def normalize_tool_args(tool_name: str, args: dict[str, Any]) -> str:
    """Canonical JSON string identifying a tool call."""
    payload = {"tool": tool_name.strip().lower(), "args": _canon(args or {})}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_messages(messages: list[dict[str, Any]], model: str | None = None) -> str:
    """Canonical JSON string identifying an LLM call.

    Model is included because identical messages to different models are
    different calls; system/user roles are preserved in order.
    """
    canon_msgs = []
    for m in messages or []:
        role = str(m.get("role", "")).strip().lower()
        content = m.get("content", "")
        if isinstance(content, list):
            # Anthropic block content -> concatenate text blocks.
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
            content = " ".join(parts)
        canon_msgs.append({"role": role, "content": _canon_scalar(str(content))})
    payload = {"model": (model or "").strip().lower(), "messages": canon_msgs}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scope_key(run_id: str, cacheability: str, state_fingerprint: str | None = None) -> str:
    """Cache scope. Run-scoped (NOT agent-scoped) so reuse crosses agents.

    state_bound calls additionally fold in the state fingerprint so a cached
    result is only reused for the same underlying state (inbox, repo, user...).
    """
    base = f"run:{run_id}"
    if cacheability == "state_bound" and state_fingerprint:
        return f"{base}:state:{state_fingerprint}"
    return base


def compute_hash(scope: str, normalized_input: str) -> str:
    """Deterministic SHA-256 over scope + normalized input."""
    h = hashlib.sha256()
    h.update(scope.encode("utf-8"))
    h.update(b"\x00")
    h.update(normalized_input.encode("utf-8"))
    return h.hexdigest()
