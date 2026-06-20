import tempfile
import unittest
from pathlib import Path

from redundant_app.demo import run_demo
from redundant_app.labels import annotation_queue, evaluate_labels, submit_label, terac_export
from redundant_app.storage import JsonlStore


class LabelWorkflowTests(unittest.TestCase):
    def test_pure_llm_item_can_be_labeled_and_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            run_demo(store=store)
            pure_llm_item = next(item for item in store.list_label_items() if item["new_call"]["call_kind"] == "llm")

            result = submit_label(
                store,
                {
                    "pair_id": pure_llm_item["pair_id"],
                    "final_label": "safe_reuse",
                    "confidence": 4,
                    "short_reason": "The later LLM planning request can reuse the earlier visible planning answer.",
                },
            )
            stats = store.dataset_stats()
            evaluation = evaluate_labels(store)

            self.assertTrue(result["accepted"])
            self.assertEqual(stats["labeled_items"], 1)
            self.assertEqual(stats["pure_llm_labeled_items"], 1)
            self.assertEqual(evaluation["labeled_items"], 1)
            self.assertEqual(evaluation["pure_llm_labeled_items"], 1)
            self.assertIn("raw_redis_policy", evaluation)
            self.assertIn("terac_gated_policy", evaluation)

    def test_annotation_queue_excludes_labeled_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            run_demo(store=store)
            first = annotation_queue(store, limit=1)[0]

            submit_label(
                store,
                {
                    "pair_id": first["pair_id"],
                    "final_label": "not_equivalent",
                    "confidence": 5,
                    "short_reason": "The candidate changes the requested work.",
                },
            )
            queued_ids = {item["pair_id"] for item in annotation_queue(store)}

            self.assertNotIn(first["pair_id"], queued_ids)

    def test_terac_export_defaults_to_unlabeled_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            run_demo(store=store)
            first = store.list_label_items()[0]
            submit_label(
                store,
                {
                    "pair_id": first["pair_id"],
                    "final_label": "side_effect_risk",
                    "confidence": 4,
                    "short_reason": "The cached call could repeat an external action.",
                },
            )

            export = terac_export(store)
            included_ids = {record["task_id"] for record in export["records"]}
            labeled_export = terac_export(store, include_labeled=True, limit=1)

            self.assertNotIn(first["pair_id"], included_ids)
            self.assertEqual(export["export_schema"], "TeracReuseLabelTask/v1")
            self.assertEqual(labeled_export["count"], 1)
            self.assertTrue(labeled_export["records"][0]["existing_answer"])

    def test_invalid_label_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp))
            run_demo(store=store)
            first = store.list_label_items()[0]

            result = submit_label(
                store,
                {
                    "pair_id": first["pair_id"],
                    "final_label": "reuse_it_probably",
                    "confidence": 4,
                    "short_reason": "Nope.",
                },
            )

            self.assertFalse(result["accepted"])
            self.assertIn("final_label", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
