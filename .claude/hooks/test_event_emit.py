"""Tests for _event_emit, the shared governance-log writer.

Written 2026-08-01 as the first step of contract C7 (writer convergence). The
module had no tests at all, which is a poor state for a helper that other
writers are about to be migrated onto: a regression in it would silently blank
the governance-log rather than fail loudly.

The log-path override tested here exists for that migration. Direct writers
today can redirect their writes during tests (bash-safety-guard reads
GATE1_ALARM_LOG_PATH, and its own suite uses that to write to a temp file).
_event_emit had no equivalent, so migrating such a writer onto it would have
silently dropped that test isolation and written to the real log.
"""

import importlib.util
import json
import os
import tempfile
import threading
import unittest
from unittest import mock


def _load():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_event_emit.py")
    spec = importlib.util.spec_from_file_location("ee_under_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Base(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "governance-log.jsonl")
        self.m.LOG_PATH = self.log
        # conftest redirects the whole suite via GOVERNANCE_LOG_PATH, and the env
        # var outranks the module constant by design. These tests are the ones
        # exercising the constant path, so they opt out of the suite-wide
        # redirect; LogPathOverrideTests re-sets the var where it needs it.
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("GOVERNANCE_LOG_PATH", None)
        self.addCleanup(self._env_patch.stop)

    def records(self, path=None):
        path = path or self.log
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class RecordShapeTests(_Base):
    def test_mandatory_schema_v2_fields_are_present(self):
        self.m.emit_event(event="e", hook="h", session="s")
        rec = self.records()[0]
        for key in ("ts", "schema", "event", "hook", "session", "environment"):
            self.assertIn(key, rec)
        self.assertEqual(rec["schema"], 2)

    def test_extra_fields_are_merged(self):
        self.m.emit_event(event="e", hook="h", session="s",
                          extra={"pattern": "p", "count": 3})
        rec = self.records()[0]
        self.assertEqual(rec["pattern"], "p")
        self.assertEqual(rec["count"], 3)

    def test_extra_cannot_overwrite_a_reserved_field(self):
        self.m.emit_event(event="real", hook="h", session="s",
                          extra={"event": "spoofed", "schema": 99})
        rec = self.records()[0]
        self.assertEqual(rec["event"], "real")
        self.assertEqual(rec["schema"], 2)

    def test_non_dict_extra_is_ignored_without_raising(self):
        self.m.emit_event(event="e", hook="h", session="s", extra=["not", "a", "dict"])
        self.assertEqual(len(self.records()), 1)

    def test_falsy_session_becomes_the_unknown_placeholder(self):
        self.m.emit_event(event="e", hook="h", session=None)
        self.assertEqual(self.records()[0]["session"], "unknown")

    def test_appends_rather_than_truncating(self):
        self.m.emit_event(event="a", hook="h", session="s")
        self.m.emit_event(event="b", hook="h", session="s")
        self.assertEqual([r["event"] for r in self.records()], ["a", "b"])


class EnvironmentTests(_Base):
    def test_defaults_to_prod(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OBSERVABILITY_ENV", None)
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(self.records()[0]["environment"], "prod")

    def test_env_var_selects_test(self):
        with mock.patch.dict(os.environ, {"OBSERVABILITY_ENV": "test"}):
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(self.records()[0]["environment"], "test")

    def test_explicit_argument_wins_over_the_env_var(self):
        with mock.patch.dict(os.environ, {"OBSERVABILITY_ENV": "test"}):
            self.m.emit_event(event="e", hook="h", session="s", environment="prod")
        self.assertEqual(self.records()[0]["environment"], "prod")


class FailureToleranceTests(_Base):
    def test_unwritable_path_does_not_raise(self):
        self.m.LOG_PATH = os.path.join(self.tmp, "no-such-dir", "x.jsonl")
        self.m.emit_event(event="e", hook="h", session="s")  # must not raise

    def test_unserialisable_extra_does_not_raise_and_writes_nothing(self):
        self.m.emit_event(event="e", hook="h", session="s", extra={"o": object()})
        self.assertEqual(self.records(), [])

    def test_a_missing_required_argument_still_raises(self):
        # Deliberate: required arguments bind before the internal try, so a
        # caller that forgets one finds out immediately instead of losing the
        # event silently. Pinned so a refactor cannot quietly soften it.
        with self.assertRaises(TypeError):
            self.m.emit_event(event="e", hook="h")


class LogPathOverrideTests(_Base):
    """The migration prerequisite: a writer moving onto _event_emit must still
    be able to redirect its writes during its own tests."""

    def test_env_var_redirects_the_write(self):
        other = os.path.join(self.tmp, "redirected.jsonl")
        with mock.patch.dict(os.environ, {"GOVERNANCE_LOG_PATH": other}):
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(len(self.records(other)), 1)
        self.assertEqual(self.records(), [], "default path must stay untouched")

    def test_module_constant_still_works_when_no_env_var_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOVERNANCE_LOG_PATH", None)
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(len(self.records()), 1)

    def test_an_empty_env_var_falls_back_to_the_module_constant(self):
        with mock.patch.dict(os.environ, {"GOVERNANCE_LOG_PATH": "   "}):
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(len(self.records()), 1)


class BeltAndSuspendersGuardTests(unittest.TestCase):
    """Phase 1 (CE-1 qmd substrate repair, 2026-08-07): the stack-based
    fallback that closes the one bypass class conftest.py's env-var redirect
    cannot reach (a bare `python -m unittest` run on a hook test file whose
    test code never touches this module, so the real hook under test writes
    straight to the live file). See finding_unittest_bypasses_conftest_log_redirect.md.

    LOG_PATH and _LIVE_LOG_PATH are both monkeypatched to the SAME decoy path
    in every case (never the real governance-log.jsonl), so a guard defect
    cannot pollute the live log even if this test itself fails.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.decoy_live = os.path.join(self.tmp, "decoy-governance-log.jsonl")
        self.m = _load()
        self.m.LOG_PATH = self.decoy_live
        self.m._LIVE_LOG_PATH = self.decoy_live
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("GOVERNANCE_LOG_PATH", None)
        self.addCleanup(self._env_patch.stop)

    def _records(self, path):
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_a_test_context_with_no_override_redirects_away_from_the_decoy_live_path(self):
        # This test method's own frame is a unittest.TestCase bound in a
        # test_*.py file: exactly the shape _in_test_context() looks for.
        self.m.emit_event(event="e", hook="some-hook", session="s")
        self.assertEqual(
            self._records(self.decoy_live), [],
            "guard must not write to the live-shaped path from a test frame",
        )
        fallback = self.m._test_fallback_path()
        recs = self._records(fallback)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["hook"], "some-hook")

    def test_b_explicit_env_override_still_wins_over_the_stack_guard(self):
        other = os.path.join(self.tmp, "explicit-override.jsonl")
        with mock.patch.dict(os.environ, {"GOVERNANCE_LOG_PATH": other}):
            self.m.emit_event(event="e", hook="h", session="s")
        self.assertEqual(len(self._records(other)), 1)
        self.assertEqual(self._records(self.decoy_live), [])
        fallback = self.m._test_fallback_path()
        self.assertEqual(
            self._records(fallback), [],
            "the explicit env override must win over the stack-based guard",
        )

    def test_c_a_non_test_frame_is_unaffected_and_writes_to_the_live_shaped_path(self):
        # Run emit_event on a worker thread: inspect.stack() only sees the
        # CURRENT thread's frames, so this thread's stack contains no
        # test_*.py/TestCase frame at all, genuinely simulating a production
        # hook firing (not just "called during a test run").
        t = threading.Thread(
            target=self.m.emit_event, kwargs={"event": "e", "hook": "prod-hook", "session": "s"}
        )
        t.start()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        recs = self._records(self.decoy_live)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["hook"], "prod-hook")


if __name__ == "__main__":
    unittest.main()
