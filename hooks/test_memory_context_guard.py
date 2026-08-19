"""Tests for memory-context-guard.py: PreToolUse advisory guard on
Write/Edit/MultiEdit into the memory folder (Hermes P2 Mechanism A).

Test matrix from the build plan (2026-08-18-hermes-p2-build-v2-plan.md, Step 3),
all cases mandatory. Every case runs on env-override paths pointed at a
per-test tempdir: MEMORY_CONTEXT_GUARD_DIR, MEMORY_CONTEXT_GUARD_LOG_PATH,
MEMORY_NUDGE_STATE_PATH. No test writes to the live memory folder, the live
log, or the live state file; case 8 asserts the live paths are untouched
around an in-scope event.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_HOOK_PATH = Path(__file__).parent / "memory-context-guard.py"
_spec = importlib.util.spec_from_file_location("memory_context_guard", str(_HOOK_PATH))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

_ENV_KEYS = (
    "MEMORY_CONTEXT_GUARD_DIR",
    "MEMORY_CONTEXT_GUARD_LOG_PATH",
    "MEMORY_NUDGE_STATE_PATH",
)


def _run(payload) -> str:
    """Run guard.main() with the payload on stdin, return captured stdout."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(text)), \
         redirect_stdout(captured):
        rc = guard.main()
    assert rc == 0, "guard.main() must always return 0"
    return captured.getvalue()


def _decision(out: str):
    if not out.strip():
        return None
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


