from __future__ import annotations

import argparse
import json
import sys

from .demo import DEFAULT_TASK, export_sample, run_demo
from .ingest import ingest_text
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

    ingest = sub.add_parser("ingest-label-data", help="Import REDUNDANT_LABEL_DATA markdown or JSON")
    ingest.add_argument("--data-dir", default="data")
    ingest.add_argument("--file", default="-", help="File to import, or '-' for stdin")

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
    elif args.command == "ingest-label-data":
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        store = JsonlStore(args.data_dir)
        result = ingest_text(store, text)
        print(json.dumps({"ingest": result.as_dict(), "stats": store.dataset_stats()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
