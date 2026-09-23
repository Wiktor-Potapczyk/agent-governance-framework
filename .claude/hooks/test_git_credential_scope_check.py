#!/usr/bin/env python3
"""Tests for git-credential-scope-check.py.

Covers:
  - value exactly "true"         -> silent (no stdout output)
  - value "false"                -> warning JSON emitted
  - config key missing (exit 1)  -> warning JSON emitted
  - subprocess exception         -> fail-open (no stdout output)
  - the live check reads --global scope (matches the remediation text)
  - the 24h cache: fresh "ok" skips the subprocess call; a stale "ok", a
    "warn", a missing state file, or a corrupted state file all re-check live

Every test runs against an isolated temp state file (setUp/tearDown below),
so none of them can read or write the real `_state/git-credential-scope.json`
that this hook's own live SessionStart firings maintain.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


def _run_main(mock_proc_result=None, proc_exception=None, mock_run=None):
    """Execute the module's main() with mocked subprocess and stdin.

    Returns (stdout_text, mock_run_used). `mock_run` lets a caller pass its
    own MagicMock (e.g. to assert call args or call count); otherwise one is
    built from `mock_proc_result` / `proc_exception`.
    """
    if mock_run is None:
        mock_run = MagicMock()
        if proc_exception is not None:
            mock_run.side_effect = proc_exception
        else:
            mock_run.return_value = mock_proc_result

    with patch("sys.stdin", StringIO("")):
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            with patch("subprocess.run", mock_run):
                _module.main()
            return mock_out.getvalue(), mock_run


def _make_proc(returncode: int, stdout: str) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = ""
    return proc


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestGitCredentialScopeCheck(unittest.TestCase):

    def setUp(self):
        # Fresh, empty temp state dir per test: no test can see a cache
        # written by another test, or by this hook's own live firings.
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_state_dir = _module._STATE_DIR
        self._orig_state_file = _module._STATE_FILE
        _module._STATE_DIR = os.path.join(self._tmpdir.name, "_state")
        _module._STATE_FILE = os.path.join(_module._STATE_DIR, "git-credential-scope.json")

    def tearDown(self):
        _module._STATE_DIR = self._orig_state_dir
        _module._STATE_FILE = self._orig_state_file
        self._tmpdir.cleanup()

    def _seed_cache(self, result: str, age: timedelta):
        os.makedirs(_module._STATE_DIR, exist_ok=True)
        last = datetime.now(timezone.utc) - age
        with open(_module._STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_verified": _iso(last), "result": result}, f)

    # ------------------------------------------------------------------
    # Original behaviour (value/warning/fail-open): unchanged intent
    # ------------------------------------------------------------------

    def test_value_true_is_silent(self):
        """When credential.usehttppath = true, no output (silent pass)."""
        proc = _make_proc(returncode=0, stdout="true\n")
        output, _ = _run_main(mock_proc_result=proc)
        self.assertEqual(output.strip(), "", "Expected no output when value is 'true'")

    def test_value_false_emits_warning(self):
        """When credential.usehttppath = false, a warning JSON is emitted."""
        proc = _make_proc(returncode=0, stdout="false\n")
        output, _ = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "", "Expected warning output when value is 'false'")
        data = json.loads(output.strip())
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("usehttppath", ctx)
        self.assertIn("GIT CREDENTIAL SCOPE", ctx)

    def test_key_missing_emits_warning(self):
        """When git config --get exits non-zero (key absent), a warning is emitted."""
        proc = _make_proc(returncode=1, stdout="")
        output, _ = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "", "Expected warning when key is missing")
        data = json.loads(output.strip())
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("usehttppath", ctx)

    def test_subprocess_exception_is_silent(self):
        """On subprocess.run raising an exception, fail-open: no output, exit 0."""
        output, _ = _run_main(proc_exception=OSError("git not found"))
        self.assertEqual(output.strip(), "", "Expected silent fail-open on subprocess error")

    def test_subprocess_timeout_is_silent(self):
        """On TimeoutExpired, fail-open: no output."""
        import subprocess
        output, _ = _run_main(
            proc_exception=subprocess.TimeoutExpired(cmd="git", timeout=5)
        )
        self.assertEqual(output.strip(), "", "Expected silent fail-open on timeout")

    def test_warning_json_is_valid_hook_contract(self):
        """Warning JSON must conform to SessionStart hookSpecificOutput contract."""
        proc = _make_proc(returncode=1, stdout="")
        output, _ = _run_main(mock_proc_result=proc)
        data = json.loads(output.strip())
        self.assertIn("hookSpecificOutput", data)
        hook_out = data["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "SessionStart")
        self.assertIsInstance(hook_out["additionalContext"], str)
        self.assertGreater(len(hook_out["additionalContext"]), 10)

    def test_true_with_trailing_newline_is_silent(self):
        """'true\\n' (git config natural output) must be recognized as silent."""
        proc = _make_proc(returncode=0, stdout="true\n")
        output, _ = _run_main(mock_proc_result=proc)
        self.assertEqual(output.strip(), "")

    def test_value_true_uppercase_emits_warning(self):
        """'True' (not exactly 'true') should emit a warning (strict match)."""
        proc = _make_proc(returncode=0, stdout="True\n")
        output, _ = _run_main(mock_proc_result=proc)
        self.assertNotEqual(output.strip(), "")

    def test_empty_value_emits_warning(self):
        """Empty string value (returncode=0, stdout='') emits warning."""
        proc = _make_proc(returncode=0, stdout="")
        output, _ = _run_main(mock_proc_result=proc)
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

    # ------------------------------------------------------------------
    # Scope fix (defect a): the live check reads --global
    # ------------------------------------------------------------------

    def test_live_check_uses_global_scope(self):
        """The subprocess argv must include --global, matching the remediation
        text (`git config --global credential.usehttppath true`) rather than
        reading the effective (possibly repo-scoped) value."""
        proc = _make_proc(returncode=0, stdout="true\n")
        _, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()
        argv = mock_run.call_args.args[0]
        self.assertIn("--global", argv)
        self.assertEqual(
            argv,
            ["git", "config", "--global", "--get", "credential.usehttppath"],
        )

    # ------------------------------------------------------------------
    # Cache fix (defect b): 24h cache on a fresh "ok"
    # ------------------------------------------------------------------

    def test_cache_hit_skips_subprocess(self):
        """A fresh "ok" (verified 1h ago) skips the live check entirely."""
        self._seed_cache("ok", timedelta(hours=1))
        proc = _make_proc(returncode=0, stdout="true\n")
        output, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_not_called()
        self.assertEqual(output.strip(), "", "Cached ok must stay silent")

    def test_cache_expiry_rechecks(self):
        """A stale "ok" (verified 25h ago, past the 24h TTL) re-runs the live
        check rather than trusting the old cache."""
        self._seed_cache("ok", timedelta(hours=25))
        proc = _make_proc(returncode=0, stdout="false\n")
        output, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()
        self.assertNotEqual(output.strip(), "", "Expired cache must fall through to a live warning")

    def test_cache_corruption_falls_through(self):
        """A corrupted state file (invalid JSON) fails open to a live check,
        never raises, and never blocks the hook."""
        os.makedirs(_module._STATE_DIR, exist_ok=True)
        with open(_module._STATE_FILE, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        proc = _make_proc(returncode=0, stdout="true\n")
        output, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()
        self.assertEqual(output.strip(), "")

    def test_warn_never_cached(self):
        """A fresh "warn" result (verified 1h ago) does NOT skip the live
        check; only a fresh "ok" is allowed to short-circuit."""
        self._seed_cache("warn", timedelta(hours=1))
        proc = _make_proc(returncode=0, stdout="true\n")
        output, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()
        self.assertEqual(output.strip(), "", "Live re-check found ok this time, so output is silent")

    def test_missing_state_file_rechecks(self):
        """No prior state file at all (first-ever run) always re-checks live."""
        self.assertFalse(os.path.isfile(_module._STATE_FILE))
        proc = _make_proc(returncode=0, stdout="true\n")
        _, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()

    def test_ok_result_writes_cache(self):
        """A live "ok" result persists to the state file for the next run."""
        proc = _make_proc(returncode=0, stdout="true\n")
        _run_main(mock_proc_result=proc)
        with open(_module._STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["result"], "ok")
        self.assertIn("last_verified", data)

    def test_warn_result_writes_cache_but_stays_reevaluated(self):
        """A live "warn" result is recorded too, but (per test_warn_never_cached
        above) recording it never causes a future run to skip the live check."""
        proc = _make_proc(returncode=0, stdout="false\n")
        _run_main(mock_proc_result=proc)
        with open(_module._STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["result"], "warn")

    def test_future_timestamp_forces_live_recheck(self):
        """A future-dated "ok" cache (clock rollback, NTP correction, corrupted
        timestamp) must be treated as stale, not fresh. Without the fix,
        (now - last_dt) is negative and always < TTL, so the cache would read
        as "fresh ok" forever and the live check would never run again."""
        self._seed_cache("ok", timedelta(hours=-1))  # 1h in the future
        proc = _make_proc(returncode=0, stdout="false\n")
        output, mock_run = _run_main(mock_proc_result=proc)
        mock_run.assert_called_once()
        self.assertNotEqual(
            output.strip(), "",
            "Future-dated cache must fall through to a live check, not stay silent forever",
        )


if __name__ == "__main__":
    unittest.main()
