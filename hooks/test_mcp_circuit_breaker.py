"""Tests for mcp-circuit-breaker.py + mcp-circuit-breaker-record.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
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


cb = _load("mcp-circuit-breaker.py", "mcp_circuit_breaker")
cbr = _load("mcp-circuit-breaker-record.py", "mcp_circuit_breaker_record")


# ---------------------------------------------------------------------------
# Helpers for redirecting state file to a tempdir
# ---------------------------------------------------------------------------

def _with_temp_state(mod, td: Path) -> tuple:
    """Return (state_dir, state_file) overrides for the module."""
    sd = td / "_state"
    sf = sd / "mcp-circuit-breaker.json"
    mod.STATE_DIR = str(sd)
    mod.STATE_FILE = str(sf)
    return sd, sf


def _run(mod, payload: dict, env: dict | None = None) -> tuple[int, str]:
    env = env or {}
    captured = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        # Defensively drop overrides if not present in env
        for k in ("MCP_HEALTH_FAIL_OPEN", "MCP_BREAKER_RESET"):
            if k not in env:
                os.environ.pop(k, None)
        rc = mod.main()
    return rc, captured.getvalue()


# ---------------------------------------------------------------------------
# ExtractServerTests
# ---------------------------------------------------------------------------

class ExtractServerTests(unittest.TestCase):
    def test_valid_mcp(self):
        self.assertEqual(cb._extract_server("mcp__qmd__query"), "qmd")
        self.assertEqual(cb._extract_server("mcp__n8n-mcp__n8n_get_workflow"), "n8n-mcp")
        self.assertEqual(
            cb._extract_server("mcp__plugin_github_github__create_issue"),
            "plugin_github_github",
        )

    def test_non_mcp_tool(self):
        self.assertIsNone(cb._extract_server("Read"))
        self.assertIsNone(cb._extract_server("Bash"))
        self.assertIsNone(cb._extract_server(""))

    def test_malformed(self):
        # Server name absent after mcp__
        self.assertIsNone(cb._extract_server("mcp__"))


# ---------------------------------------------------------------------------
# State file IO tests
# ---------------------------------------------------------------------------

class StateIOTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            _with_temp_state(cb, Path(td))
            state = {"qmd": {"failures": ["2026-05-24T00:00:00Z"], "tripped_at": None}}
            cb.save_state(state)
            roundtrip = cb.load_state()
            self.assertEqual(roundtrip, state)

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            _with_temp_state(cb, Path(td))
            self.assertEqual(cb.load_state(), {})

    def test_load_corrupt_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            sd, sf = _with_temp_state(cb, Path(td))
            sd.mkdir(parents=True, exist_ok=True)
            sf.write_text("not valid json", encoding="utf-8")
            self.assertEqual(cb.load_state(), {})


# ---------------------------------------------------------------------------
# Prune + trip-detect tests
# ---------------------------------------------------------------------------

class PruneAndTripTests(unittest.TestCase):
    def test_prune_drops_old_failures(self):
        now = datetime.now(timezone.utc)
        old = "2020-01-01T00:00:00Z"
        recent = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {"failures": [old, recent], "tripped_at": None}
        pruned = cb.prune_old_failures(state, now)
        self.assertEqual(len(pruned["failures"]), 1)
        self.assertEqual(pruned["failures"][0], recent)

    def test_not_tripped_below_threshold(self):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {"failures": [ts, ts], "tripped_at": None}  # 2 < THRESHOLD(3)
        self.assertFalse(cb.is_tripped(state, now))

    def test_tripped_at_threshold(self):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {"failures": [ts, ts, ts], "tripped_at": None}
        self.assertTrue(cb.is_tripped(state, now))

    def test_tripped_during_cooldown(self):
        now = datetime.now(timezone.utc)
        state = {
            "failures": [],
            "tripped_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        # Even with empty failures, breaker stays tripped during cooldown
        self.assertTrue(cb.is_tripped(state, now))

    def test_auto_reset_after_cooldown(self):
        # tripped_at far in the past → cooldown expired → not tripped
        state = {
            "failures": [],
            "tripped_at": "2020-01-01T00:00:00Z",
        }
        now = datetime.now(timezone.utc)
        self.assertFalse(cb.is_tripped(state, now))
        # And tripped_at should have been cleared as side effect
        self.assertIsNone(state["tripped_at"])


# ---------------------------------------------------------------------------
# Main flow tests
# ---------------------------------------------------------------------------

class MainFlowTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        _with_temp_state(cb, Path(self._td.name))
        _with_temp_state(cbr, Path(self._td.name))
        # Patch _log_event to no-op so we don't write to governance-log.jsonl
        self._patch = mock.patch.object(cb, "_log_event", lambda *a, **k: None)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._td.cleanup()

    def test_non_mcp_tool_passes(self):
        rc, out = _run(cb, {"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_mcp_tool_with_clean_state_passes(self):
        rc, out = _run(cb, {"tool_name": "mcp__qmd__query"})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_mcp_tool_below_threshold_passes(self):
        # Seed 2 recent failures
        state = {"qmd": {"failures": [cb._now_iso(), cb._now_iso()], "tripped_at": None}}
        cb.save_state(state)
        rc, out = _run(cb, {"tool_name": "mcp__qmd__query"})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_mcp_tool_at_threshold_is_denied(self):
        # Seed 3 recent failures = THRESHOLD
        state = {"qmd": {"failures": [cb._now_iso(), cb._now_iso(), cb._now_iso()], "tripped_at": None}}
        cb.save_state(state)
        rc, out = _run(cb, {"tool_name": "mcp__qmd__query"})
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("MCP CIRCUIT BREAKER", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("qmd", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_override_lets_through(self):
        state = {"qmd": {"failures": [cb._now_iso(), cb._now_iso(), cb._now_iso()], "tripped_at": None}}
        cb.save_state(state)
        rc, out = _run(
            cb,
            {"tool_name": "mcp__qmd__query"},
            env={"MCP_HEALTH_FAIL_OPEN": "1"},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_reset_request_clears_breaker(self):
        state = {"qmd": {"failures": [cb._now_iso()] * 5, "tripped_at": cb._now_iso()}}
        cb.save_state(state)
        rc, out = _run(
            cb,
            {"tool_name": "mcp__qmd__query"},
            env={"MCP_BREAKER_RESET": "qmd"},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        new_state = cb.load_state()
        self.assertEqual(new_state["qmd"]["failures"], [])
        self.assertIsNone(new_state["qmd"]["tripped_at"])

    def test_reset_for_other_server_does_not_clear_this_one(self):
        state = {"qmd": {"failures": [cb._now_iso()] * 5, "tripped_at": cb._now_iso()}}
        cb.save_state(state)
        rc, out = _run(
            cb,
            {"tool_name": "mcp__qmd__query"},
            env={"MCP_BREAKER_RESET": "different-server"},
        )
        # qmd is still tripped → expect deny
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_malformed_payload_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not-json")), \
             redirect_stdout(captured):
            rc = cb.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")


# ---------------------------------------------------------------------------
# Record-half tests (PostToolUse companion)
# ---------------------------------------------------------------------------

class RecordTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        _with_temp_state(cbr, Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def test_classify_is_error_true(self):
        self.assertEqual(cbr.classify_response({"is_error": True}), "failure")

    def test_classify_error_field(self):
        self.assertEqual(cbr.classify_response({"error": "boom"}), "failure")

    def test_classify_string_error_prefix(self):
        self.assertEqual(cbr.classify_response("Error: connection refused"), "failure")
        self.assertEqual(cbr.classify_response("MCP error: timeout"), "failure")

    def test_classify_normal_response(self):
        self.assertEqual(cbr.classify_response({"content": [{"text": "ok"}]}), "success")
        self.assertEqual(cbr.classify_response("query returned 5 results"), "success")

    def test_classify_missing_response(self):
        self.assertEqual(cbr.classify_response(None), "failure")

    def test_classify_content_with_error_text(self):
        self.assertEqual(
            cbr.classify_response({"content": [{"text": "Error: server timeout"}]}),
            "failure",
        )

    def test_record_failure_appends_timestamp(self):
        _run(cbr, {
            "tool_name": "mcp__qmd__query",
            "tool_response": {"is_error": True, "error": "timeout"},
        })
        state = cbr.load_state()
        self.assertEqual(len(state["qmd"]["failures"]), 1)

    def test_record_success_resets_failures(self):
        # Pre-load 3 failures
        state = {"qmd": {"failures": [cbr._now_iso()] * 3, "tripped_at": None}}
        cbr.save_state(state)
        _run(cbr, {
            "tool_name": "mcp__qmd__query",
            "tool_response": {"content": [{"text": "good result"}]},
        })
        new_state = cbr.load_state()
        self.assertEqual(new_state["qmd"]["failures"], [])
        self.assertIsNotNone(new_state["qmd"]["last_success_at"])

    def test_record_failures_capped_at_50(self):
        state = {"qmd": {"failures": [cbr._now_iso()] * 60, "tripped_at": None}}
        cbr.save_state(state)
        _run(cbr, {
            "tool_name": "mcp__qmd__query",
            "tool_response": {"is_error": True},
        })
        new_state = cbr.load_state()
        # 60 → trim to 50 → append 1 → 50 total
        self.assertEqual(len(new_state["qmd"]["failures"]), 50)

    def test_record_non_mcp_tool_no_state_change(self):
        rc, _ = _run(cbr, {
            "tool_name": "Read",
            "tool_response": {"is_error": True},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(cbr.load_state(), {})


# ---------------------------------------------------------------------------
# End-to-end: record failures → breaker trips → override resets → record success → cleared
# ---------------------------------------------------------------------------

class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        _with_temp_state(cb, Path(self._td.name))
        _with_temp_state(cbr, Path(self._td.name))
        self._patch = mock.patch.object(cb, "_log_event", lambda *a, **k: None)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._td.cleanup()

    def test_three_failures_then_block_then_reset_then_success(self):
        # Record 3 failures
        for _ in range(3):
            _run(cbr, {
                "tool_name": "mcp__broken-server__do_thing",
                "tool_response": {"is_error": True, "error": "boom"},
            })
        # Next PreToolUse call → blocked
        rc, out = _run(cb, {"tool_name": "mcp__broken-server__do_thing"})
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        # Reset the breaker for that server
        rc, out = _run(
            cb,
            {"tool_name": "mcp__broken-server__do_thing"},
            env={"MCP_BREAKER_RESET": "broken-server"},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        # Now record a success → state is clean
        _run(cbr, {
            "tool_name": "mcp__broken-server__do_thing",
            "tool_response": {"content": [{"text": "all good"}]},
        })
        final = cbr.load_state()
        self.assertEqual(final["broken-server"]["failures"], [])
        self.assertIsNotNone(final["broken-server"]["last_success_at"])


if __name__ == "__main__":
    unittest.main()
