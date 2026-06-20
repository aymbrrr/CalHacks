from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .ingest import default_inbox_path, ingest_inbox
from .labels import evaluate_labels
from .storage import JsonlStore


def bridge_once(data_dir: str | Path = "data", inbox_path: str | Path | None = None, keep: bool = False) -> dict[str, Any]:
    store = JsonlStore(data_dir)
    path = Path(inbox_path) if inbox_path else default_inbox_path(data_dir)
    before = store.dataset_stats()
    inbox_bytes = path.stat().st_size if path.exists() else 0
    result = ingest_inbox(store, inbox_path=path, keep=keep)
    after = store.dataset_stats()
    evaluation = evaluate_labels(store)
    return {
        "inbox_path": str(path),
        "inbox_bytes_before": inbox_bytes,
        "import": result.as_dict(),
        "delta": {
            "total_items": after["total_items"] - before["total_items"],
            "pure_llm_items": after["pure_llm_items"] - before["pure_llm_items"],
            "labeled_items": after["labeled_items"] - before["labeled_items"],
        },
        "stats": after,
        "eval": {
            "labeled_items": evaluation["labeled_items"],
            "unlabeled_items": evaluation["unlabeled_items"],
            "pure_llm_labeled_items": evaluation["pure_llm_labeled_items"],
            "raw_unsafe_reuses": evaluation["raw_redis_policy"]["unsafe_reuses"],
            "raw_reuse_candidates": evaluation["raw_redis_policy"]["reuse_candidates"],
            "terac_blocks": evaluation["terac_gated_policy"]["block_reuse"],
        },
    }


def print_bridge_snapshot(snapshot: dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return

    ingest = snapshot["import"]["ingest"]
    stats = snapshot["stats"]
    eval_stats = snapshot["eval"]
    print(
        "Redundant bridge | "
        f"inbox={snapshot['inbox_bytes_before']} bytes | "
        f"accepted={ingest['accepted']} duplicates={ingest['duplicates']} rejected={ingest['rejected']} | "
        f"items={stats['total_items']} pure_llm={stats['pure_llm_items']} "
        f"labeled={stats['labeled_items']} unlabeled={stats['unlabeled_items']} | "
        f"raw_unsafe={eval_stats['raw_unsafe_reuses']}/{eval_stats['raw_reuse_candidates']} "
        f"terac_blocks={eval_stats['terac_blocks']}"
    )
    archived_path = snapshot["import"].get("archived_path")
    if archived_path:
        print(f"Archived imported inbox to {archived_path}")
    for error in ingest.get("errors", [])[:3]:
        print(f"Inbox error: {error}")


def watch_sessions(
    data_dir: str | Path = "data",
    inbox_path: str | Path | None = None,
    interval_seconds: float = 30.0,
    cycles: int | None = None,
    keep: bool = False,
    as_json: bool = False,
) -> None:
    count = 0
    while True:
        snapshot = bridge_once(data_dir=data_dir, inbox_path=inbox_path, keep=keep)
        print_bridge_snapshot(snapshot, as_json=as_json)
        count += 1
        if cycles is not None and count >= cycles:
            return
        time.sleep(interval_seconds)
