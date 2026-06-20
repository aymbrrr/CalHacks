"""Deterministic demo tools.

Outputs are a pure function of inputs so reuse is observable and the demo is
reproducible offline (no real network). Each tool declares a default
cacheability class. A side-effecting tool records invocations so tests can prove
it is never auto-replayed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from redundant.schema import Cacheability


def _stable_blurb(seed: str, n: int = 3) -> str:
    lines = []
    for i in range(n):
        h = hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:8]
        lines.append(f"- finding {i+1} [{h}]")
    return "\n".join(lines)


def search_docs(query: str = "", **_: Any) -> str:
    return f"Top results for '{query}':\n{_stable_blurb('search:' + query)}"


def summarize_page(url_or_text: str = "", **_: Any) -> str:
    return f"Summary of {url_or_text[:40]!r}:\n{_stable_blurb('sum:' + url_or_text)}"


def scan_repo(topic: str = "", **_: Any) -> str:
    return f"Repo scan for '{topic}':\n{_stable_blurb('repo:' + topic)}"


def compare_tools(tool_a: str = "", tool_b: str = "", **_: Any) -> str:
    return f"Comparison {tool_a} vs {tool_b}:\n{_stable_blurb('cmp:' + tool_a + tool_b)}"


@dataclass
class SideEffectLog:
    sends: list[dict] = field(default_factory=list)


SIDE_EFFECT_LOG = SideEffectLog()


def send_email(to: str = "", subject: str = "", **_: Any) -> str:
    # Records the side effect so a test can assert it did not replay.
    SIDE_EFFECT_LOG.sends.append({"to": to, "subject": subject})
    return f"email-sent:{to}:{subject}"


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable[..., str]
    cacheability: Cacheability


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_docs": ToolSpec(search_docs, Cacheability.PURE),
    "summarize_page": ToolSpec(summarize_page, Cacheability.PURE),
    "scan_repo": ToolSpec(scan_repo, Cacheability.PURE),
    "compare_tools": ToolSpec(compare_tools, Cacheability.PURE),
    "send_email": ToolSpec(send_email, Cacheability.SIDE_EFFECTING),
}


def default_cacheability(tool_name: str) -> Cacheability:
    spec = TOOL_REGISTRY.get(tool_name)
    return spec.cacheability if spec else Cacheability.PURE


def run_tool(tool_name: str, args: dict[str, Any]) -> str:
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        raise KeyError(f"unknown tool: {tool_name}")
    return spec.fn(**(args or {}))
