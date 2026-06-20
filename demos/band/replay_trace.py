#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_trace(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replay_dry_run(trace: dict[str, Any], *, run_id: str, stream_key: str, include_events: bool) -> None:
    for span in trace["spans"]:
        payload = dict(span)
        payload["run_id"] = run_id
        print(f"DRY-RUN XADD {stream_key} data '{json.dumps(payload, sort_keys=True)}'")
    if include_events:
        event_key = f"events:{run_id}"
        for event in trace.get("events", []):
            payload = dict(event)
            payload["run_id"] = run_id
            print(f"DRY-RUN XADD {event_key} data '{json.dumps(payload, sort_keys=True)}'")


def replay_redis(
    trace: dict[str, Any],
    *,
    run_id: str,
    redis_url: str,
    stream_key: str,
    include_events: bool,
    pace: bool,
) -> None:
    try:
        import redis
    except ImportError:
        print("redis-py is not installed; falling back to dry-run replay.", file=sys.stderr)
        replay_dry_run(trace, run_id=run_id, stream_key=stream_key, include_events=include_events)
        return

    client = redis.from_url(redis_url)
    previous_start = None
    for span in trace["spans"]:
        if pace and previous_start is not None:
            delay_ms = max(0, min(500, span["start_time"] - previous_start))
            time.sleep(delay_ms / 1000)
        previous_start = span["start_time"]
        payload = dict(span)
        payload["run_id"] = run_id
        client.xadd(stream_key, {"data": json.dumps(payload, sort_keys=True)})
        print(f"XADD {stream_key} {span['span_id']}")

    if include_events:
        event_key = f"events:{run_id}"
        for event in trace.get("events", []):
            payload = dict(event)
            payload["run_id"] = run_id
            client.xadd(event_key, {"data": json.dumps(payload, sort_keys=True)})
            print(f"XADD {event_key} {event['event_id']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a frozen Band demo trace into Redis Streams.")
    parser.add_argument("trace_path", type=Path)
    parser.add_argument("--run-id", default=None, help="Replay as this run id. Defaults to the trace run id.")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--dry-run", action="store_true", help="Print XADD commands without connecting to Redis.")
    parser.add_argument("--include-events", action="store_true", help="Also replay decision events to events:{run_id}.")
    parser.add_argument("--pace", action="store_true", help="Preserve relative timing gaps, capped at 500 ms.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trace = load_trace(args.trace_path)
    run_id = args.run_id or trace["run"]["run_id"]
    stream_key = f"trace:{run_id}"

    if args.dry_run:
        replay_dry_run(trace, run_id=run_id, stream_key=stream_key, include_events=args.include_events)
        return

    try:
        replay_redis(
            trace,
            run_id=run_id,
            redis_url=args.redis_url,
            stream_key=stream_key,
            include_events=args.include_events,
            pace=args.pace,
        )
    except Exception as exc:
        print(f"Redis replay failed ({exc}); falling back to dry-run replay.", file=sys.stderr)
        replay_dry_run(trace, run_id=run_id, stream_key=stream_key, include_events=args.include_events)


if __name__ == "__main__":
    main()

