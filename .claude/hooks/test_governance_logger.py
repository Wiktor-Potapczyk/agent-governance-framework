"""Tests for _governance_logger, the shared hook fire-logging helper.

Written 2026-08-01 alongside the dark-12 instrumentation wave. The helper had
no tests despite being the single writer every class-B hook now depends on, so
a regression in it would silently blank the fire stream rather than fail loudly.

Two concerns are covered:
  log_fire      : record shape, failure-tolerance, append semantics
  session_from  : best-effort session identity from a hook payload (contract C3:
                  a record that carries a session must carry a real one; a record
                  that cannot know its session carries null, never a guess)
"""

import importlib.util
import json
import os
import tempfile
import threading
import unittest
from unittest import mock


def _load(log_path):
    """Load a fresh copy of the module with _LOG_PATH redirected."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_governance_logger.py")
    spec = importlib.util.spec_from_file_location("gl_under_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._LOG_PATH = log_path
    return m


class _ConstantPathTestCase(unittest.TestCase):
    """Base for tests that assert on the module constant, not the env var.

    conftest redirects the whole suite via HOOK_ACTIVITY_LOG_PATH, and the env
    var outranks the module constant by design. Any test that writes through
    log_fire and then reads the constant's path must opt out of that redirect
    or it reads an empty directory. LogPathOverrideTests re-sets the var per
    test, so it does not inherit from this.
    """

    def _use_module_constant(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop("HOOK_ACTIVITY_LOG_PATH", None)
        self.addCleanup(patcher.stop)


class LogFireTests(_ConstantPathTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "hook-activity.jsonl")
        self.m = _load(self.log)
        self._use_module_constant()

    def _records(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_writes_one_record_with_the_expected_keys(self):
        self.m.log_fire("some-hook", decision="allow", detail="d", session="s")
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(
            sorted(recs[0]),
            ["decision", "detail", "event", "hook", "session", "ts"],
        )
        self.assertEqual(recs[0]["event"], "hook_fire")
        self.assertEqual(recs[0]["hook"], "some-hook")
        self.assertEqual(recs[0]["decision"], "allow")

    def test_optional_fields_default_to_null_not_missing(self):
        self.m.log_fire("some-hook")
        rec = self._records()[0]
        self.assertIsNone(rec["decision"])
        self.assertIsNone(rec["detail"])
        self.assertIsNone(rec["session"])

    def test_appends_rather_than_truncating(self):
        self.m.log_fire("a")
        self.m.log_fire("b")
        self.assertEqual([r["hook"] for r in self._records()], ["a", "b"])

    def test_detail_is_truncated_to_200_chars(self):
        self.m.log_fire("h", detail="x" * 500)
        self.assertEqual(len(self._records()[0]["detail"]), 200)

    def test_never_raises_when_the_log_path_is_unwritable(self):
        self.m._LOG_PATH = os.path.join(self.tmp, "no-such-dir", "x.jsonl")
        import contextlib
        import io
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            self.m.log_fire("h")  # must not raise
        # the docstring contract is silent no-op: no stderr leakage either
        self.assertEqual(captured.getvalue(), "")

    def test_never_raises_on_an_unserialisable_detail(self):
        self.m.log_fire("h", detail=object())  # str() coerced, must not raise
        self.assertEqual(len(self._records()), 1)


class LogPathOverrideTests(unittest.TestCase):
    """The other half of the test-pollution fix. _event_emit got a
    GOVERNANCE_LOG_PATH override on 2026-08-01 and the suite stopped writing to
    the live governance log. This writer owns the OTHER stream and had no
    equivalent, so hook-activity.jsonl stayed fully polluted: one hooks-suite
    run appended 117 records to it, measured before this override existed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "hook-activity.jsonl")
        self.m = _load(self.log)

    def _count(self, path):
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as fh:
            return len([l for l in fh if l.strip()])

    def test_env_var_redirects_the_write(self):
        other = os.path.join(self.tmp, "redirected.jsonl")
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": other}):
            self.m.log_fire("h", decision="allow")
        self.assertEqual(self._count(other), 1)
        self.assertEqual(self._count(self.log), 0, "default path must stay untouched")

    def test_module_constant_still_works_when_no_env_var_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOOK_ACTIVITY_LOG_PATH", None)
            self.m.log_fire("h", decision="allow")
        self.assertEqual(self._count(self.log), 1)

    def test_an_empty_env_var_falls_back_to_the_module_constant(self):
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": "   "}):
            self.m.log_fire("h", decision="allow")
        self.assertEqual(self._count(self.log), 1)

    def test_the_override_never_makes_log_fire_raise(self):
        bad = os.path.join(self.tmp, "no-such-dir", "x.jsonl")
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": bad}):
            self.m.log_fire("h")  # must not raise


