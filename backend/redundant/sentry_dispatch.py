"""Sentry alert arm (docs/SENTRY_REQUIREMENTS.md).

Consumes `route == "alert"` findings and fires one rich Sentry incident per
finding. Falls back to a local mock sink when no `SENTRY_DSN` is configured or
the Sentry API is unreachable, so the demo never depends on a live network call.

Contract (SR §4, Option A): in-process `dispatch_alert(finding, span, run_id)`.
The core router (here, the /findings endpoint) calls it for each alert finding.
"""
from __future__ import annotations

from typing import Optional

from redundant.config import SETTINGS, Settings
from redundant.span_schema import Finding, Span

try:
    import sentry_sdk
except Exception:  # pragma: no cover - sentry_sdk is a hard dep, defensive only
    sentry_sdk = None  # type: ignore


# --- module state -----------------------------------------------------------

# Whether sentry_sdk.init succeeded with a real DSN. False → mock mode (SR-9).
_REAL_MODE = False
# Records fired events when in mock mode (or on a real-mode send failure).
MOCK_EVENTS: list[dict] = []
# In-process idempotency set, used when no Redis client is available (SR-6).
_FIRED: set[str] = set()


def init_sentry(settings: Settings = SETTINGS) -> bool:
    """Initialize the Sentry SDK from the DSN (SR-1). Returns True if real mode.

    No DSN, no SDK, or any init failure → mock mode (returns False), never raises.
    """
    global _REAL_MODE
    _REAL_MODE = False
    if not settings.sentry_dsn or sentry_sdk is None:
        return False
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            default_integrations=False,
            traces_sample_rate=0.0,
        )
        _REAL_MODE = True
    except Exception:
        _REAL_MODE = False
    return _REAL_MODE


def reset() -> None:
    """Clear mock sink + idempotency state. For tests/demo re-runs."""
    MOCK_EVENTS.clear()
    _FIRED.clear()


def _already_fired(run_id: str, dedup_id: str, redis_client) -> bool:
    """Atomically mark (run_id, dedup_id) fired; True if it was already fired."""
    key = f"sentry:fired:{run_id}"
    if redis_client is not None:
        try:
            # SADD returns 1 for a new member, 0 if it already existed.
            added = redis_client.sadd(key, dedup_id)
            try:
                redis_client.expire(key, 3600)
            except Exception:
                pass
            return int(added) == 0
        except Exception:
            pass  # fall through to in-process tracking
    marker = f"{run_id}:{dedup_id}"
    if marker in _FIRED:
        return True
    _FIRED.add(marker)
    return False


def _classify(finding: Finding, settings: Settings) -> str:
    """Re-derive why a finding routed to alert (routing collapses the reasons)."""
    if finding.type == "cycle":
        return "cycle"
    if finding.count >= settings.r_max or finding.evidence.convergence == "none":
        return "runaway"
    return "side_effecting"


def _build_event(finding: Finding, span: Optional[Span], run_id: str,
                 kind: str, settings: Settings) -> dict:
    agent = span.agent_name if span else "unknown"
    tool = (span.tool_name or span.name) if span else "unknown"
    cost = finding.dollar_cost

    if kind == "runaway":
        message = (
            f"Runaway agent loop: {agent} retried {tool} {finding.count}× — "
            f"${cost:.2f} burned, no convergence"
        )
        level = "error"
        if finding.count >= settings.sentry_fatal_count or cost >= settings.sentry_fatal_cost:
            level = "fatal"
        fingerprint = ["runaway-loop", tool, run_id]
    elif kind == "cycle":
        path = " -> ".join(finding.evidence.cycle_path or finding.span_ids)
        message = (
            f"Execution cycle detected: {agent} looped through {finding.count} spans "
            f"({path}) — ${cost:.2f} burned"
        )
        level = "error"
        if finding.count >= settings.sentry_fatal_count or cost >= settings.sentry_fatal_cost:
            level = "fatal"
        fingerprint = ["execution-cycle", tool, run_id]
    else:  # side_effecting
        message = (
            f"Side-effecting redundancy: {agent} repeated write tool {tool} "
            f"{finding.count}× — un-cacheable, ${cost:.2f}"
        )
        level = "warning"
        fingerprint = ["side-effecting-redundancy", tool, run_id]

    return {
        "message": message,
        "level": level,
        "fingerprint": fingerprint,
        "tags": {
            "run_id": run_id,
            "agent": agent,
            "tool": tool,
            "finding_type": finding.type,
            "severity": finding.severity,
        },
        "context": {
            "finding_id": finding.finding_id,
            "count": finding.count,
            "dollar_cost": cost,
            "convergence": finding.evidence.convergence,
            "span_ids": finding.span_ids,
        },
    }


def _send(event: dict) -> str:
    """Fire to Sentry if real mode; else record to the mock sink. Returns mode."""
    if _REAL_MODE and sentry_sdk is not None:
        try:
            with sentry_sdk.push_scope() as scope:
                for k, v in event["tags"].items():
                    scope.set_tag(k, v)
                scope.set_context("redundant_finding", event["context"])
                scope.fingerprint = event["fingerprint"]
                scope.level = event["level"]
                sentry_sdk.capture_message(event["message"])
            return "real"
        except Exception:
            pass  # degrade to mock-record, never block the pipeline (SR-11)
    MOCK_EVENTS.append(event)
    return "mock"


def dispatch_alert(
    finding: Finding,
    span: Optional[Span] = None,
    run_id: str = "run-001",
    redis_client=None,
    settings: Settings = SETTINGS,
) -> dict:
    """Fire exactly one incident for an alert-routed finding (SR-2..SR-6, SR-11).

    Non-blocking: any failure degrades to mock mode and returns normally.
    """
    try:
        kind = _classify(finding, settings)
        event = _build_event(finding, span, run_id, kind, settings)
        # Dedup on the Sentry fingerprint (stable across re-analysis), not the
        # finding_id, which is regenerated on every analyze() pass. This matches
        # how real-mode Sentry collapses duplicates (SR-6).
        dedup_key = "|".join(str(p) for p in event["fingerprint"])
        if _already_fired(run_id, dedup_key, redis_client):
            return {"fired": False, "reason": "duplicate"}
        mode = _send(event)
        return {"fired": True, "mode": mode, "reason_kind": kind}
    except Exception as exc:  # pragma: no cover - last-resort guard (SR-11)
        return {"fired": False, "reason": f"error: {exc}"}
