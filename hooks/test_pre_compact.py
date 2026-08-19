#!/usr/bin/env python3
"""Tests for pre-compact.py -- project-discovery failure observability.

pre-compact.py is a top-level script (module-level code executes fully on
import, no main() to call), so each test execs a fresh copy via
importlib.util.spec_from_file_location + exec_module, with sys.stdin and
USERPROFILE controlled so nothing touches the real recovery file, and
`_project_discovery` in sys.modules controlled so nothing touches the real
project-discovery import.

Covers:
  - _project_discovery import failure: projects=[] (fail-open, unchanged)
    PLUS a "[SNAPSHOT DEGRADED: ...]" marker written into the recovery file
    PLUS a "degraded" record logged to hook-activity.jsonl.
  - Healthy path (real _project_discovery import succeeds): no degraded
    marker, no degraded log record, unchanged shape.

Must run under pytest (not plain unittest) -- conftest.py's session-scoped
autouse fixture redirects HOOK_ACTIVITY_LOG_PATH away from the live stream.
Running these tests any other way would append synthetic records to the
real hook-activity.jsonl.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

_HOOK_PATH = Path(__file__).parent / "pre-compact.py"


def _run_hook(stdin_payload="{}"):
    """Exec a fresh copy of pre-compact.py with sys.stdin mocked.

    Returns the executed module object so tests can inspect module-level
    state (`projects`, `discovery_error`).
    """
    spec = importlib.util.spec_from_file_location("pre_compact_under_test", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch("sys.stdin", StringIO(stdin_payload)):
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _read_activity_records():
    path = os.environ.get("HOOK_ACTIVITY_LOG_PATH")
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestPreCompactDiscoveryFailure(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_userprofile = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = self._tmpdir.name
        self._orig_pd_module = sys.modules.get("_project_discovery", "__absent__")

    def tearDown(self):
        if self._orig_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self._orig_userprofile
        if self._orig_pd_module == "__absent__":
            sys.modules.pop("_project_discovery", None)
        else:
            sys.modules["_project_discovery"] = self._orig_pd_module
        self._tmpdir.cleanup()

    def _recovery_path(self):
        return os.path.join(self._tmpdir.name, ".claude", "pre-compact-recovery.md")

    def test_discovery_failure_writes_degraded_marker_and_logs(self):
        """Forcing `_project_discovery` import to fail must fail open (empty
        states/plans, unchanged) but leave a visible marker in the recovery
        file and a degraded record in hook-activity.jsonl."""
        sys.modules["_project_discovery"] = None  # forces ImportError on import
        before = len(_read_activity_records())

        payload = json.dumps({"transcript_path": r"C:\fake\abc123.jsonl"})
        module = _run_hook(payload)

        self.assertEqual(module.projects, [])
        self.assertIsNotNone(module.discovery_error)

        with open(self._recovery_path(), "r", encoding="utf-8") as f:
            recovery_text = f.read()
        self.assertIn("[SNAPSHOT DEGRADED: project discovery failed,", recovery_text)

        after = _read_activity_records()
        new_records = after[before:]
        self.assertGreater(len(new_records), 0)
        degraded = [r for r in new_records
                    if r.get("hook") == "pre-compact" and r.get("decision") == "degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertIn("_project_discovery unavailable", degraded[0].get("detail", ""))
        self.assertEqual(degraded[0].get("session"), "abc123")

    def test_healthy_path_has_no_degraded_marker(self):
        """The real `_project_discovery` import (unforced) must leave the
        healthy path unchanged: no discovery_error, no degraded marker,
        no degraded log record."""
        sys.modules.pop("_project_discovery", None)
        before = len(_read_activity_records())

        module = _run_hook(json.dumps({}))

        self.assertIsNone(module.discovery_error)
        self.assertIsInstance(module.projects, list)

        with open(self._recovery_path(), "r", encoding="utf-8") as f:
            recovery_text = f.read()
        self.assertNotIn("SNAPSHOT DEGRADED", recovery_text)

        after = _read_activity_records()
        degraded = [r for r in after[before:]
                    if r.get("hook") == "pre-compact" and r.get("decision") == "degraded"]
        self.assertEqual(degraded, [])


if __name__ == "__main__":
    unittest.main()
