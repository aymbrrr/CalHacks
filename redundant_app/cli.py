from __future__ import annotations

import argparse
import json

from .demo import DEFAULT_TASK, export_sample, run_demo
from .server import serve
from .storage import JsonlStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Redundant demo")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-demo", help="Run the scripted multi-agent demo and generate labelable data")
    run.add_argument("--task", default=DEFAULT_TASK)
    run.add_argument("--mode", default="redundant", choices=["baseline", "redundant", "replay"])
    run.add_argument("--data-dir", default="data")
    run.add_argument("--sample-out", default="")

    server = sub.add_parser("serve", help="Start the local HTTP demo")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", default=8765, type=int)
    server.add_argument("--data-dir", default="data")

    stats = sub.add_parser("dataset-stats", help="Print labelable dataset stats")
    stats.add_argument("--data-dir", default="data")

    args = parser.parse_args()
    if args.command == "run-demo":
        store = JsonlStore(args.data_dir)
        report = run_demo(args.task, args.mode, store)
        if args.sample_out:
            export_sample(store, args.sample_out)
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.command == "serve":
        serve(args.host, args.port, args.data_dir)
    elif args.command == "dataset-stats":
        print(json.dumps(JsonlStore(args.data_dir).dataset_stats(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
