"""
Unit tests for session-start-log.py — P1-B (2026-04-09).

Covers:
- Session ID extraction from payload.session_id (priority)
- Session ID extraction from transcript_path (fallback)
- "unknown" default when neither is present
- Graceful handling of malformed JSON
- Proper entry structure (schema=2, event=session_start)

Run: python .claude/hooks/test_session_start_log.py
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session-start-log.py")


def run_hook_with_payload(payload_json, log_path):
    """Helper: run the hook with a mock payload, capture what was written to log_path."""
    spec = importlib.util.spec_from_file_location("session_start_log", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)

    # Redirect LOG_PATH to our temp file
    original_log_path = None

    # We need to monkey-patch LOG_PATH before main() runs
    # Do this by loading the module and modifying its LOG_PATH
    spec.loader.exec_module(mod)
    mod.LOG_PATH = log_path

    # Provide stdin
    with patch.object(sys, 'stdin', io.StringIO(payload_json)):
        mod.main()

    # Read back what was written
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                return json.loads(content.split('\n')[-1])
    return None


class TestSessionStartLog(unittest.TestCase):

    def setUp(self):
        # Create a temp log file for each test
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.jsonl', encoding='utf-8')
        self.tmp.close()
        self.log_path = self.tmp.name

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)

    def test_session_id_from_payload(self):
        payload = json.dumps({
            "session_id": "abc123-def456-ghi789",
            "source": "startup",
            "transcript_path": "/tmp/other-id.jsonl"
        })
        entry = run_hook_with_payload(payload, self.log_path)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["session"], "abc123-def456-ghi789")
        self.assertEqual(entry["source"], "startup")
        self.assertEqual(entry["event"], "session_start")
        self.assertEqual(entry["schema"], 2)

    def test_session_id_from_transcript_path(self):
        payload = json.dumps({
            "source": "resume",
            "transcript_path": "/tmp/xyz987-uuu555.jsonl"
        })
        entry = run_hook_with_payload(payload, self.log_path)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["session"], "xyz987-uuu555")
        self.assertEqual(entry["source"], "resume")

    def test_unknown_default(self):
        payload = json.dumps({"source": "clear"})
        entry = run_hook_with_payload(payload, self.log_path)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["session"], "unknown")

    def test_malformed_json_no_crash(self):
        # Should not raise, should not write anything
        try:
            entry = run_hook_with_payload("{not valid json", self.log_path)
            self.assertIsNone(entry)  # Nothing logged
        except Exception as e:
            self.fail(f"Hook should not raise on malformed JSON, got: {e}")

    def test_empty_stdin(self):
        entry = run_hook_with_payload("", self.log_path)
        self.assertIsNone(entry)

    def test_source_defaults_to_unknown(self):
        payload = json.dumps({
            "session_id": "test-session-no-source"
        })
        entry = run_hook_with_payload(payload, self.log_path)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["source"], "unknown")

    def test_schema_version_present(self):
        payload = json.dumps({
            "session_id": "test",
            "source": "startup"
        })
        entry = run_hook_with_payload(payload, self.log_path)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["schema"], 2, "P1-E: schema field must be 2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
