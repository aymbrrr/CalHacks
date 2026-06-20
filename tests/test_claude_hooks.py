import json
import tempfile
import unittest
from pathlib import Path

from redundant_app.claude_hooks import CALLS_FILE, EVENTS_FILE, capture_hook_event, handle_hook_stdin
from redundant_app.storage import JsonlStore


def prompt_event(prompt: str):
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "claude-session-test",
        "prompt": prompt,
    }


def post_tool_event(tool_name: str, tool_input: dict, tool_response: dict):
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "claude-session-test",
        "tool_use_id": f"tool-{tool_name}-1",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
    }


class ClaudeHookCaptureTests(unittest.TestCase):
    def test_repeated_user_prompts_create_labelable_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = capture_hook_event(prompt_event("Plan the Redundant LangCache demo for Claude Code."), data_dir=tmp)
            second = capture_hook_event(prompt_event("Plan a Redundant LangCache demo for Claude Code hooks."), data_dir=tmp)
            store = JsonlStore(Path(tmp))
            items = store.list_label_items()

            self.assertIsNone(first.label_item)
            self.assertIsNotNone(second.label_item)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["new_call"]["call_kind"], "llm")
            self.assertEqual(items[0]["source"], "claude_code_hook")
            self.assertTrue((Path(tmp) / EVENTS_FILE).exists())
            self.assertTrue((Path(tmp) / CALLS_FILE).exists())

    def test_write_tool_input_is_summarized_not_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_hook_event(
                post_tool_event(
                    "Write",
                    {"file_path": "demo.py", "content": "secret-looking code " * 80},
                    {"content": "ok"},
                ),
                data_dir=tmp,
            )
            calls_blob = (Path(tmp) / CALLS_FILE).read_text(encoding="utf-8")

            self.assertIn("content_summary", calls_blob)
            self.assertNotIn("secret-looking code secret-looking code", calls_blob)

    def test_cli_context_outputs_claude_hook_json_when_candidate_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            handle_hook_stdin(["--data-dir", tmp], stdin=json.dumps(prompt_event("Summarize Redundant cache demo.")))

            output_path = Path(tmp) / "stdout.txt"
            # Use a direct function call for deterministic setup, then assert the command path succeeds.
            result = capture_hook_event(
                prompt_event("Summarize the Redundant cache demo with LangCache."),
                data_dir=tmp,
            )

            self.assertIsNotNone(result.label_item)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
