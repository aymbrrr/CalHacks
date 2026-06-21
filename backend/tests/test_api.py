import asyncio

import pytest
from fastapi.testclient import TestClient

from redundant import api
from redundant.memory_store import InMemoryStore


@pytest.fixture
def client(monkeypatch):
    # Force the in-memory store so the API e2e runs offline.
    store = InMemoryStore()
    monkeypatch.setattr(api, "_store", store)
    return TestClient(api.app)


def _wait_complete(client, run_id, timeout=10.0):
    import time

    start = time.time()
    while time.time() - start < timeout:
        report = client.get(f"/api/runs/{run_id}/report").json()
        # Demo emits a fixed number of calls; wait until the stream settles. Fetch
        # events only after the report shows completion — fetching them first would
        # snapshot a partial stream while the report (read a moment later) already
        # reflects more calls, leaving events < report (a helper-ordering race).
        if report["attempted_calls"] >= 12:
            return client.get(f"/api/runs/{run_id}/events").json(), report
        time.sleep(0.1)
    return client.get(f"/api/runs/{run_id}/events").json(), client.get(
        f"/api/runs/{run_id}/report"
    ).json()


def test_start_events_report_flow(client):
    resp = client.post("/api/runs/start", json={"task": "audit", "mode": "redundant"})
    assert resp.status_code == 200
    run = resp.json()
    assert run["mode"] == "redundant"
    run_id = run["run_id"]

    events, report = _wait_complete(client, run_id)
    assert len(events) >= 12
    # Contract fields present on each event.
    assert {"event_id", "run_id", "decision", "saved_cost_usd"} <= set(events[0].keys())
    assert report["attempted_calls"] == report["executed_calls"] + report["reused_or_blocked_calls"]
    assert report["reused_or_blocked_calls"] >= 3


def test_replay_reproduces_without_executing(client):
    run = client.post("/api/runs/start", json={"task": "audit", "mode": "redundant"}).json()
    run_id = run["run_id"]
    _wait_complete(client, run_id)

    replay = client.post(f"/api/runs/{run_id}/replay").json()
    assert replay["mode"] == "replay"
    new_id = replay["run_id"]

    import time

    time.sleep(1.5)
    replay_events = client.get(f"/api/runs/{new_id}/events").json()
    original_events = client.get(f"/api/runs/{run_id}/events").json()
    assert len(replay_events) == len(original_events)


def _wait_done(client, run_id, timeout=10.0):
    """Block until the run's status settles, so the span stream and the report are
    both fully written before we compare them."""
    import time

    start = time.time()
    while time.time() - start < timeout:
        runs = client.get("/api/runs").json()
        run = next((r for r in runs if r["run_id"] == run_id), None)
        if run and run["status"] in ("complete", "failed"):
            return run
        time.sleep(0.1)
    return None


def test_findings_reflect_the_real_run(client):
    """/findings?run_id must return spans from the run that just executed (read
    from trace:{run_id} via the store), not the bundled demo_trace.json fallback."""
    run = client.post("/api/runs/start", json={"task": "audit", "mode": "redundant"}).json()
    run_id = run["run_id"]
    assert _wait_done(client, run_id) is not None

    report = client.get(f"/api/runs/{run_id}/report").json()
    findings = client.get("/findings", params={"run_id": run_id}).json()
    spans = findings["spans"]
    call_spans = [s for s in spans if s["kind"] in ("llm", "tool")]

    # The real run's call-span count matches the events-derived report — the demo
    # fallback (8 call spans, agents researcher/analyst/reporter) would not.
    assert len(call_spans) == report["attempted_calls"]
    assert {s["agent_name"] for s in call_spans} <= {"research-agent", "report-agent"}

    # Agent root spans nest the calls (UI flamegraph).
    assert any(s["kind"] == "agent" for s in spans)

    # Non-executed calls stay at ~0 cost (reuse-cost guard in _stamp_cost), and the
    # demo deterministically produces some reuse/blocks.
    reuse = [s for s in call_spans if s["decision"] in
             ("EXACT_REUSE", "SEMANTIC_REUSE", "BLOCK_OR_WARN")]
    assert reuse
    assert all(s["cost_usd"] == 0 for s in reuse)
    assert findings["total_cost_usd"] > 0


def test_unknown_run_report_404(client):
    assert client.get("/api/runs/does-not-exist/report").status_code == 404
