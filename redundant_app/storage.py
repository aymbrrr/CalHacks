from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime import utc_now


class JsonlStore:
    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.label_data_path = self.data_dir / "labelable-review-items.jsonl"
        self.label_answers_path = self.data_dir / "terac-labels.jsonl"
        self.runs_path = self.data_dir / "runs.jsonl"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._event_counters: dict[str, int] = {}
        self._label_ids = self._load_label_ids()

    def start_run(self, task: str, mode: str, run_id: str) -> dict[str, Any]:
        run = {
            "run_id": run_id,
            "task": task,
            "mode": mode,
            "status": "running",
            "started_at": utc_now(),
        }
        self._append_jsonl(self.runs_path, run)
        return run

    def complete_run(self, run_id: str) -> None:
        self._append_jsonl(self.runs_path, {"run_id": run_id, "status": "complete", "completed_at": utc_now()})

    def next_event_id(self, run_id: str) -> str:
        current = self._event_counters.get(run_id, 0) + 1
        self._event_counters[run_id] = current
        return f"{run_id}-{current:04d}"

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._append_jsonl(self._events_path(run_id), event)

    def append_call(self, run_id: str, call: dict[str, Any]) -> None:
        self._append_jsonl(self._calls_path(run_id), call)

    def append_label_item(self, item: dict[str, Any]) -> bool:
        pair_id = item["pair_id"]
        if pair_id in self._label_ids:
            return False
        self._label_ids.add(pair_id)
        self._append_jsonl(self.label_data_path, item)
        return True

    def append_label_answer(self, answer: dict[str, Any]) -> None:
        self._append_jsonl(self.label_answers_path, answer)

    def save_report(self, run_id: str, report: dict[str, Any]) -> None:
        self._report_path(run_id).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def list_events(self, run_id: str, after: str | None = None) -> list[dict[str, Any]]:
        events = self._read_jsonl(self._events_path(run_id))
        if after:
            events = [event for event in events if event.get("event_id", "") > after]
        return events

    def get_report(self, run_id: str) -> dict[str, Any]:
        path = self._report_path(run_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"run_id": run_id, "status": "missing"}

    def list_label_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        items = self._read_jsonl(self.label_data_path)
        return items[-limit:] if limit else items

    def list_label_answers(self, pair_id: str | None = None) -> list[dict[str, Any]]:
        answers = self._read_jsonl(self.label_answers_path)
        if pair_id:
            answers = [answer for answer in answers if answer.get("pair_id") == pair_id]
        return answers

    def labels_by_pair_id(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for answer in self.list_label_answers():
            pair_id = answer.get("pair_id")
            if pair_id:
                latest[pair_id] = answer
        return latest

    def annotation_queue(self, limit: int | None = None) -> list[dict[str, Any]]:
        answers = self.labels_by_pair_id()
        items = [item for item in self.list_label_items() if item.get("pair_id") not in answers]
        return items[:limit] if limit else items

    def dataset_stats(self) -> dict[str, Any]:
        items = self.list_label_items()
        answers = self.labels_by_pair_id()
        labels: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        pure_llm_labeled = 0
        for item in items:
            label = item.get("label_hint", {}).get("likely_label", "unknown")
            kind = item.get("new_call", {}).get("call_kind", "unknown")
            labels[label] = labels.get(label, 0) + 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if kind == "llm" and item.get("pair_id") in answers:
                pure_llm_labeled += 1
        pure_llm = by_kind.get("llm", 0)
        labeled_items = sum(1 for item in items if item.get("pair_id") in answers)
        coverage_ok = len(items) > 0 and pure_llm > 0
        return {
            "path": str(self.label_data_path),
            "label_answers_path": str(self.label_answers_path),
            "total_items": len(items),
            "labeled_items": labeled_items,
            "unlabeled_items": max(0, len(items) - labeled_items),
            "by_label_hint": labels,
            "by_call_kind": by_kind,
            "pure_llm_items": pure_llm,
            "pure_llm_labeled_items": pure_llm_labeled,
            "dataset_health": "collecting" if coverage_ok else "needs_llm_examples",
        }

    def _events_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.events.jsonl"

    def _calls_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.calls.jsonl"

    def _report_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.report.json"

    def _append_jsonl(self, path: Path, item: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

    def _load_label_ids(self) -> set[str]:
        if not self.label_data_path.exists():
            return set()
        return {item["pair_id"] for item in self._read_jsonl(self.label_data_path) if "pair_id" in item}
