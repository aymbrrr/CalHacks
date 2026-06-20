from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()[:16]


def cache_prompt(call_kind: str, tool_name: str, prompt_or_args: Any) -> str:
    return stable_json({"call_kind": call_kind, "tool_name": tool_name, "payload": prompt_or_args})


def input_hash_for(prompt: str) -> str:
    return stable_hash(prompt.lower())


def parse_cache_prompt(prompt: str) -> dict[str, Any]:
    try:
        parsed = json.loads(prompt)
    except json.JSONDecodeError:
        return {"call_kind": "unknown", "tool_name": "unknown", "payload": {"prompt": prompt}}
    if not isinstance(parsed, dict):
        return {"call_kind": "unknown", "tool_name": "unknown", "payload": parsed}
    return parsed


def _words(value: Any) -> list[str]:
    text = stable_json(value).lower()
    return [word for word in re.findall(r"[a-z0-9]+", text) if len(word) > 2]


def _embedding(value: Any) -> dict[str, float]:
    counts: dict[str, float] = {}
    for word in _words(value):
        stem = word[:-1] if word.endswith("s") and len(word) > 4 else word
        counts[stem] = counts.get(stem, 0.0) + 1.0
    return counts


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(weight * right.get(key, 0.0) for key, weight in left.items())
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return round(dot / (left_norm * right_norm), 4)


@dataclass
class CachedCall:
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
    langcache_entry_id: str | None = None
    vector: dict[str, float] = field(default_factory=dict)

    def attributes(self) -> dict[str, str]:
        return {
            "call_id": self.call_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "call_kind": self.call_kind,
            "tool_name": self.tool_name,
            "input_hash": self.input_hash,
            "cacheability": self.cacheability,
            "output_summary": self.output_summary,
            "input_tokens": str(self.input_tokens),
            "output_tokens": str(self.output_tokens),
            "cost_usd": str(self.cost_usd),
            "latency_ms": str(self.latency_ms),
            "created_at": self.created_at,
        }


@dataclass
class CacheLookup:
    exact_entry: CachedCall | None = None
    semantic_entry: CachedCall | None = None
    similarity: float = 0.0
    backend: str = "local-langcache-contract"
    error: str | None = None


class LocalLangCacheBackend:
    backend_name = "local-langcache-contract"

    def __init__(self) -> None:
        self.entries: list[CachedCall] = []

    def search(
        self,
        *,
        prompt: str,
        attributes: dict[str, str],
        input_hash: str,
        similarity_threshold: float,
    ) -> CacheLookup:
        matching = [entry for entry in self.entries if self._matches_attributes(entry, attributes)]
        exact = next((entry for entry in matching if entry.input_hash == input_hash), None)
        best: tuple[CachedCall | None, float] = (None, 0.0)
        target = _embedding(prompt)
        for entry in matching:
            score = _cosine(target, entry.vector)
            if score > best[1]:
                best = (entry, score)
        semantic = best[0] if best[0] and best[1] >= similarity_threshold else None
        return CacheLookup(
            exact_entry=exact,
            semantic_entry=semantic,
            similarity=1.0 if exact else best[1],
            backend=self.backend_name,
        )

    def store(self, entry: CachedCall) -> None:
        entry.vector = _embedding(entry.normalized_input)
        self.entries.append(entry)

    def _matches_attributes(self, entry: CachedCall, attributes: dict[str, str]) -> bool:
        return all(str(getattr(entry, key, "")) == value for key, value in attributes.items())