class _GuardEnvTestCase(unittest.TestCase):
    """Base: tempdir memory folder, log, and state file via env overrides."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mem-ctx-guard-test-")
        self.memory_dir = os.path.join(self._tmp, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.log_path = os.path.join(self._tmp, "aggregates", "memory-context-warnings.jsonl")
        self.state_path = os.path.join(self._tmp, "_state", "memory-nudge.json")
        self._prev_env = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["MEMORY_CONTEXT_GUARD_DIR"] = self.memory_dir
        os.environ["MEMORY_CONTEXT_GUARD_LOG_PATH"] = self.log_path
        os.environ["MEMORY_NUDGE_STATE_PATH"] = self.state_path

    def tearDown(self):
        for k, v in self._prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _records(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def _mem_payload(self, **overrides):
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": os.path.join(self.memory_dir, "some-fact.md"),
                "content": "x",
            },
        }
        payload.update(overrides)
        return payload

    def _fake_subagent_transcript(self, agent_name="general-purpose"):
        """A minimal subagent transcript: the first user entry carries the
        dispatch prompt with the agent frontmatter name: field."""
        path = os.path.join(self._tmp, "subagent-transcript.jsonl")
        entry = {
            "type": "user",
            "message": {"content": [{
                "type": "text",
                "text": "---\nname: %s\ndescription: d\n---\nDo the task." % agent_name,
            }]},
        }
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return path


class Case1PayloadTierWarnTests(_GuardEnvTestCase):
    def test_agent_type_set_warns_allow_plus_reason(self):
        out = _run(self._mem_payload(agent_type="general-purpose", session_id="sess-1"))
        self.assertEqual(_decision(out), "allow")
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("advisory warning, not a block", reason)
        self.assertIn("main-session-owned", reason)
        self.assertIn("The write proceeds", reason)
        recs = self._records()
        self.assertEqual(len(recs), 1, "exactly one JSONL record per in-scope event")
        rec = recs[0]
        self.assertEqual(rec["decision"], "warn")
        self.assertEqual(rec["context"], "subagent")
        self.assertEqual(rec["detection_tier"], "payload")
        self.assertEqual(rec["agent_type"], "general-purpose")
        self.assertEqual(rec["tool"], "Write")
        self.assertEqual(rec["session"], "sess-1")
        for field in ("ts", "tool", "path", "context", "agent_type",
                      "detection_tier", "session", "decision"):
            self.assertIn(field, rec)


class Case2TranscriptTierWarnTests(_GuardEnvTestCase):
    def test_empty_agent_type_with_agent_transcript_warns_via_transcript_tier(self):
        transcript = self._fake_subagent_transcript("general-purpose")
        out = _run(self._mem_payload(agent_type="", transcript_path=transcript))
        self.assertEqual(_decision(out), "allow")
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["decision"], "warn")
        self.assertEqual(recs[0]["context"], "subagent")
        self.assertEqual(recs[0]["detection_tier"], "transcript")
        self.assertEqual(recs[0]["agent_type"], "general-purpose")


class Case3MainSessionLogOnlyTests(_GuardEnvTestCase):
    def test_no_subagent_signal_logs_only_no_reason_text(self):
        out = _run(self._mem_payload(session_id="sess-main"))
        self.assertEqual(out.strip(), "", "log-only path must print nothing")
        recs = self._records()
        self.assertEqual(len(recs), 1, "log-only events still produce one record")
        self.assertEqual(recs[0]["decision"], "log")
        self.assertEqual(recs[0]["context"], "main")
        self.assertEqual(recs[0]["detection_tier"], "none")
        self.assertEqual(recs[0]["agent_type"], "")


class Case4NonMemoryFastPathTests(_GuardEnvTestCase):
    def test_out_of_scope_path_no_record_no_state_touch(self):
        outside = os.path.join(self._tmp, "elsewhere", "note.md")
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": outside, "content": "x"},
            "agent_type": "general-purpose",
        })
        self.assertEqual(out.strip(), "")
        self.assertFalse(os.path.exists(self.log_path), "no log record out of scope")
        self.assertFalse(os.path.exists(self.state_path), "no state touch out of scope")


class Case5BoundaryPairTests(_GuardEnvTestCase):
    def test_file_directly_inside_the_folder_matches(self):
        inside = os.path.join(self.memory_dir, "inside.md")
        self.assertTrue(guard.is_memory_target(inside))
        _run({"tool_name": "Write", "tool_input": {"file_path": inside}})
        self.assertEqual(len(self._records()), 1)

    def test_sibling_prefix_without_separator_does_not_match(self):
        sibling = self.memory_dir + "X" + os.sep + "f.md"
        self.assertFalse(guard.is_memory_target(sibling))
        out = _run({"tool_name": "Write", "tool_input": {"file_path": sibling},
                    "agent_type": "general-purpose"})
        self.assertEqual(out.strip(), "")
        self.assertEqual(self._records(), [])


class Case6FailOpenTests(_GuardEnvTestCase):
    def test_malformed_payload_allows_without_crash(self):
        out = _run("this is not json {")
        self.assertEqual(out.strip(), "")

    def test_non_dict_payload_allows_without_crash(self):
        out = _run(json.dumps(["not", "a", "dict"]))
        self.assertEqual(out.strip(), "")

    def test_unreadable_state_file_still_warns_and_logs(self):
        # A directory at the state path makes both read and os.replace fail.
        os.makedirs(self.state_path, exist_ok=True)
        out = _run(self._mem_payload(agent_type="general-purpose"))
        self.assertEqual(_decision(out), "allow", "state failure must not kill the warn")
        self.assertEqual(len(self._records()), 1, "state failure must not kill the record")


class Case7CounterResetTests(_GuardEnvTestCase):
    def test_in_scope_event_resets_counter_and_watermark(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({
                "turns_since_memory_write": 23,
                "turns_at_last_nudge": 20,
                "last_memory_write_iso": "2026-08-01T00:00:00+00:00",
                "last_nudge_iso": "2026-08-17T00:00:00+00:00",
                "updated_iso": "2026-08-17T00:00:00+00:00",
            }, fh)
        _run(self._mem_payload())
        with open(self.state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["turns_since_memory_write"], 0)
        self.assertEqual(state["turns_at_last_nudge"], 0)
        self.assertTrue(state["last_memory_write_iso"].startswith("20"))
        self.assertNotEqual(state["last_memory_write_iso"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(state["last_nudge_iso"], "2026-08-17T00:00:00+00:00",
                         "reset must preserve last_nudge_iso")
        self.assertIn("updated_iso", state)

    def test_reset_bootstraps_missing_state_file(self):
        self.assertFalse(os.path.exists(self.state_path))
        _run(self._mem_payload())
        with open(self.state_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["turns_since_memory_write"], 0)
        self.assertEqual(state["turns_at_last_nudge"], 0)
        self.assertEqual(state["last_nudge_iso"], "")

    def test_reset_write_is_atomic_tmp_then_replace(self):
        _run(self._mem_payload())
        self.assertFalse(os.path.exists(self.state_path + ".tmp"),
                         "tmp file must be replaced away, not left behind")
        self.assertTrue(os.path.exists(self.state_path))


class Case8EnvOverrideAndLiveUntouchedTests(_GuardEnvTestCase):
    @staticmethod
    def _snapshot(path):
        if not os.path.exists(path):
            return ("absent", 0)
        return ("present", os.path.getsize(path))

    def test_overrides_honored_and_live_paths_untouched(self):
        live_log = guard._DEFAULT_LOG_PATH
        live_state = guard._DEFAULT_STATE_PATH
        before_log = self._snapshot(live_log)
        before_state = self._snapshot(live_state)

        _run(self._mem_payload(agent_type="general-purpose"))

        self.assertTrue(os.path.exists(self.log_path), "log landed at override path")
        self.assertTrue(os.path.exists(self.state_path), "state landed at override path")
        self.assertEqual(self._snapshot(live_log), before_log,
                         "live log must be untouched by tests")
        self.assertEqual(self._snapshot(live_state), before_state,
                         "live state file must be untouched by tests")


class NeverDenyBySourceTests(unittest.TestCase):
    """Step 8 acceptance: no "deny" in any output path of the hook source."""

    def test_every_permission_decision_in_source_is_allow(self):
        src = _HOOK_PATH.read_text(encoding="utf-8")
        decisions = re.findall(r'"permissionDecision":\s*"(\w+)"', src)
        self.assertTrue(decisions, "expected at least one permissionDecision emit")
        self.assertEqual(set(decisions), {"allow"})

    def test_stdlib_only_imports(self):
        src = _HOOK_PATH.read_text(encoding="utf-8")
        imports = re.findall(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                             src, re.MULTILINE)
        stdlib_ok = {"annotations", "json", "os", "re", "sys", "datetime",
                     "_governance_logger", "__future__"}
        self.assertTrue(set(imports).issubset(stdlib_ok),
                        "unexpected import: %s" % (set(imports) - stdlib_ok))


if __name__ == "__main__":
    unittest.main()
