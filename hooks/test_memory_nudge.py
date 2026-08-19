"""Tests for memory-nudge.py: Stop counter + SessionStart persistence nudge
(Hermes P2 Mechanism B).

Test matrix from the build plan (2026-08-18-hermes-p2-build-v2-plan.md, Step 5),
all cases mandatory, every case on the MEMORY_NUDGE_STATE_PATH override
pointed at a per-test tempdir. Case 9 asserts on the FULL captured output of
every invocation in this file that no code path returns a blocking decision.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_HOOK_PATH = Path(__file__).parent / "memory-nudge.py"
_spec = importlib.util.spec_from_file_location("memory_nudge", str(_HOOK_PATH))
nudge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nudge)

# Every stdout captured by _run() lands here; the case-9 test sweeps them all.
_ALL_OUTPUTS = []


def _run(payload) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(text)), \
         redirect_stdout(captured):
        rc = nudge.main()
    assert rc == 0, "nudge.main() must always return 0"
    out = captured.getvalue()
    _ALL_OUTPUTS.append(out)
    return out


class _NudgeEnvTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mem-nudge-test-")
        self.state_path = os.path.join(self._tmp, "_state", "memory-nudge.json")
        self._prev = os.environ.get("MEMORY_NUDGE_STATE_PATH")
        os.environ["MEMORY_NUDGE_STATE_PATH"] = self.state_path

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("MEMORY_NUDGE_STATE_PATH", None)
        else:
            os.environ["MEMORY_NUDGE_STATE_PATH"] = self._prev
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed(self, turns, watermark=0, **extra):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        state = {
            "turns_since_memory_write": turns,
            "turns_at_last_nudge": watermark,
            "last_memory_write_iso": "",
            "last_nudge_iso": "",
            "updated_iso": "",
        }
        state.update(extra)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def _state(self):
        with open(self.state_path, encoding="utf-8") as fh:
            return json.load(fh)


class Case1StopIncrementTests(_NudgeEnvTestCase):
    def test_stop_increments_by_one(self):
        self._seed(turns=4)
        out = _run({"hook_event_name": "Stop", "session_id": "s"})
        self.assertEqual(out.strip(), "", "Stop path must print nothing")
        self.assertEqual(self._state()["turns_since_memory_write"], 5)


class Case2StopChainSkipTests(_NudgeEnvTestCase):
    def test_stop_hook_active_skips_increment(self):
        self._seed(turns=4)
        out = _run({"hook_event_name": "Stop", "stop_hook_active": True})
        self.assertEqual(out.strip(), "")
        self.assertEqual(self._state()["turns_since_memory_write"], 4)


class Case3BelowThresholdTests(_NudgeEnvTestCase):
    def test_session_start_below_threshold_emits_nothing(self):
        self._seed(turns=nudge.THRESHOLD - 1)
        out = _run({"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(out.strip(), "")


class Case4ThresholdFireTests(_NudgeEnvTestCase):
    def test_session_start_at_threshold_fires_and_stamps(self):
        self._seed(turns=12)
        out = _run({"hook_event_name": "SessionStart", "source": "startup"})
        parsed = json.loads(out)
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[MEMORY PERSISTENCE]", ctx)
        self.assertIn("12 main-session turns", ctx)
        self.assertIn("Saving nothing is a correct outcome", ctx)
        self.assertIn("do-not-capture list", ctx)
        self.assertIn("never manufacture an entry", ctx)
        state = self._state()
        self.assertEqual(state["turns_at_last_nudge"], 12)
        self.assertTrue(state["last_nudge_iso"].startswith("20"))


class Case5AntiNagWatermarkTests(_NudgeEnvTestCase):
    def test_no_repeat_until_full_threshold_past_watermark(self):
        self._seed(turns=12)
        _run({"hook_event_name": "SessionStart"})  # fires, watermark = 12
        out2 = _run({"hook_event_name": "SessionStart"})
        self.assertEqual(out2.strip(), "", "immediate repeat must be silent")
        self._seed(turns=21, watermark=12)
        out3 = _run({"hook_event_name": "SessionStart"})
        self.assertEqual(out3.strip(), "", "21 - 12 = 9 < threshold: silent")
        self._seed(turns=22, watermark=12)
        out4 = _run({"hook_event_name": "SessionStart"})
        self.assertIn("[MEMORY PERSISTENCE]", out4, "22 - 12 = 10: fires again")


class Case6MechanismAResetHonoredTests(_NudgeEnvTestCase):
    def test_reset_state_from_guard_fires_next_at_clean_threshold(self):
        # Mechanism A writes counter 0 and watermark 0 after a real memory write.
        self._seed(turns=0, watermark=0)
        out = _run({"hook_event_name": "SessionStart"})
        self.assertEqual(out.strip(), "", "freshly reset: silent")
        self._seed(turns=nudge.THRESHOLD, watermark=0)
        out2 = _run({"hook_event_name": "SessionStart"})
        self.assertIn("[MEMORY PERSISTENCE]", out2, "fires at exactly 10 after reset")


class Case7BootstrapTests(_NudgeEnvTestCase):
    def test_missing_state_file_bootstraps_on_stop(self):
        self.assertFalse(os.path.exists(self.state_path))
        out = _run({"hook_event_name": "Stop"})
        self.assertEqual(out.strip(), "")
        self.assertEqual(self._state()["turns_since_memory_write"], 1)

    def test_missing_state_file_is_silent_on_session_start(self):
        out = _run({"hook_event_name": "SessionStart"})
        self.assertEqual(out.strip(), "")

    def test_corrupt_state_file_bootstraps_without_crash(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        out = _run({"hook_event_name": "Stop"})
        self.assertEqual(out.strip(), "")
        self.assertEqual(self._state()["turns_since_memory_write"], 1)

    def test_non_numeric_counter_coerced_without_crash(self):
        self._seed(turns=0)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump({"turns_since_memory_write": "many"}, fh)
        _run({"hook_event_name": "Stop"})
        self.assertEqual(self._state()["turns_since_memory_write"], 1)


class Case8ConcurrentOverwriteTests(_NudgeEnvTestCase):
    def test_overwrite_between_read_and_write_last_writer_wins(self):
        self._seed(turns=5)
        state = nudge._load_state()  # the read
        # A concurrent session lands its own write between read and write:
        self._seed(turns=99, watermark=50)
        state["turns_since_memory_write"] += 1
        nudge._save_state(state)  # must not raise; last writer wins
        self.assertEqual(self._state()["turns_since_memory_write"], 6,
                         "this writer's version is the surviving one")

    def test_malformed_payload_no_crash(self):
        out = _run("not json at all")
        self.assertEqual(out.strip(), "")

    def test_atomic_save_leaves_no_tmp(self):
        self._seed(turns=1)
        _run({"hook_event_name": "Stop"})
        self.assertFalse(os.path.exists(self.state_path + ".tmp"))


class Case9NeverBlocksTests(_NudgeEnvTestCase):
    """Asserted on the full output of every invocation in this file, plus a
    source-level sweep: no code path returns a blocking decision."""

    def test_no_captured_output_carries_a_blocking_decision(self):
        # Run one more of each event shape so this test never depends on order.
        self._seed(turns=50, watermark=0)
        _run({"hook_event_name": "SessionStart"})
        _run({"hook_event_name": "Stop"})
        _run({"hook_event_name": "SomethingElse"})
        for out in _ALL_OUTPUTS:
            self.assertNotIn("permissionDecision", out)
            self.assertNotIn('"decision"', out)
            self.assertNotIn('"block"', out)
            self.assertNotIn('"deny"', out)

    def test_source_has_no_decision_emission(self):
        src = _HOOK_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"permissionDecision"', src)
        self.assertNotIn('"decision": "block"', src)
        self.assertNotIn('"deny"', src)

    def test_stdlib_only_imports(self):
        import re as _re
        src = _HOOK_PATH.read_text(encoding="utf-8")
        imports = _re.findall(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)",
                              src, _re.MULTILINE)
        stdlib_ok = {"annotations", "json", "os", "sys", "datetime", "__future__"}
        self.assertTrue(set(imports).issubset(stdlib_ok),
                        "unexpected import: %s" % (set(imports) - stdlib_ok))


if __name__ == "__main__":
    unittest.main()
