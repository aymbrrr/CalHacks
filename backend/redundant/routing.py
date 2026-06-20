"""Routing brain (§7.4 of DESIGN_redis.md).

Single source of truth for wasteful-vs-runaway routing. Detectors produce
findings with severity/route unset ("wasteful"/"cache" as defaults); this
module overwrites those fields according to the routing table.
"""
from __future__ import annotations

from redundant.detection import R_MAX
from redundant.span_schema import Finding


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
