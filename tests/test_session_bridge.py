import json
import tempfile
import unittest
from pathlib import Path

from redundant_app.session_bridge import bridge_once


def llm_item(pair_id: str = "bridge_llm_001"):
    return {
        "pair_id": pair_id,
        "trace_id": "bridge_trace_test",
        "created_at": "2026-06-20T21:45:00Z",
        "task_context": "Coding-session bridge smoke test.",
        "new_call": {
            "agent_id": "codex",
            "call_kind": "llm",
            "tool_name": "none",
            "prompt_or_args": {
                "visible_task_summary": "Explain how Redundant watches coding-session label data."
            },
            "requested_at": None,
        },
        "candidate_cached_call": {
            "agent_id": "codex",
            "call_kind": "llm",
            "tool_name": "none",
            "prompt_or_args": {
                "visible_task_summary": "Explain how Redundant imports label data from the inbox."
            },
            "output_summary": "Earlier answer described the local label inbox and import workflow.",
            "cached_at": None,
        },
        "runtime_signals": {
            "redis_similarity": 0.81,
            "exact_key_match": False,
            "cache_age_seconds": None,
            "tool_has_side_effects": False,
            "contains_user_state": False,
            "proposed_ttl_seconds": None,
        },
        "label_hint": {
            "likely_label": "safe_reuse",
            "why_labelable": "Both visible turns ask about the same local session-bridge workflow.",
        },
        "privacy": {
            "redaction_applied": False,
            "notes": "Visible prompt/output summaries only.",
        },
    }


class SessionBridgeTests(unittest.TestCase):
    def test_bridge_imports_inbox_and_reports_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "redundant-label-inbox.md"
            inbox.write_text("REDUNDANT_LABEL_DATA\n```json\n" + json.dumps([llm_item()]) + "\n```\n", encoding="utf-8")

            snapshot = bridge_once(data_dir=tmp, inbox_path=inbox)

            self.assertEqual(snapshot["import"]["ingest"]["accepted"], 1)
            self.assertEqual(snapshot["delta"]["total_items"], 1)
            self.assertEqual(snapshot["delta"]["pure_llm_items"], 1)
            self.assertEqual(snapshot["stats"]["total_items"], 1)
            self.assertEqual(snapshot["stats"]["pure_llm_items"], 1)
            self.assertEqual(snapshot["eval"]["unlabeled_items"], 1)
            self.assertEqual(inbox.read_text(encoding="utf-8"), "")
            self.assertTrue(Path(snapshot["import"]["archived_path"]).exists())

    def test_bridge_empty_inbox_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = bridge_once(data_dir=tmp)

            self.assertEqual(snapshot["import"]["ingest"]["accepted"], 0)
            self.assertEqual(snapshot["delta"]["total_items"], 0)
            self.assertEqual(snapshot["stats"]["total_items"], 0)


if __name__ == "__main__":
    unittest.main()
