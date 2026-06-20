from __future__ import annotations

from typing import Any

from .runtime import stable_hash, utc_now


VALID_FINAL_LABELS = {
    "safe_reuse",
    "not_equivalent",
    "needs_freshness_check",
    "state_specific",
    "side_effect_risk",
    "unclear",
}

SAFE_REUSE_LABELS = {"safe_reuse"}
CONDITIONAL_REUSE_LABELS = {"needs_freshness_check"}


def submit_label(store: Any, payload: dict[str, Any]) -> dict[str, Any]:
    answer, errors = normalize_label_answer(store, payload)
    if errors or answer is None:
        return {"accepted": False, "errors": errors, "answer": None}
    store.append_label_answer(answer)
    return {"accepted": True, "errors": [], "answer": answer}


def normalize_label_answer(store: Any, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    pair_id = str(payload.get("pair_id", "")).strip()
    known_pairs = {item.get("pair_id") for item in store.list_label_items()}
    if not pair_id:
        errors.append("pair_id is required")
    elif pair_id not in known_pairs:
        errors.append(f"pair_id {pair_id} is not in the labelable dataset")

    final_label = str(payload.get("final_label") or payload.get("label") or "").strip()
    if final_label not in VALID_FINAL_LABELS:
        errors.append(f"final_label must be one of {sorted(VALID_FINAL_LABELS)}")

    try:
        confidence = int(payload.get("confidence", 3))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 1 or confidence > 5:
        errors.append("confidence must be an integer from 1 to 5")

    reason = str(payload.get("short_reason", "")).strip()
    if not reason:
        errors.append("short_reason is required")
    reason = reason[:500]
    reviewer = str(payload.get("reviewer", "local-reviewer")).strip()[:80] or "local-reviewer"

    if errors:
        return None, errors

    created_at = utc_now()
    answer = {
        "answer_id": f"answer_{stable_hash({'pair_id': pair_id, 'label': final_label, 'confidence': confidence, 'reason': reason, 'created_at': created_at})}",
        "pair_id": pair_id,
        "final_label": final_label,
        "confidence": confidence,
        "short_reason": reason,
        "reviewer": reviewer,
        "source": payload.get("source", "local_annotation"),
        "created_at": created_at,
    }
    return answer, []


def annotation_queue(store: Any, limit: int | None = None) -> list[dict[str, Any]]:
    answers = store.labels_by_pair_id()
    items = []
    for item in store.list_label_items():
        if item.get("pair_id") in answers:
            continue
        items.append(with_review_metadata(item))
        if limit and len(items) >= limit:
            break
    return items


def with_review_metadata(item: dict[str, Any]) -> dict[str, Any]:
    review = dict(item)
    signals = item.get("runtime_signals", {})
    hint = item.get("label_hint", {})
    review["review_prompt"] = {
        "question": "Can the cached call safely replace the new call?",
        "choices": sorted(VALID_FINAL_LABELS),
        "label_hint": hint.get("likely_label", "unclear"),
        "redis_would_reuse": raw_redis_would_reuse(item),
        "redis_similarity": signals.get("redis_similarity"),
        "exact_key_match": bool(signals.get("exact_key_match")),
    }
    return review


def terac_export(store: Any, include_labeled: bool = False, limit: int | None = None) -> dict[str, Any]:
    answers = store.labels_by_pair_id()
    records = []
    for item in store.list_label_items():
        pair_id = item.get("pair_id")
        answer = answers.get(pair_id)
        if answer and not include_labeled:
            continue
        records.append(
            {
                "task_id": pair_id,
                "schema": "CacheReuseReviewItem/v1",
                "instruction": "Label whether the candidate cached call can safely satisfy the new call.",
                "choices": sorted(VALID_FINAL_LABELS),
                "new_call": item.get("new_call", {}),
                "candidate_cached_call": item.get("candidate_cached_call", {}),
                "runtime_signals": item.get("runtime_signals", {}),
                "label_hint": item.get("label_hint", {}),
                "existing_answer": answer,
            }
        )
        if limit and len(records) >= limit:
            break
    return {
        "export_schema": "TeracReuseLabelTask/v1",
        "created_at": utc_now(),
        "pure_llm_supported": True,
        "include_labeled": include_labeled,
        "count": len(records),
        "records": records,
    }


def evaluate_labels(store: Any, reuse_threshold: float = 0.72) -> dict[str, Any]:
    items = store.list_label_items()
    answers = store.labels_by_pair_id()
    label_distribution: dict[str, int] = {}
    call_kind_distribution: dict[str, int] = {}
    hint_agreements = 0
    raw_reuse_candidates = 0
    raw_unsafe_reuses = 0
    terac_allow = 0
    terac_refresh = 0
    terac_block = 0
    pure_llm_labeled = 0

    labeled_pairs = []
    for item in items:
        pair_id = item.get("pair_id")
        answer = answers.get(pair_id)
        if not answer:
            continue

        final_label = answer.get("final_label", "unclear")
        label_distribution[final_label] = label_distribution.get(final_label, 0) + 1

        call_kind = item.get("new_call", {}).get("call_kind", "unknown")
        call_kind_distribution[call_kind] = call_kind_distribution.get(call_kind, 0) + 1
        if call_kind == "llm":
            pure_llm_labeled += 1

        hint = item.get("label_hint", {}).get("likely_label")
        if hint == final_label:
            hint_agreements += 1

        raw_reuse = raw_redis_would_reuse(item, reuse_threshold)
        if raw_reuse:
            raw_reuse_candidates += 1
            if final_label not in SAFE_REUSE_LABELS:
                raw_unsafe_reuses += 1

        action = terac_policy_action(final_label)
        if action == "allow_reuse":
            terac_allow += 1
        elif action == "refresh_then_reuse":
            terac_refresh += 1
        else:
            terac_block += 1

        labeled_pairs.append(
            {
                "pair_id": pair_id,
                "call_kind": call_kind,
                "hint": hint,
                "final_label": final_label,
                "redis_would_reuse": raw_reuse,
                "terac_action": action,
            }
        )

    labeled_items = len(labeled_pairs)
    total_items = len(items)
    agreement_rate = round(hint_agreements / labeled_items, 3) if labeled_items else 0.0
    unsafe_rate = round(raw_unsafe_reuses / raw_reuse_candidates, 3) if raw_reuse_candidates else 0.0
    return {
        "total_items": total_items,
        "labeled_items": labeled_items,
        "unlabeled_items": max(0, total_items - labeled_items),
        "pure_llm_labeled_items": pure_llm_labeled,
        "hint_agreement_rate": agreement_rate,
        "label_distribution": label_distribution,
        "labeled_call_kind_distribution": call_kind_distribution,
        "raw_redis_policy": {
            "reuse_threshold": reuse_threshold,
            "reuse_candidates": raw_reuse_candidates,
            "unsafe_reuses": raw_unsafe_reuses,
            "unsafe_reuse_rate": unsafe_rate,
        },
        "terac_gated_policy": {
            "allow_reuse": terac_allow,
            "refresh_then_reuse": terac_refresh,
            "block_reuse": terac_block,
            "unsafe_reuses": 0,
        },
        "labeled_pairs": labeled_pairs[-20:],
    }


def raw_redis_would_reuse(item: dict[str, Any], reuse_threshold: float = 0.72) -> bool:
    signals = item.get("runtime_signals", {})
    if signals.get("exact_key_match") is True:
        return True
    similarity = signals.get("redis_similarity")
    return isinstance(similarity, (int, float)) and similarity >= reuse_threshold


def terac_policy_action(final_label: str) -> str:
    if final_label in SAFE_REUSE_LABELS:
        return "allow_reuse"
    if final_label in CONDITIONAL_REUSE_LABELS:
        return "refresh_then_reuse"
    return "block_reuse"
