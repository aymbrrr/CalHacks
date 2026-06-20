"""Routing brain (§7.4) + LangCache (§7.5) per DESIGN_redis.md.

Routing brain: mutates Finding.severity / route based on R_max, convergence,
and side-effect status.

LangCache: exact-hash Redis SET/GET.  Falls back to an in-process dict when
Redis is unavailable so the demo never hard-crashes.
"""
from __future__ import annotations
from typing import Optional

from redundant.detection import R_MAX, READ_ONLY_TOOLS
from redundant.span_schema import Finding

# Cache TTL in seconds for read-only tool results.
_CACHE_TTL = 24 * 3600


# ---------------------------------------------------------------------------
# Routing brain
# ---------------------------------------------------------------------------

def route_findings(findings: list[Finding]) -> list[Finding]:
    """Apply routing rules to each finding in-place and return the list."""
    for f in findings:
        _route_one(f)
    return findings


def _route_one(f: Finding) -> None:
    # Any finding whose count hits R_max is runaway regardless of other signals.
    if f.count >= R_MAX:
        f.severity = "runaway"
        f.route = "alert"
        return

    # Non-converging outputs (outputs changing each repeat) = reliability incident.
    if f.evidence.convergence == "none":
        f.severity = "runaway"
        f.route = "alert"
        return

    # Side-effecting tools are never cacheable; escalate to alert.
    if not f.cacheable:
        f.severity = "runaway"
        f.route = "alert"
        return

    # Default: wasteful but cacheable.
    f.severity = "wasteful"
    f.route = "cache"


# ---------------------------------------------------------------------------
# LangCache — DIY exact-hash Redis SET/GET (§7.5 fallback path)
# ---------------------------------------------------------------------------

class LangCache:
    """Exact-hash cache keyed on (tool_name, input_hash).

    Uses Redis when available; falls back to an in-process dict.
    """

    def __init__(self, redis_client=None, ttl: int = _CACHE_TTL):
        self._r = redis_client
        self._ttl = ttl
        self._local: dict[str, str] = {}

    def _key(self, tool_name: str, input_hash: str) -> str:
        return f"cache:{tool_name}:{input_hash}"

    def get(self, tool_name: str, input_hash: str) -> Optional[str]:
        """Return cached result or None (staleness gate: TTL enforced by Redis)."""
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

    def put(self, tool_name: str, input_hash: str, result: str) -> None:
        """Cache result only if tool is in the read-only allowlist (cacheability gate)."""
        if tool_name not in READ_ONLY_TOOLS:
            return  # side-effecting: never store
        key = self._key(tool_name, input_hash)
        if self._r is not None:
            try:
                self._r.set(key, result, ex=self._ttl)
                return
            except Exception:
                pass
        self._local[key] = result

    def populate_from_findings(self, findings: list[Finding],
                                spans_by_id: dict) -> int:
        """Write cacheable findings' representative results into the cache.
        Returns the number of entries written."""
        written = 0
        for f in findings:
            if f.route != "cache":
                continue
            rep = spans_by_id.get(f.representative_span_id)
            if rep is None or not rep.tool_name:
                continue
            self.put(rep.tool_name, rep.input_hash, rep.output)
            written += 1
        return written
