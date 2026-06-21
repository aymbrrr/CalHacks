"""Thin HTTP client that pushes Band trace data into the Redundant backend API.

Set REDUNDANT_API_URL (default: http://localhost:8000) to point at the backend.
All calls are fire-and-forget: failures are printed but never raised, so the
Band demo continues even if the backend is not running.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

REDUNDANT_API_URL = os.getenv("REDUNDANT_API_URL", "http://localhost:8000")


def _post(path: str, body: Any) -> dict | None:
    url = f"{REDUNDANT_API_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        print(f"[redundant_client] POST {path} failed: {exc}")
        return None


def _get(path: str) -> dict | None:
    url = f"{REDUNDANT_API_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        print(f"[redundant_client] GET {path} failed: {exc}")
        return None


def register_run(run_id: str, task: str, mode: str) -> dict | None:
    """POST /api/runs/start — register this Band run with the Redundant backend."""
    return _post("/api/runs/start", {"task": task, "mode": mode})


def ingest_trace_file(trace_path: Path) -> dict | None:
    """GET /findings?json_path=... — ask the backend to analyze the written trace file."""
    return _get(f"/findings?json_path={trace_path}")


def push_event(run_id: str, event: dict[str, Any]) -> None:
    """POST /api/runs/{run_id}/events/ingest — send a single event (if the backend supports it).

    The current backend does not expose a per-event ingest endpoint; this is a
    no-op placeholder.  Wire it up when the backend adds POST /api/runs/{run_id}/ingest.
    """
    pass
