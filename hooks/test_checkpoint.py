"""Smoke tests for checkpoint.py: PostToolUse hook (save-check reminder).

checkpoint.py is top-level script code (no main() function, no importable
module boundary: it runs on import), so it is exercised via subprocess like
reviewer-scope-violation-check.py's own smoke-test convention, not via
importlib.module_from_spec + direct calls like the other hook test files.

Defect 2 (2026-08-07): this hook never read stdin at all, so its log_fire()
call always wrote session=None to hook-activity.jsonl even though CC's
PostToolUse payload carries session_id like every other event.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK_PATH = str(Path(__file__).parent / "checkpoint.py")
PYTHON_EXE = r"C:\Program Files\Python314\python.exe"


def _run(payload: dict, userprofile: str, activity_log: str) -> tuple[int, str]:
    env = os.environ.copy()
    env["USERPROFILE"] = userprofile
    env["HOOK_ACTIVITY_LOG_PATH"] = activity_log
    result = subprocess.run(
        [PYTHON_EXE, HOOK_PATH],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=10,
        env=env,
    )
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


class SessionWiringTests(unittest.TestCase):
    def _fresh_profile(self, td: str) -> str:
        """A USERPROFILE with no pre-existing .claude/last-checkpoint file, so
        the first invocation always clears the 60s throttle (diff starts at 0,
        but the file is freshly written to `now`, so a SECOND call is what
        clears the throttle: see test below)."""
        profile = Path(td) / "profile"
        profile.mkdir()
        return str(profile)

    def test_session_populates_from_payload(self):
        with tempfile.TemporaryDirectory() as td:
            profile = self._fresh_profile(td)
            activity_log = str(Path(td) / "hook-activity.jsonl")
            # First call initializes CHECKPOINT_FILE and, since it did not
            # exist, `last` falls back to `now` (diff == 0 < 60): throttled,
            # no log_fire call. This matches the hook's own documented
            # contract ("Logged only past the 60s throttle").
            _run({"session_id": "test-checkpoint-1"}, profile, activity_log)
            self.assertFalse(
                os.path.exists(activity_log),
                "first call must stay under the 60s throttle and not log",
            )
            # Force the throttle open by rewriting the checkpoint file to a
            # timestamp far enough in the past.
            checkpoint_file = Path(profile) / ".claude" / "last-checkpoint"
            checkpoint_file.write_text("0", encoding="utf-8")
            rc, out = _run({"session_id": "test-checkpoint-1"}, profile, activity_log)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(activity_log))
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["hook"], "checkpoint")
            self.assertEqual(records[0]["session"], "test-checkpoint-1")

    def test_missing_session_id_logs_null_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            profile = self._fresh_profile(td)
            activity_log = str(Path(td) / "hook-activity.jsonl")
            _run({}, profile, activity_log)
            checkpoint_file = Path(profile) / ".claude" / "last-checkpoint"
            checkpoint_file.write_text("0", encoding="utf-8")
            rc, out = _run({}, profile, activity_log)
            self.assertEqual(rc, 0)
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["session"])


if __name__ == "__main__":
    unittest.main()
