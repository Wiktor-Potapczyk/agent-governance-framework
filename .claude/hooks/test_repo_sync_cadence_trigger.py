"""Smoke tests for repo-sync-cadence-trigger.py — SessionStart cadence trigger.

Defect 2 (2026-08-07): this hook never read stdin at all, so every _log_fire()
call always logged session=None even though CC's SessionStart payload carries
session_id like every other event.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "repo_sync_cadence_trigger",
    str(Path(__file__).parent / "repo-sync-cadence-trigger.py"),
)
rsc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rsc)


def _run(payload: dict, extra_env: dict | None = None) -> str:
    env = dict(extra_env or {})
    captured = io.StringIO()
    with mock.patch.dict(os.environ, env), \
         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        rsc.main()
    return captured.getvalue()


class SessionWiringTests(unittest.TestCase):
    """Reproduces the broken shape first (main() never derived identity from
    stdin at all), then asserts _SESSION and the logged record populate."""

    def _isolated_state(self, td):
        return {
            "throttled": lambda *a, **k: True,  # short-circuit past git/network work
        }

    def test_session_populates_module_global(self):
        rsc._SESSION = None
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            with mock.patch.object(rsc, "throttled", return_value=True):
                _run(
                    {"session_id": "test-reposync-1"},
                    extra_env={"HOOK_ACTIVITY_LOG_PATH": activity_log},
                )
        self.assertEqual(rsc._SESSION, "test-reposync-1")

    def test_throttled_fire_carries_session(self):
        rsc._SESSION = None
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            with mock.patch.object(rsc, "throttled", return_value=True):
                _run(
                    {"session_id": "test-reposync-2"},
                    extra_env={"HOOK_ACTIVITY_LOG_PATH": activity_log},
                )
            self.assertTrue(os.path.exists(activity_log))
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hook"], "repo-sync-cadence-trigger")
        self.assertEqual(records[0]["decision"], "throttled")
        self.assertEqual(records[0]["session"], "test-reposync-2")

    def test_missing_session_id_logs_null_not_crash(self):
        rsc._SESSION = None
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            with mock.patch.object(rsc, "throttled", return_value=True):
                _run({}, extra_env={"HOOK_ACTIVITY_LOG_PATH": activity_log})
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["session"])


if __name__ == "__main__":
    unittest.main()