class SDKLangCacheBackend:
    backend_name = "redis-langcache-sdk"

    def __init__(self, server_url: str, cache_id: str, api_key: str, fallback: LocalLangCacheBackend | None = None) -> None:
        from langcache import LangCache

        self.client = LangCache(server_url=server_url, cache_id=cache_id, api_key=api_key)
        self.fallback = fallback or LocalLangCacheBackend()

    def search(
        self,
        *,
        prompt: str,
        attributes: dict[str, str],
        input_hash: str,
        similarity_threshold: float,
    ) -> CacheLookup:
        try:
            from langcache.models import SearchStrategy

            response = self.client.search(
                prompt=prompt,
                attributes=attributes,
                search_strategies=[SearchStrategy.EXACT, SearchStrategy.SEMANTIC],
                similarity_threshold=similarity_threshold,
                max_results=3,
            )
            exact: CachedCall | None = None
            semantic: CachedCall | None = None
            similarity = 0.0
            for hit in response.data:
                cached = self._cached_call_from_hit(hit)
                similarity = max(similarity, float(hit.similarity))
                strategy = getattr(hit.search_strategy, "value", hit.search_strategy)
                if strategy == "exact" or cached.input_hash == input_hash:
                    exact = cached
                elif semantic is None:
                    semantic = cached
            return CacheLookup(
                exact_entry=exact,
                semantic_entry=semantic,
                similarity=1.0 if exact else similarity,
                backend=self.backend_name,
            )
        except Exception as exc:  # noqa: BLE001 - LangCache preview/network errors should not break the demo
            lookup = self.fallback.search(
                prompt=prompt,
                attributes=attributes,
                input_hash=input_hash,
                similarity_threshold=similarity_threshold,
            )
            lookup.backend = f"{self.backend_name}->fallback"
            lookup.error = str(exc)
            return lookup

    def store(self, entry: CachedCall) -> None:
        self.fallback.store(entry)
        try:
            response = self.client.set(prompt=entry.normalized_input, response=entry.output, attributes=entry.attributes())
            entry.langcache_entry_id = getattr(response, "entry_id", None)
        except Exception:
            return

    def _cached_call_from_hit(self, hit: Any) -> CachedCall:
        attrs = dict(getattr(hit, "attributes", {}) or {})
        parsed = parse_cache_prompt(hit.prompt)
        return CachedCall(
            call_id=attrs.get("call_id", getattr(hit, "id", "langcache-hit")),
            run_id=attrs.get("run_id", "remote-langcache"),
            agent_id=attrs.get("agent_id", "unknown-agent"),
            call_kind=attrs.get("call_kind", str(parsed.get("call_kind", "unknown"))),
            tool_name=attrs.get("tool_name", str(parsed.get("tool_name", "unknown"))),
            prompt_or_args=parsed.get("payload", {}),
            normalized_input=hit.prompt,
            input_hash=attrs.get("input_hash", input_hash_for(hit.prompt)),
            output=hit.response,
            output_summary=attrs.get("output_summary", hit.response[:260]),
            cacheability=attrs.get("cacheability", "pure"),
            input_tokens=int(attrs.get("input_tokens", "0") or 0),
            output_tokens=int(attrs.get("output_tokens", "0") or 0),
            cost_usd=float(attrs.get("cost_usd", "0") or 0),
            latency_ms=int(attrs.get("latency_ms", "0") or 0),
            created_at=attrs.get("created_at", ""),
            langcache_entry_id=getattr(hit, "id", None),
        )


def build_langcache_backend() -> LocalLangCacheBackend | SDKLangCacheBackend:
    if os.getenv("REDUNDANT_CACHE_BACKEND", "").lower() == "local":
        return LocalLangCacheBackend()

    server_url = os.getenv("LANGCACHE_SERVER_URL") or os.getenv("LANGCACHE_URL")
    host = os.getenv("LANGCACHE_HOST") or os.getenv("HOST")
    if not server_url and host:
        server_url = host if host.startswith("http") else f"https://{host}"
    cache_id = os.getenv("LANGCACHE_CACHE_ID") or os.getenv("CACHE_ID")
    api_key = os.getenv("LANGCACHE_API_KEY") or os.getenv("API_KEY")

    if server_url and cache_id and api_key:
        try:
            return SDKLangCacheBackend(server_url=server_url, cache_id=cache_id, api_key=api_key)
        except Exception:
            return LocalLangCacheBackend()
    return LocalLangCacheBackend()
