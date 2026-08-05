"""Tests for hook-write-regression-gate.py (GAP-3a, TA-3 Phase 2 Step 2).

Polarity contract (plan Step-2 acceptance criterion):
  - red temp suite + hook-file Write payload  -> warning MUST be emitted
  - green temp suite + hook-file Write payload -> gate MUST stay silent
  - write outside .claude/hooks/               -> no pytest run (fast path)
  - write under _state/ (or archive/aggregates/__pycache__) -> ignored

All pytest runs target a TEMP mini-suite via HOOK_REGRESSION_GATE_TARGET_DIR /
HOOK_REGRESSION_GATE_LOG_PATH env overrides: never the live suite.
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


def _load(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(Path(__file__).parent / filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("hook-write-regression-gate.py", "hook_write_regression_gate")

HOOK_PATH = r"C:\Users\exampleuser\Workspace\.claude\hooks\some-hook.py"


def _run(payload: dict, env: dict) -> tuple[int, str]:
    captured = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        rc = gate.main()
    return rc, captured.getvalue()


def _payload(file_path: str, tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": file_path}}


class PathFilterTests(unittest.TestCase):
    def test_hook_py_is_gated(self):
        self.assertTrue(gate.is_gated_hook_write(HOOK_PATH))
        self.assertTrue(gate.is_gated_hook_write(".claude/hooks/foo.py"))
        self.assertTrue(gate.is_gated_hook_write(
            "C:/Users/exampleuser/Workspace/.claude/hooks/test_foo.py"
        ))  # test_*.py INCLUDED by design (plan Step-2 decision)

    def test_non_py_ignored(self):
        self.assertFalse(gate.is_gated_hook_write(
            r"C:\Users\exampleuser\Workspace\.claude\hooks\notes.md"
        ))

    def test_outside_hooks_ignored(self):
        self.assertFalse(gate.is_gated_hook_write(
            r"C:\Users\exampleuser\Workspace\.claude\scripts\foo.py"
        ))
        self.assertFalse(gate.is_gated_hook_write(
            r"C:\Users\exampleuser\Workspace\Projects\X\work\foo.py"
        ))

    def test_excluded_subdirs_ignored(self):
        for sub in ("_state", "archive", "aggregates", "__pycache__"):
            self.assertFalse(gate.is_gated_hook_write(
                rf"C:\Users\exampleuser\Workspace\.claude\hooks\{sub}\foo.py"
            ), sub)

    def test_empty_and_none_like(self):
        self.assertFalse(gate.is_gated_hook_write(""))


class GateBehaviorTests(unittest.TestCase):
    def _temp_suite(self, td: str, failing: bool) -> dict:
        suite_dir = Path(td) / "minisuite"
        suite_dir.mkdir()
        body = (
            "def test_red():\n    assert False\n" if failing
            else "def test_green():\n    assert True\n"
        )
        (suite_dir / "test_mini.py").write_text(body, encoding="utf-8")
        return {
            "HOOK_REGRESSION_GATE_TARGET_DIR": str(suite_dir),
            "HOOK_REGRESSION_GATE_LOG_PATH": str(Path(td) / "gate.log"),
        }

    def test_red_suite_emits_warning(self):
        with tempfile.TemporaryDirectory() as td:
            env = self._temp_suite(td, failing=True)
            rc, out = _run(_payload(HOOK_PATH), env)
            self.assertEqual(rc, 0)  # WARN-first: never nonzero
            self.assertIn("SUITE RED", out)
            self.assertIn("DO NOT report success", out)
            data = json.loads(out)
            self.assertEqual(
                data["hookSpecificOutput"]["hookEventName"], "PostToolUse"
            )

    def test_green_suite_stays_silent(self):
        with tempfile.TemporaryDirectory() as td:
            env = self._temp_suite(td, failing=False)
            rc, out = _run(_payload(HOOK_PATH), env)
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")  # a warning on a green suite is a defect

    def test_edit_tool_also_gated(self):
        with tempfile.TemporaryDirectory() as td:
            env = self._temp_suite(td, failing=True)
            rc, out = _run(_payload(HOOK_PATH, tool="Edit"), env)
            self.assertEqual(rc, 0)
            self.assertIn("SUITE RED", out)

    def test_outside_hooks_runs_no_pytest(self):
        """Fast path: run_suite must NOT be called for a non-hook write."""
        calls = []
        with mock.patch.object(
            gate, "run_suite",
            side_effect=lambda *a, **k: calls.append(a) or (1, "boom"),
        ):
            rc, out = _run(
                _payload(r"C:\Users\exampleuser\Workspace\Notes\x.py"), {}
            )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertEqual(calls, [])

    def test_state_write_ignored(self):
        calls = []
        with mock.patch.object(
            gate, "run_suite",
            side_effect=lambda *a, **k: calls.append(a) or (1, "boom"),
        ):
            rc, out = _run(_payload(
                r"C:\Users\exampleuser\Workspace\.claude\hooks\_state\x.py"
            ), {})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertEqual(calls, [])

    def test_non_write_tool_ignored(self):
        calls = []
        with mock.patch.object(
            gate, "run_suite",
            side_effect=lambda *a, **k: calls.append(a) or (1, "boom"),
        ):
            rc, out = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}}, {})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertEqual(calls, [])

    def test_gate_error_warns_loudly(self):
        """Unrunnable suite (nonexistent target) must warn, not stay silent."""
        with tempfile.TemporaryDirectory() as td:
            env = {
                "HOOK_REGRESSION_GATE_TARGET_DIR": str(Path(td) / "does-not-exist"),
                "HOOK_REGRESSION_GATE_LOG_PATH": str(Path(td) / "gate.log"),
            }
            rc, out = _run(_payload(HOOK_PATH), env)
            self.assertEqual(rc, 0)
            # pytest exits nonzero on a bad target -> SUITE RED (or GATE ERROR
            # if pytest itself could not start); either way it must be loud.
            self.assertTrue("REGRESSION GATE" in out, out)

    def test_malformed_stdin_fail_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{not json")), \
             redirect_stdout(captured):
            rc = gate.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
