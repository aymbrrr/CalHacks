"""LangCache (§7.5 of DESIGN_redis.md) — DIY exact-hash Redis SET/GET.

Key scheme matches RedisStore._exact_key so both paths share the same cache:
  redundant:cache:exact:{scope_key}:{input_hash}

Falls back to an in-process dict when Redis is unavailable so the demo never
hard-crashes.

Routing brain has moved to redundant.routing.
"""
from __future__ import annotations
from typing import Optional

from redundant.config import SETTINGS
from redundant.detection import READ_ONLY_TOOLS
from redundant.span_schema import Finding

_CACHE_TTL = 24 * 3600
_NS = SETTINGS.namespace


class LangCache:
    """Exact-hash cache keyed on (scope_key, input_hash).

    scope_key defaults to the tool name for the /findings pre-warm path so
    lookups from /findings/cache-lookup (which only have tool_name + input_hash)
    still resolve correctly.
    """

    def __init__(self, redis_client=None, ttl: int = _CACHE_TTL, namespace: str = _NS):
        self._r = redis_client
        self._ttl = ttl
        self._ns = namespace
        self._local: dict[str, str] = {}

    def _key(self, scope_key: str, input_hash: str) -> str:
        return f"{self._ns}:cache:exact:{scope_key}:{input_hash}"

    def get(self, tool_name: str, input_hash: str) -> Optional[str]:
        """Return cached result or None. scope_key = tool_name for simple lookups."""
        key = self._key(tool_name, input_hash)
        if self._r is not None:
            try:
                raw = self._r.get(key)
                if raw:
                    return raw.decode("utf-8") if isinstance(raw, bytes) else raw
                return None
            except Exception:
                pass
        return self._local.get(key)

    def put(self, tool_name: str, input_hash: str, result: str) -> bool:
        """Cache result only if tool is in the read-only allowlist (cacheability
        gate). Returns True if an entry was actually written."""
        if tool_name not in READ_ONLY_TOOLS:
            return False
        key = self._key(tool_name, input_hash)
        if self._r is not None:
            try:
                self._r.set(key, result, ex=self._ttl)
                return True
            except Exception:
                pass
        self._local[key] = result
        return True

    def populate_from_findings(self, findings: list[Finding], spans_by_id: dict) -> int:
        """Write cacheable findings' representative results into the cache.
        Returns the number of entries written."""
        written = 0
        for f in findings:
            if f.route != "cache":
                continue
            rep = spans_by_id.get(f.representative_span_id)
            if rep is None:
                continue
            # LLM spans have no tool_name; use the span name as the cache key.
            tool_name = rep.tool_name or rep.name
            if not tool_name:
                continue
            if self.put(tool_name, rep.input_hash, rep.output):
                written += 1
        return written
