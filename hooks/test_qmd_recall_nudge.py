"""Smoke tests for qmd-recall-nudge.py: PreToolUse(Grep) nudge.

Defect 2 (2026-08-07): the self-log log_fire() call never passed session=
even though `payload` (with session_id) was already in scope at the call site.
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
    "qmd_recall_nudge",
    str(Path(__file__).parent / "qmd-recall-nudge.py"),
)
qrn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qrn)


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        qrn.main()
    return captured.getvalue()


class TargetsQmdCorpusTests(unittest.TestCase):
    def test_memory_path_matches(self):
        self.assertEqual(
            qrn._targets_qmd_corpus("C:/Users/x/.claude/projects/y/memory/foo.md"),
            "memory",
        )

    def test_kb_path_matches(self):
        self.assertEqual(qrn._targets_qmd_corpus("Resources/KB/index.md"), "agr-kb")

    def test_unrelated_path_no_match(self):
        self.assertIsNone(qrn._targets_qmd_corpus("Projects/Foo/work/bar.md"))

    def test_empty_path_no_match(self):
        self.assertIsNone(qrn._targets_qmd_corpus(""))


class NudgeBehaviorTests(unittest.TestCase):
    def test_non_grep_tool_silent(self):
        out = _run({"tool_name": "Read", "tool_input": {"path": "Resources/KB"}})
        self.assertEqual(out, "")

    def test_grep_outside_corpus_silent(self):
        out = _run({"tool_name": "Grep", "tool_input": {"path": "Projects/Foo"}})
        self.assertEqual(out, "")

    def test_grep_kb_corpus_nudges(self):
        out = _run({"tool_name": "Grep", "tool_input": {"path": "Resources/KB"}})
        self.assertNotEqual(out, "")
        result = json.loads(out)
        self.assertIn("qmd-recall", result["hookSpecificOutput"]["additionalContext"])


class SessionWiringTests(unittest.TestCase):
    """Reproduces the broken shape first (a synthetic Grep-on-corpus payload),
    then asserts the self-log fire carries a populated session id."""

    def test_session_populates_from_payload(self):
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": activity_log}):
                _run({
                    "tool_name": "Grep",
                    "tool_input": {"path": "Resources/KB"},
                    "session_id": "test-qmdnudge-1",
                })
            self.assertTrue(os.path.exists(activity_log))
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hook"], "qmd-recall-nudge")
        self.assertEqual(records[0]["session"], "test-qmdnudge-1")
        self.assertEqual(records[0]["detail"], "agr-kb")


if __name__ == "__main__":
    unittest.main()
