#!/usr/bin/env python3
"""Tests for user-prompt-state-inject.py -- project-discovery failure observability.

Covers:
  - detect_active_project(): forcing the `_project_discovery` import to fail
    must fail open (returns (None, None, None), unchanged) AND log a
    "degraded" record to hook-activity.jsonl, with the session id threaded
    from the raw stdin payload.
  - A malformed raw payload must never raise -- session_from() fails closed
    to None and the logging call is itself swallowed on any error.
  - main(): the discovery-failure path still emits empty additionalContext
    (unchanged fail-open behaviour), matching what the hook did before this
    fix -- only observability was added, not a new emission.
  - Healthy path (real _project_discovery import succeeds): no degraded log
    record, unchanged 3-tuple return shape.

Must run under pytest (not plain unittest) -- conftest.py's session-scoped
autouse fixture redirects HOOK_ACTIVITY_LOG_PATH away from the live stream.
"""

import importlib.util
import json
import os
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load the module under test without executing __main__.
# ---------------------------------------------------------------------------
_HOOK_PATH = Path(__file__).parent / "user-prompt-state-inject.py"

spec = importlib.util.spec_from_file_location("user_prompt_state_inject_under_test", _HOOK_PATH)
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)  # type: ignore[union-attr]


def _read_activity_records():
    path = os.environ.get("HOOK_ACTIVITY_LOG_PATH")
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestDetectActiveProjectDiscoveryFailure(unittest.TestCase):

    def setUp(self):
        self._orig_pd_module = sys.modules.get("_project_discovery", "__absent__")

    def tearDown(self):
        if self._orig_pd_module == "__absent__":
            sys.modules.pop("_project_discovery", None)
        else:
            sys.modules["_project_discovery"] = self._orig_pd_module

    def test_import_failure_fails_open_and_logs(self):
        """Forced `_project_discovery` import failure must still return
        (None, None, None) but leave a degraded record in hook-activity.jsonl,
        with the session id threaded from the raw payload."""
        sys.modules["_project_discovery"] = None  # forces ImportError on import
        before = len(_read_activity_records())

        raw = json.dumps({"session_id": "test-session-upsi"})
        result = _module.detect_active_project(raw)

        self.assertEqual(result, (None, None, None))

        after = _read_activity_records()
        new_records = after[before:]
        self.assertGreater(len(new_records), 0)
        degraded = [r for r in new_records
                    if r.get("hook") == "user-prompt-state-inject" and r.get("decision") == "degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertIn("_project_discovery unavailable", degraded[0].get("detail", ""))
        self.assertEqual(degraded[0].get("session"), "test-session-upsi")

    def test_import_failure_with_malformed_raw_never_raises(self):
        """A malformed raw payload must not crash detect_active_project --
        session_from() fails closed to None, and the logging call itself
        is wrapped so it can never propagate a new failure mode."""
        sys.modules["_project_discovery"] = None
        result = _module.detect_active_project("{not valid json")
        self.assertEqual(result, (None, None, None))

    def test_healthy_path_no_degraded_record(self):
        """The real `_project_discovery` import (unforced) leaves the healthy
        path unchanged: no degraded log record, and the normal 3-tuple shape."""
        sys.modules.pop("_project_discovery", None)
        before = len(_read_activity_records())

        result = _module.detect_active_project("{}")

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

        after = _read_activity_records()
        degraded = [r for r in after[before:]
                    if r.get("hook") == "user-prompt-state-inject" and r.get("decision") == "degraded"]
        self.assertEqual(degraded, [])


class TestMainEmitsEmptyOnDiscoveryFailure(unittest.TestCase):
    """End-to-end: main() must stay silent (emit empty additionalContext) on
    a discovery failure -- identical output to the pre-fix behaviour."""

    def setUp(self):
        self._orig_pd_module = sys.modules.get("_project_discovery", "__absent__")

    def tearDown(self):
        if self._orig_pd_module == "__absent__":
            sys.modules.pop("_project_discovery", None)
        else:
            sys.modules["_project_discovery"] = self._orig_pd_module

    def test_main_emits_empty_context_on_discovery_failure(self):
        sys.modules["_project_discovery"] = None
        payload = json.dumps({
            "prompt": "what should I do next",
            "session_id": "test-session-upsi-main",
        })
        with patch("sys.stdin", StringIO(payload)):
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                _module.main()
        output = json.loads(mock_out.getvalue().strip())
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"], "")


if __name__ == "__main__":
    unittest.main()
