"""Tests for the Sentry alert arm (docs/SENTRY_REQUIREMENTS.md)."""
import json

import pytest
from fastapi.testclient import TestClient

from redundant import api, sentry_dispatch
from redundant.config import Settings
from redundant.memory_store import InMemoryStore
from redundant.span_schema import Evidence, Finding, Span, TokenCost


# --- helpers ----------------------------------------------------------------

def make_finding(**over) -> Finding:
    base = dict(
        finding_id="f_1",
        type="repetition",
        span_ids=["s_0", "s_1"],
        representative_span_id="s_0",
        count=12,
        description="verify_source called 12x",
        token_cost=TokenCost(input=100, output=20),
        dollar_cost=0.30,
        severity="runaway",
        route="alert",
        cacheable=False,
        evidence=Evidence(convergence="none"),
    )
    base.update(over)
    return Finding(**base)


def make_span() -> Span:
    return Span(span_id="s_0", kind="tool", name="tool:verify_source",
                tool_name="verify_source", agent_name="fact_checker")


@pytest.fixture(autouse=True)
def _clean():
    """Mock mode + clean sink/idempotency for every test."""
    sentry_dispatch._REAL_MODE = False
    sentry_dispatch.reset()
    yield
    sentry_dispatch.reset()


# --- SR-1 / SR-9: init + mock fallback --------------------------------------

def test_init_no_dsn_is_mock_mode():
    assert sentry_dispatch.init_sentry(Settings(sentry_dsn="")) is False


# --- SR-2 / SR-3 / SR-5: runaway event content ------------------------------

def test_runaway_event_is_rich():
    ack = sentry_dispatch.dispatch_alert(make_finding(), make_span(), "run-001")
    assert ack == {"fired": True, "mode": "mock", "reason_kind": "runaway"}
    assert len(sentry_dispatch.MOCK_EVENTS) == 1
    ev = sentry_dispatch.MOCK_EVENTS[0]
    assert "Runaway agent loop" in ev["message"]
    assert ev["level"] == "error"
    assert ev["fingerprint"] == ["runaway-loop", "verify_source", "run-001"]
    assert ev["tags"] == {
        "run_id": "run-001", "agent": "fact_checker", "tool": "verify_source",
        "finding_type": "repetition", "severity": "runaway",
    }
    assert ev["context"]["finding_id"] == "f_1"
    assert ev["context"]["count"] == 12
    assert ev["context"]["convergence"] == "none"


def test_extreme_runaway_escalates_to_fatal():
    f = make_finding(count=25, dollar_cost=2.0)
    sentry_dispatch.dispatch_alert(f, make_span(), "run-001")
    assert sentry_dispatch.MOCK_EVENTS[0]["level"] == "fatal"


# --- SR-4: side-effecting redundancy is a distinct incident ------------------

def test_side_effecting_is_distinct():
    f = make_finding(count=3, severity="runaway", cacheable=False,
                     evidence=Evidence(convergence="converged"))
    span = Span(span_id="s_0", kind="tool", name="tool:send_email",
                tool_name="send_email", agent_name="writer")
    ack = sentry_dispatch.dispatch_alert(f, span, "run-001")
    assert ack["reason_kind"] == "side_effecting"
    ev = sentry_dispatch.MOCK_EVENTS[0]
    assert "Side-effecting redundancy" in ev["message"]
    assert ev["level"] == "warning"
    assert ev["fingerprint"][0] == "side-effecting-redundancy"


# --- SR-6: idempotency ------------------------------------------------------

def test_idempotent_in_process():
    f = make_finding()
    first = sentry_dispatch.dispatch_alert(f, make_span(), "run-001")
    second = sentry_dispatch.dispatch_alert(f, make_span(), "run-001")
    assert first["fired"] is True
    assert second == {"fired": False, "reason": "duplicate"}
    assert len(sentry_dispatch.MOCK_EVENTS) == 1


def test_idempotent_via_redis():
    class FakeRedis:
        def __init__(self):
            self._sets = {}

        def sadd(self, key, member):
            s = self._sets.setdefault(key, set())
            if member in s:
                return 0
            s.add(member)
            return 1

        def expire(self, key, ttl):
            return True

    r = FakeRedis()
    f = make_finding()
    a = sentry_dispatch.dispatch_alert(f, make_span(), "run-001", redis_client=r)
    b = sentry_dispatch.dispatch_alert(f, make_span(), "run-001", redis_client=r)
    assert a["fired"] is True and b["fired"] is False
    assert len(sentry_dispatch.MOCK_EVENTS) == 1


# --- SR-11: never raises into the pipeline ----------------------------------

def test_non_blocking_on_send_failure(monkeypatch):
    def boom(_event):
        raise RuntimeError("sentry down")

    monkeypatch.setattr(sentry_dispatch, "_send", boom)
    ack = sentry_dispatch.dispatch_alert(make_finding(), make_span(), "run-001")
    assert ack["fired"] is False
    assert ack["reason"].startswith("error:")


# --- E2E: /findings fires and sets alert_fired ------------------------------

def test_findings_endpoint_fires_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_store", InMemoryStore())
    sentry_dispatch._REAL_MODE = False
    sentry_dispatch.reset()

    # 12× verify_source loop (not in the read-only allowlist → runaway alert).
    spans = [
        {
            "span_id": f"s_{i}", "kind": "tool", "name": "tool:verify_source",
            "tool_name": "verify_source", "agent_name": "fact_checker",
            "input": "claim x", "output": "still checking", "input_hash": "loop01",
            "tokens": {"input": 200, "output": 40}, "model": "claude-haiku-4-5",
        }
        for i in range(12)
    ]
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps(spans), encoding="utf-8")

    client = TestClient(api.app)
    body = client.get("/findings", params={"json_path": str(trace)}).json()

    assert body["alerts_fired"] >= 1
    runaways = [f for f in body["findings"] if f["route"] == "alert"]
    assert runaways and all(f["alert_fired"] for f in runaways)

    alerts = client.get("/alerts").json()
    assert alerts["mock"] is True
    assert any("Runaway agent loop" in e["message"] for e in alerts["events"])
