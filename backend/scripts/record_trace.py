"""Record a complete run's events to a JSON trace for the replay fallback.

Usage:
    python scripts/record_trace.py [out.json]

The recorded trace can be reloaded so the UI/demo replays deterministically even
if sponsor APIs are unavailable.
"""

from __future__ import annotations

import json
import sys

from redundant.config import SETTINGS
from redundant.demo import run_demo_task
from redundant.memory_store import InMemoryStore
from redundant.report import build_report


def main(out_path: str = "trace.json") -> None:
    store = InMemoryStore(SETTINGS)
    run_id = "trace-run"
    run_demo_task(run_id, "redundant", store)
    events = store.read_events(run_id)
    report = build_report(run_id, events)
    trace = {
        "run_id": run_id,
        "events": [e.model_dump(mode="json") for e in events],
        "report": report.model_dump(mode="json"),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(trace, fh, indent=2)
    print(f"wrote {len(events)} events -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "trace.json")
