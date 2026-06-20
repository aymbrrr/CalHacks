import tempfile
import unittest
from pathlib import Path

from redundant_app.demo import run_demo
from redundant_app.storage import JsonlStore


class RuntimeDatasetTests(unittest.TestCase):
    def test_demo_generates_labelable_dataset_with_pure_llm_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            report = run_demo(store=store)
            stats = store.dataset_stats()

            self.assertGreaterEqual(report["attempted_calls"], 10)
            self.assertGreater(stats["total_items"], 0)
            self.assertGreater(stats["by_call_kind"].get("llm", 0), 0)
            self.assertGreater(report["dataset"]["pure_llm_items_generated"], 0)
            self.assertTrue(store.label_data_path.exists())

    def test_dataset_items_do_not_expose_internal_prompt_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            run_demo(store=store)
            blob = store.label_data_path.read_text(encoding="utf-8").lower()

            self.assertNotIn("chain-of-thought", blob)
            self.assertNotIn("developer prompt", blob)
            self.assertIn("visible_task_summary", blob)

    def test_periodic_dataset_check_events_are_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            report = run_demo(store=store)
            events = store.list_events(report["run_id"])

            checks = [event for event in events if event["tool_name"] == "dataset_monitor"]
            self.assertGreaterEqual(len(checks), 2)
            self.assertIn("labelable items generated", checks[-1]["summary"])


if __name__ == "__main__":
    unittest.main()
