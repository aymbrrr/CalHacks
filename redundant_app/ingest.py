from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime import safe_payload, stable_hash, utc_now


VALID_CALL_KINDS = {"llm", "tool", "browser", "repo", "api"}
VALID_LABEL_HINTS = {
    "safe_reuse",
    "not_equivalent",
    "needs_freshness_check",
    "state_specific",
    "side_effect_risk",
    "unclear",
}


@dataclass
class IngestResult:
    accepted: int
    duplicates: int
    rejected: int
    errors: list[str]
    items: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "errors": self.errors,
            "items": self.items,
        }


@dataclass
class InboxIngestResult:
    inbox_path: str
    archived_path: str | None
    ingest: IngestResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "inbox_path": self.inbox_path,
            "archived_path": self.archived_path,
            "ingest": self.ingest.as_dict(),
        }


def parse_label_data(text: str) -> list[dict[str, Any]]:
    """Extract REDUNDANT_LABEL_DATA JSON from markdown or accept a raw JSON array."""
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array.")
        return parsed

    section_match = re.search(r"REDUNDANT_LABEL_DATA(?P<section>.*)", stripped, flags=re.IGNORECASE | re.DOTALL)
    search_area = section_match.group("section") if section_match else stripped
    fence_match = re.search(r"```(?:json)?\s*(?P<json>.*?)\s*```", search_area, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        parsed = json.loads(fence_match.group("json"))
        if not isinstance(parsed, list):
            raise ValueError("Expected fenced REDUNDANT_LABEL_DATA to be a JSON array.")
        return parsed

    raise ValueError("Could not find a JSON array or fenced REDUNDANT_LABEL_DATA block.")


def default_inbox_path(data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / "redundant-label-inbox.md"


def normalize_label_item(item: dict[str, Any], index: int = 0) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return None, [f"item {index}: expected object"]

    normalized = dict(item)
    normalized.setdefault("pair_id", f"imported_{stable_hash(item)}")
    normalized.setdefault("trace_id", "manual_import")
    normalized.setdefault("created_at", utc_now())
    normalized.setdefault("task_context", "Imported REDUNDANT_LABEL_DATA item.")

    for side in ("new_call", "candidate_cached_call"):
        call = normalized.get(side)
        if not isinstance(call, dict):
            errors.append(f"item {index}: missing {side}")
            continue
        kind = call.get("call_kind")
        if kind not in VALID_CALL_KINDS:
            errors.append(f"item {index}: {side}.call_kind must be one of {sorted(VALID_CALL_KINDS)}")
        call.setdefault("agent_id", "unknown-agent")
        call.setdefault("tool_name", "none" if kind == "llm" else "unknown")
        call.setdefault("prompt_or_args", {})
        safe_args, redacted_args = safe_payload(call["prompt_or_args"])
        call["prompt_or_args"] = safe_args
        if side == "new_call":
            call.setdefault("requested_at", None)
        else:
            call.setdefault("cached_at", None)
            call.setdefault("output_summary", "Imported output summary unavailable.")
        normalized[side] = call
        if redacted_args:
            normalized.setdefault("privacy", {})["redaction_applied"] = True

    runtime = normalized.setdefault("runtime_signals", {})
    if not isinstance(runtime, dict):
        errors.append(f"item {index}: runtime_signals must be an object")
    else:
        runtime.setdefault("redis_similarity", None)
        runtime.setdefault("exact_key_match", None)
        runtime.setdefault("cache_age_seconds", None)
        runtime.setdefault("tool_has_side_effects", False)
        runtime.setdefault("contains_user_state", False)
        runtime.setdefault("proposed_ttl_seconds", None)

    label_hint = normalized.setdefault("label_hint", {})
    if not isinstance(label_hint, dict):
        errors.append(f"item {index}: label_hint must be an object")
    else:
        likely_label = label_hint.get("likely_label", "unclear")
        if likely_label not in VALID_LABEL_HINTS:
            errors.append(f"item {index}: label_hint.likely_label must be one of {sorted(VALID_LABEL_HINTS)}")
        label_hint.setdefault("likely_label", likely_label)
        label_hint.setdefault("why_labelable", "Imported item needs human review.")

    privacy = normalized.setdefault("privacy", {})
    if not isinstance(privacy, dict):
        errors.append(f"item {index}: privacy must be an object")
    else:
        privacy.setdefault("redaction_applied", False)
        privacy.setdefault("notes", "Imported item; visible prompt/output summaries only.")

    normalized["imported_at"] = utc_now()
    normalized["source"] = normalized.get("source", "manual_ingest")
    return (None if errors else normalized), errors


def validate_and_normalize_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(items):
        normalized, item_errors = normalize_label_item(item, index)
        if item_errors:
            errors.extend(item_errors)
        elif normalized:
            accepted.append(normalized)
    return accepted, errors


def ingest_text(store: Any, text: str) -> IngestResult:
    try:
        parsed = parse_label_data(text)
    except Exception as exc:  # noqa: BLE001 - user-facing parse error
        return IngestResult(accepted=0, duplicates=0, rejected=1, errors=[str(exc)], items=[])

    normalized, errors = validate_and_normalize_items(parsed)
    accepted = 0
    duplicates = 0
    imported: list[dict[str, Any]] = []
    for item in normalized:
        if store.append_label_item(item):
            accepted += 1
            imported.append(item)
        else:
            duplicates += 1
    return IngestResult(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
        items=imported,
    )


def ingest_inbox(store: Any, inbox_path: str | Path | None = None, keep: bool = False) -> InboxIngestResult:
    path = Path(inbox_path) if inbox_path else default_inbox_path(store.data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    result = ingest_text(store, text)
    archived_path: str | None = None
    if text.strip() and not keep and (result.accepted or result.duplicates):
        archive_dir = path.parent / "inbox-archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{path.stem}-{utc_now().replace(':', '').replace('-', '')}.md"
        archive_path.write_text(text, encoding="utf-8")
        path.write_text("", encoding="utf-8")
        archived_path = str(archive_path)
    return InboxIngestResult(inbox_path=str(path), archived_path=archived_path, ingest=result)
