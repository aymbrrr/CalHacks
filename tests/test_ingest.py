import json
import tempfile
import unittest
from pathlib import Path

from redundant_app.ingest import ingest_text, parse_label_data
from redundant_app.storage import JsonlStore


def llm_item(pair_id="manual_llm_001"):
    return {
        "pair_id": pair_id,
        "trace_id": "manual_trace_test",
        "created_at": "2026-06-20T21:30:00Z",
        "task_context": "Manual pure LLM turn collection.",
        "new_call": {
            "agent_id": "codex",
            "call_kind": "llm",
            "tool_name": "none",
            "prompt_or_args": {
                "visible_task_summary": "Explain why pure LLM turns should be labelable."
            },
            "requested_at": None,
        },
        "candidate_cached_call": {
            "agent_id": "codex",
            "call_kind": "llm",
            "tool_name": "none",
            "prompt_or_args": {
                "visible_task_summary": "Explain whether label data is being generated."
            },
            "output_summary": "Earlier visible answer explained the current collection behavior.",
            "cached_at": None,
        },
        "runtime_signals": {
            "redis_similarity": None,
            "exact_key_match": False,
            "cache_age_seconds": None,
            "tool_has_side_effects": False,
            "contains_user_state": False,
            "proposed_ttl_seconds": None,
        },
        "label_hint": {
            "likely_label": "not_equivalent",
            "why_labelable": "Related cache-policy discussion but materially different request.",
        },
        "privacy": {
            "redaction_applied": False,
            "notes": "Visible prompt/output summaries only.",
        },
    }


class IngestTests(unittest.TestCase):
    def test_parse_markdown_redundant_label_data_block(self):
        payload = [llm_item()]
        markdown = "normal answer\n\nREDUNDANT_LABEL_DATA\n```json\n" + json.dumps(payload) + "\n```"

        parsed = parse_label_data(markdown)

        self.assertEqual(parsed[0]["pair_id"], "manual_llm_001")

    def test_ingest_accepts_pure_llm_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            text = json.dumps([llm_item()])

            first = ingest_text(store, text)
            second = ingest_text(store, text)
            stats = store.dataset_stats()

            self.assertEqual(first.accepted, 1)
            self.assertEqual(second.duplicates, 1)
            self.assertEqual(stats["total_items"], 1)
            self.assertEqual(stats["pure_llm_items"], 1)
            self.assertEqual(stats["dataset_health"], "collecting")

    def test_ingest_rejects_invalid_call_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            item = llm_item()
            item["new_call"]["call_kind"] = "hidden_reasoning"

            result = ingest_text(store, json.dumps([item]))

            self.assertEqual(result.accepted, 0)
            self.assertEqual(result.rejected, 1)
            self.assertIn("call_kind", result.errors[0])

    def test_ingest_redacts_sensitive_prompt_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            item = llm_item("manual_secret_001")
            item["new_call"]["prompt_or_args"]["api_key"] = "sk-test-123456789abcdef"

            result = ingest_text(store, json.dumps([item]))
            stored = store.list_label_items()[0]

            self.assertEqual(result.accepted, 1)
            self.assertEqual(stored["new_call"]["prompt_or_args"]["api_key"], "[REDACTED]")
            self.assertTrue(stored["privacy"]["redaction_applied"])


if __name__ == "__main__":
    unittest.main()