class SessionFromTests(_ConstantPathTestCase):
    """Contract C3: derive a real session id or return None. Never invent one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = _load(os.path.join(self.tmp, "hook-activity.jsonl"))
        self._use_module_constant()

    def test_reads_session_id_from_a_payload_dict(self):
        sid = "59710481-ff64-4af5-9fb8-e77b30af5e01"
        self.assertEqual(self.m.session_from({"session_id": sid}), sid)

    def test_reads_session_id_from_raw_json_text(self):
        sid = "59710481-ff64-4af5-9fb8-e77b30af5e01"
        self.assertEqual(self.m.session_from(json.dumps({"session_id": sid})), sid)

    def test_falls_back_to_the_transcript_filename(self):
        sid = "8a2cd9c6-c88e-47f6-8763-3bd98706c6d1"
        payload = {"transcript_path": "C:/x/projects/vault/%s.jsonl" % sid}
        self.assertEqual(self.m.session_from(payload), sid)

    def test_session_id_wins_over_transcript_path(self):
        payload = {"session_id": "aaa", "transcript_path": "C:/x/bbb.jsonl"}
        self.assertEqual(self.m.session_from(payload), "aaa")

    def test_returns_none_when_identity_is_absent(self):
        self.assertIsNone(self.m.session_from({}))
        self.assertIsNone(self.m.session_from(""))
        self.assertIsNone(self.m.session_from(None))
        self.assertIsNone(self.m.session_from("not json at all"))
        self.assertIsNone(self.m.session_from([1, 2, 3]))

    def test_blank_and_whitespace_values_are_not_identities(self):
        self.assertIsNone(self.m.session_from({"session_id": "   "}))
        self.assertIsNone(self.m.session_from({"session_id": ""}))
        self.assertIsNone(self.m.session_from({"transcript_path": "   "}))

    def test_result_feeds_log_fire_unchanged(self):
        sid = "59710481-ff64-4af5-9fb8-e77b30af5e01"
        self.m.log_fire("h", session=self.m.session_from({"session_id": sid}))
        with open(self.m._LOG_PATH, encoding="utf-8") as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["session"], sid)


class BeltAndSuspendersGuardTests(unittest.TestCase):
    """Phase 1 (CE-1 qmd substrate repair, 2026-08-07): the stack-based
    fallback that closes the one bypass class conftest.py's env-var redirect
    cannot reach (a bare `python -m unittest` run on a hook test file whose
    test code never touches this module, so the real hook under test writes
    straight to the live file). See finding_unittest_bypasses_conftest_log_redirect.md.

    _LOG_PATH and _LIVE_LOG_PATH are both monkeypatched to the SAME decoy path
    in every case (never the real hook-activity.jsonl), so a guard defect
    cannot pollute the live log even if this test itself fails.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.decoy_live = os.path.join(self.tmp, "decoy-hook-activity.jsonl")
        self.m = _load(self.decoy_live)
        self.m._LIVE_LOG_PATH = self.decoy_live
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("HOOK_ACTIVITY_LOG_PATH", None)
        self.addCleanup(self._env_patch.stop)

    def _records(self, path):
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_a_test_context_with_no_override_redirects_away_from_the_decoy_live_path(self):
        # This test method's own frame is a unittest.TestCase bound in a
        # test_*.py file: exactly the shape _in_test_context() looks for.
        self.m.log_fire("some-hook")
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
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": other}):
            self.m.log_fire("h")
        self.assertEqual(len(self._records(other)), 1)
        self.assertEqual(self._records(self.decoy_live), [])
        fallback = self.m._test_fallback_path()
        self.assertEqual(
            self._records(fallback), [],
            "the explicit env override must win over the stack-based guard",
        )

    def test_c_a_non_test_frame_is_unaffected_and_writes_to_the_live_shaped_path(self):
        # Run log_fire on a worker thread: inspect.stack() only sees the
        # CURRENT thread's frames, so this thread's stack contains no
        # test_*.py/TestCase frame at all, genuinely simulating a production
        # hook firing (not just "called during a test run").
        t = threading.Thread(target=self.m.log_fire, args=("prod-hook",))
        t.start()
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        recs = self._records(self.decoy_live)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["hook"], "prod-hook")


if __name__ == "__main__":
    unittest.main()
