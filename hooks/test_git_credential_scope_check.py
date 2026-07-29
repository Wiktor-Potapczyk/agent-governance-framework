#!/usr/bin/env python3
"""Tests for git-credential-scope-check.py.

Covers:
  - value exactly "true"         -> silent (no stdout output)
  - value "false"                -> warning JSON emitted
  - config key missing (exit 1)  -> warning JSON emitted
  - subprocess exception         -> fail-open (no stdout output)
"""

import importlib.util
import json
import sys
import types
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the module under test without executing __main__.
# ---------------------------------------------------------------------------
_HOOK_PATH = Path(__file__).parent / "git-credential-scope-check.py"

spec = importlib.util.spec_from_file_location("git_credential_scope_check", _HOOK_PATH)
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)  # type: ignore[union-attr]


def _run_main(mock_proc_result=None, proc_exception=None):
    """Execute the module's main() with mocked subprocess and stdin.

    Returns the text captured from stdout.
    """
    with patch("sys.stdin", StringIO("")):
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            if proc_exception is not None:
                with patch(
                    "subprocess.run",
                    side_effect=proc_exception,
                ):
                    _module.main()
            else:
                with patch(
                    "subprocess.run",
                    return_value=mock_proc_result,
                ):
                    _module.main()
            return mock_out.getvalue()


def _make_proc(returncode: int, stdout: str) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = ""
    return proc


class TestGitCredentialScopeCheck(unittest.TestCase):

    def test_value_true_is_silent(self):
        """When credential.usehttppath = true, no output (silent pass)."""
        proc = _make_proc(returncode=0, stdout="true\n")
        output = _run_main(mock_proc_result=proc)
        self.assertEqual(output.strip(), "", "Expected no output when value is 'true'")

    def test_value_false_emits_warning(self):
        """When credential.usehttppath = false, a warning JSON is emitted."""
        proc = _make_proc(returncode=0, stdout="false\n")
        output = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "", "Expected warning output when value is 'false'")
        data = json.loads(output.strip())
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("usehttppath", ctx)
        self.assertIn("GIT CREDENTIAL SCOPE", ctx)

    def test_key_missing_emits_warning(self):
        """When git config --get exits non-zero (key absent), a warning is emitted."""
        proc = _make_proc(returncode=1, stdout="")
        output = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "", "Expected warning when key is missing")
        data = json.loads(output.strip())
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("usehttppath", ctx)

    def test_subprocess_exception_is_silent(self):
        """On subprocess.run raising an exception, fail-open: no output, exit 0."""
        output = _run_main(proc_exception=OSError("git not found"))
        self.assertEqual(output.strip(), "", "Expected silent fail-open on subprocess error")

    def test_subprocess_timeout_is_silent(self):
        """On TimeoutExpired, fail-open: no output."""
        import subprocess
        output = _run_main(
            proc_exception=subprocess.TimeoutExpired(cmd="git", timeout=5)
        )
        self.assertEqual(output.strip(), "", "Expected silent fail-open on timeout")

    def test_warning_json_is_valid_hook_contract(self):
        """Warning JSON must conform to SessionStart hookSpecificOutput contract."""
        proc = _make_proc(returncode=1, stdout="")
        output = _run_main(mock_proc_result=proc)
        data = json.loads(output.strip())
        self.assertIn("hookSpecificOutput", data)
        hook_out = data["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "SessionStart")
        self.assertIsInstance(hook_out["additionalContext"], str)
        self.assertGreater(len(hook_out["additionalContext"]), 10)

    def test_true_with_trailing_newline_is_silent(self):
        """'true\\n' (git config natural output) must be recognized as silent."""
        proc = _make_proc(returncode=0, stdout="true\n")
        output = _run_main(mock_proc_result=proc)
        self.assertEqual(output.strip(), "")

    def test_value_true_uppercase_emits_warning(self):
        """'True' (not exactly 'true') should emit a warning (strict match)."""
        proc = _make_proc(returncode=0, stdout="True\n")
        output = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "")

    def test_empty_value_emits_warning(self):
        """Empty string value (returncode=0, stdout='') emits warning."""
        proc = _make_proc(returncode=0, stdout="")
        output = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "")

    def test_main_returns_zero_always(self):
        """main() always returns 0."""
        for proc in [
            _make_proc(0, "true\n"),
            _make_proc(0, "false\n"),
            _make_proc(1, ""),
        ]:
            with patch("sys.stdin", StringIO("")), patch("sys.stdout", new_callable=StringIO):
                with patch("subprocess.run", return_value=proc):
                    ret = _module.main()
            self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
