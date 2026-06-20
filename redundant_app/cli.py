from __future__ import annotations

import argparse
import json
import sys

from .claude_hooks import handle_hook_stdin
from .demo import DEFAULT_TASK, export_sample, run_demo
from .ingest import default_inbox_path, ingest_inbox, ingest_text
from .labels import VALID_FINAL_LABELS, evaluate_labels, submit_label, terac_export
from .server import serve
from .session_bridge import watch_sessions
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

    inbox = sub.add_parser("ingest-inbox", help="Import REDUNDANT_LABEL_DATA from the local always-on inbox")
    inbox.add_argument("--data-dir", default="data")
    inbox.add_argument("--inbox", default="", help="Inbox markdown file; defaults to data/redundant-label-inbox.md")
    inbox.add_argument("--keep", action="store_true", help="Leave inbox content in place after import")

    watch = sub.add_parser("watch-sessions", help="Poll the local coding-session label inbox and report dataset health")
    watch.add_argument("--data-dir", default="data")
    watch.add_argument("--inbox", default="", help="Inbox markdown file; defaults to data/redundant-label-inbox.md")
    watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox checks")
    watch.add_argument("--once", action="store_true", help="Run one check and exit")
    watch.add_argument("--keep", action="store_true", help="Leave imported inbox content in place")
    watch.add_argument("--json", action="store_true", help="Print full JSON snapshots")

    claude_hook = sub.add_parser("claude-hook", help="Capture a Claude Code hook event for Redundant")
    claude_hook.add_argument("--data-dir", default="data")
    claude_hook.add_argument("--context", action="store_true", help="Return Claude additionalContext when a reuse candidate is found")
    claude_hook.add_argument("--similarity-threshold", type=float, default=0.56)

    label = sub.add_parser("label-item", help="Add a local Terac-style label answer for one review item")
    label.add_argument("--data-dir", default="data")
    label.add_argument("--pair-id", required=True)
    label.add_argument("--final-label", required=True, choices=sorted(VALID_FINAL_LABELS))
    label.add_argument("--confidence", type=int, default=3)
    label.add_argument("--reason", required=True)
    label.add_argument("--reviewer", default="local-reviewer")

    eval_cmd = sub.add_parser("eval", help="Evaluate Redis reuse against local label answers")
    eval_cmd.add_argument("--data-dir", default="data")

    export = sub.add_parser("export-terac", help="Export unlabeled review items in a Terac task shape")
    export.add_argument("--data-dir", default="data")
    export.add_argument("--include-labeled", action="store_true")
    export.add_argument("--limit", type=int, default=None)

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
    elif args.command == "ingest-inbox":
        store = JsonlStore(args.data_dir)
        inbox_path = args.inbox or default_inbox_path(args.data_dir)
        result = ingest_inbox(store, inbox_path=inbox_path, keep=args.keep)
        print(json.dumps({"inbox": result.as_dict(), "stats": store.dataset_stats()}, indent=2, sort_keys=True))
    elif args.command == "watch-sessions":
        inbox_path = args.inbox or default_inbox_path(args.data_dir)
        watch_sessions(
            data_dir=args.data_dir,
            inbox_path=inbox_path,
            interval_seconds=args.interval,
            cycles=1 if args.once else None,
            keep=args.keep,
            as_json=args.json,
        )
    elif args.command == "claude-hook":
        hook_args = ["--data-dir", args.data_dir, "--similarity-threshold", str(args.similarity_threshold)]
        if args.context:
            hook_args.append("--context")
        raise SystemExit(handle_hook_stdin(hook_args))
    elif args.command == "label-item":
        store = JsonlStore(args.data_dir)
        result = submit_label(
            store,
            {
                "pair_id": args.pair_id,
                "final_label": args.final_label,
                "confidence": args.confidence,
                "short_reason": args.reason,
                "reviewer": args.reviewer,
                "source": "cli",
            },
        )
        print(json.dumps({"label": result, "stats": store.dataset_stats(), "eval": evaluate_labels(store)}, indent=2, sort_keys=True))
        if not result["accepted"]:
            raise SystemExit(2)
    elif args.command == "eval":
        print(json.dumps(evaluate_labels(JsonlStore(args.data_dir)), indent=2, sort_keys=True))
    elif args.command == "export-terac":
        store = JsonlStore(args.data_dir)
        print(json.dumps(terac_export(store, include_labeled=args.include_labeled, limit=args.limit), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
