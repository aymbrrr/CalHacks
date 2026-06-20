#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demos.band.agents import AGENT_PROMPTS, AuditAgent, ReportAgent, ResearchAgent, VerifierAgent
from demos.band.fallback_band_room import FallbackBandRoom
from demos.band.redundant_runtime import RedundantRuntime
from demos.band.trace_writer import TraceWriter


TASK = "Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation."


KNOWN_FALLBACK_LIMITATIONS = [
    "Uses a local fallback BandRoom adapter because live Band credentials are not assumed in this repo.",
    "Uses deterministic scripted tools and scripted LLM responses instead of live Anthropic/tool calls.",
    "The Redundant runtime is a demo-compatible shim with the same wrapper payload shape, not Dev 1's final backend.",
    "Redis replay is supported by replay_trace.py, with dry-run fallback when redis-py or Redis is unavailable.",
]


def default_trace_path(mode: str) -> Path:
    filename = "band_demo_trace.json" if mode == "redundant" else "band_demo_baseline_trace.json"
    return Path(__file__).resolve().parent / "traces" / filename


def run_demo(*, mode: str, run_id: str, trace_out: Path, echo_room: bool) -> dict:
    writer = TraceWriter(run_id=run_id, mode=mode, task=TASK)
    runtime = RedundantRuntime(run_id=run_id, mode=mode, writer=writer)
    room = FallbackBandRoom(writer, echo=echo_room)

    print(f"Starting Band fallback room {room.room_id} in {mode} mode.")
    room_span_id = writer.start_agent_span("BandRoom", None, TASK)
    room.post("User", TASK, kind="task")

    ResearchAgent().run(room=room, runtime=runtime, parent_span_id=room_span_id, task=TASK)
    ReportAgent().run_overlap(room=room, runtime=runtime, parent_span_id=room_span_id, task=TASK)
    AuditAgent().run(room=room, runtime=runtime, parent_span_id=room_span_id)
    VerifierAgent().run(room=room, runtime=runtime, parent_span_id=room_span_id)
    ReportAgent().write_final(room=room, runtime=runtime, parent_span_id=room_span_id)

    writer.finish_agent_span(room_span_id, "Completed deterministic Band multi-agent collaboration.")

    report = runtime.build_report()
    duplicate_clusters = runtime.build_duplicate_clusters()
    trace = writer.build_trace(
        agent_prompts=AGENT_PROMPTS,
        report=report,
        duplicate_clusters=duplicate_clusters,
        known_fallback_limitations=KNOWN_FALLBACK_LIMITATIONS,
    )
    validation_errors = writer.validate()
    if validation_errors:
        for error in validation_errors:
            print(f"TRACE VALIDATION ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

    writer.write_trace(trace_out, trace)
    print("")
    print("Final savings report")
    print(f"- Attempted calls: {report['attempted_calls']}")
    print(f"- Executed calls: {report['executed_calls']}")
    print(f"- Reused or blocked calls: {report['reused_or_blocked_calls']}")
    print(f"- Estimated baseline cost: ${report['estimated_baseline_cost_usd']:.2f}")
    print(f"- Actual run cost: ${report['actual_cost_usd']:.2f}")
    print(f"- Saved/wasted cost: ${report['saved_cost_usd']:.2f}")
    print(f"- Waste rate: {report['waste_rate'] * 100:.1f}%")
    print(f"- Trace: {trace_out}")
    print("")
    if mode == "redundant":
        print("Required visible line:")
        print("ReportAgent reused ResearchAgent's prior result.")
    else:
        print("Redundant mode visible line:")
        print("ReportAgent reused ResearchAgent's prior result.")
    print("")
    print("Replay command:")
    print(f"python demos/band/replay_trace.py {trace_out} --run-id {run_id}")
    return trace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic Band multi-agent demo.")
    parser.add_argument("--mode", choices=["baseline", "redundant"], default="redundant")
    parser.add_argument("--run-id", default="run-001")
    parser.add_argument("--trace-out", type=Path, default=None)
    parser.add_argument("--quiet-room", action="store_true", help="Do not echo Band room messages to stdout.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trace_out = args.trace_out or default_trace_path(args.mode)
    run_demo(mode=args.mode, run_id=args.run_id, trace_out=trace_out, echo_room=not args.quiet_room)


if __name__ == "__main__":
    main()
