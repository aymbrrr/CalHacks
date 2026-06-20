import json
import tempfile
import unittest
from pathlib import Path

from redundant_app.demo import run_demo
from redundant_app.storage import JsonlStore


class ContractTests(unittest.TestCase):
    def test_events_match_frontend_contract_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            report = run_demo(store=store)
            events = store.list_events(report["run_id"])

            self.assertTrue(events)
            for event in events:
                self.assertIn(event["decision"], {"EXECUTE", "EXACT_REUSE", "SEMANTIC_REUSE", "COMPRESS_AND_EXECUTE", "BLOCK_OR_WARN"})
                self.assertIn("Redis LangCache", event["sponsor_hooks"])
                self.assertIn("Redis Streams", event["sponsor_hooks"])
                self.assertIn("summary", event)

    def test_report_is_json_serializable_and_has_dataset_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            report = run_demo(store=store)
            encoded = json.dumps(report)

            self.assertIn("dataset", report)
            self.assertEqual(report["mode"], "redundant")
            self.assertEqual(report["status"], "complete")
            self.assertIn("labelable_items_generated", report["dataset"])
            self.assertIn(report["run_id"], encoded)

    def test_run_ids_are_unique_for_repeated_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            first = run_demo(store=store)
            second = run_demo(store=store)

            self.assertNotEqual(first["run_id"], second["run_id"])


if __name__ == "__main__":
    unittest.main()
