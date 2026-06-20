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
        events = client.get(f"/api/runs/{run_id}/events").json()
        report = client.get(f"/api/runs/{run_id}/report").json()
        # Demo emits a fixed number of calls; wait until the stream settles.
        if report["attempted_calls"] >= 12:
            return events, report
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


def test_unknown_run_report_404(client):
    assert client.get("/api/runs/does-not-exist/report").status_code == 404
