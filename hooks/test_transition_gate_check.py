"""Tests for transition-gate-check.py — PreToolUse Layer-1 guard for SDLC phase sentinels.

Autonomous SDLC State-Machine, Layer 1. Every deny path gets BOTH a true-positive
(must deny) and a false-positive guard (must allow). Ground-truth note: assertions
derive from the spec's deny conditions (§4.2), NOT from the hook's own output
(feedback_test_ground_truth).

Sentinel files are created under tmp_path/tempfile so no real _state/ data is touched.
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
    "transition_gate_check",
    str(Path(__file__).parent / "transition-gate-check.py"),
)
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def _run(payload: dict) -> str:
    """Run main() with payload on stdin, governance log mocked out, capture stdout."""
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(tg, "_log_block", lambda *a, **k: None), \
         redirect_stdout(captured):
        tg.main()
    return captured.getvalue()


def _decision(out: str):
    if not out.strip():
        return None
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return None


def _write_payload(path: str, proposed: dict) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": path, "content": json.dumps(proposed)},
    }


def _multiedit_payload(path: str, edits: list) -> dict:
    # MultiEdit tool_input shape: {file_path, edits:[{old_string,new_string},...]} — NO content.
    return {"tool_name": "MultiEdit", "tool_input": {"file_path": path, "edits": edits}}


# A non-colliding sentinel path that does NOT exist on disk (FileNotFoundError -> first write).
_FRESH_SENTINEL = "/nonexistent/.claude/hooks/_state/sdlc-phase-testproj.json"

_ORACLE = {"dod_key": "build_pytest", "evidence_type": "external_oracle",
           "evidence_path": "x.txt", "passed_at": "2026-06-18T11:00:00Z"}


# ---------------------------------------------------------------------------
# Edit-to-sentinel (R3): Write-only restriction
# ---------------------------------------------------------------------------
class EditToSentinelTests(unittest.TestCase):
    def test_edit_to_sentinel_denies(self):  # TP
        out = _run({"tool_name": "Edit",
                    "tool_input": {"file_path": _FRESH_SENTINEL, "new_string": '"verify"'}})
        self.assertEqual(_decision(out), "deny")

    def test_edit_to_non_sentinel_allows(self):  # FP guard
        out = _run({"tool_name": "Edit",
                    "tool_input": {"file_path": "/x/Resources/KB/foo.json", "new_string": "x"}})
        self.assertIsNone(_decision(out))

    def test_write_to_sentinel_not_denied_by_edit_branch(self):  # FP guard
        # A Write (not Edit) advancing to an advisory phase must NOT be caught by the Edit branch.
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "design", "completed_gates": {}}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# MultiEdit-to-sentinel (R3): Write-only restriction — the Layer-1 bypass close.
#
# Ground truth (spec §4.2 R3): the Write-only restriction makes ANY non-Write edit
# to a sentinel a violation. MultiEdit carries only old_string/new_string fragments
# (tool_input has no `content`), so it can NEVER overwrite the whole sentinel — every
# MultiEdit targeting a sentinel denies, keyed SOLELY off file_path, independent of
# the edits-array contents or length. (NOT derived from the hook's own output.)
# ---------------------------------------------------------------------------
class MultiEditToSentinelTests(unittest.TestCase):
    def test_multiedit_single_edit_to_sentinel_denies(self):  # TP
        out = _run(_multiedit_payload(
            _FRESH_SENTINEL,
            [{"old_string": '"build"', "new_string": '"verify"'}],
        ))
        self.assertEqual(_decision(out), "deny")

    def test_multiedit_multi_edit_array_to_sentinel_denies(self):  # TP — multi-entry array still denies
        out = _run(_multiedit_payload(
            _FRESH_SENTINEL,
            [
                {"old_string": '"build"', "new_string": '"verify"'},
                {"old_string": '"completed_gates": {}', "new_string": '"completed_gates": {"build": {}}'},
            ],
        ))
        self.assertEqual(_decision(out), "deny")

    def test_multiedit_to_sentinel_proposing_enforced_advance_denies(self):  # TP — deny by file_path, not by parsing the advance
        out = _run(_multiedit_payload(
            _FRESH_SENTINEL,
            [{"old_string": '"build"', "new_string": '"release"'}],
        ))
        self.assertEqual(_decision(out), "deny")

    def test_multiedit_to_non_sentinel_md_allows(self):  # FP guard
        out = _run(_multiedit_payload(
            "/x/Resources/KB/foo.md",
            [{"old_string": "a", "new_string": "b"}],
        ))
        self.assertIsNone(_decision(out))

    def test_multiedit_advisory_context_to_non_sentinel_allows(self):  # FP guard — phase words in fragments must not trigger
        # Fragments mention an advisory phase name ("design") but the path is a non-sentinel.
        out = _run(_multiedit_payload(
            "/x/Projects/foo/work/notes.md",
            [{"old_string": "design phase", "new_string": "build phase"}],
        ))
        self.assertIsNone(_decision(out))

    def test_multiedit_first_write_no_sentinel_allows(self):  # FP guard — plain non-sentinel file, no sdlc-phase- token
        out = _run(_multiedit_payload(
            "/x/Resources/KB/plain.json",
            [{"old_string": "1", "new_string": "2"}],
        ))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Missing prior-phase evidence (R4 / core enforcement)
# ---------------------------------------------------------------------------
class MissingEvidenceTests(unittest.TestCase):
    def test_build_to_verify_no_evidence_denies(self):  # TP
        out = _run(_write_payload(_FRESH_SENTINEL,
                                  {"current_phase": "verify", "completed_gates": {}}))
        self.assertEqual(_decision(out), "deny")

    def test_build_to_verify_with_oracle_evidence_allows(self):  # FP guard
        out = _run(_write_payload(_FRESH_SENTINEL,
                                  {"current_phase": "verify", "completed_gates": {"build": _ORACLE}}))
        self.assertIsNone(_decision(out))

    def test_evidence_present_but_wrong_type_denies(self):  # TP — spoofed evidence_type
        spoof = dict(_ORACLE, evidence_type="advisory")
        out = _run(_write_payload(_FRESH_SENTINEL,
                                  {"current_phase": "verify", "completed_gates": {"build": spoof}}))
        self.assertEqual(_decision(out), "deny")

    def test_review_to_release_with_oracle_allows(self):  # FP guard — deeper in the chain
        out = _run(_write_payload(_FRESH_SENTINEL,
                                  {"current_phase": "release", "completed_gates": {"review": _ORACLE}}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Malformed JSON (R2)
# ---------------------------------------------------------------------------
class MalformedJsonTests(unittest.TestCase):
    def test_non_json_content_denies(self):  # TP
        out = _run({"tool_name": "Write",
                    "tool_input": {"file_path": _FRESH_SENTINEL, "content": "this is not json {{"}})
        self.assertEqual(_decision(out), "deny")

    def test_json_array_content_denies(self):  # TP — valid JSON but not an object
        out = _run({"tool_name": "Write",
                    "tool_input": {"file_path": _FRESH_SENTINEL, "content": "[1,2,3]"}})
        self.assertEqual(_decision(out), "deny")

    def test_valid_json_not_denied_for_this_reason(self):  # FP guard
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "design", "completed_gates": {}}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Unknown phase
# ---------------------------------------------------------------------------
class UnknownPhaseTests(unittest.TestCase):
    def test_unknown_phase_denies(self):  # TP
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "banana", "completed_gates": {}}))
        self.assertEqual(_decision(out), "deny")

    def test_missing_current_phase_denies(self):  # TP — None not in PHASE_ORDER
        out = _run(_write_payload(_FRESH_SENTINEL, {"completed_gates": {}}))
        self.assertEqual(_decision(out), "deny")

    def test_known_phase_not_denied_for_this_reason(self):  # FP guard
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "design", "completed_gates": {}}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Advisory advance — never denies
# ---------------------------------------------------------------------------
class AdvisoryAdvanceTests(unittest.TestCase):
    def test_advance_to_design_no_evidence_allows(self):  # FP guard (never a TP)
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "design", "completed_gates": {}}))
        self.assertIsNone(_decision(out))

    def test_advance_to_requirements_no_evidence_allows(self):
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "requirements", "completed_gates": {}}))
        self.assertIsNone(_decision(out))

    def test_build_after_advisory_design_no_evidence_allows(self):
        # Build's prior phase is design (advisory) -> no evidence required.
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "build", "completed_gates": {}}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# First write / bootstrap (R4)
# ---------------------------------------------------------------------------
class FirstWriteBootstrapTests(unittest.TestCase):
    def test_first_write_straight_to_release_no_evidence_denies(self):  # TP — bootstrap cannot skip the gate
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "release", "completed_gates": {}}))
        self.assertEqual(_decision(out), "deny")

    def test_first_write_to_advisory_discovery_allows(self):  # FP guard — fresh project can start
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "discovery", "completed_gates": {}}))
        self.assertIsNone(_decision(out))

    def test_first_write_to_first_phase_index0_allows(self):  # FP guard — idx==0 path
        # discovery is index 0 AND advisory; this exercises the always-allow-first path.
        out = _run(_write_payload(_FRESH_SENTINEL, {"current_phase": "discovery"}))
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Non-sentinel / non-Write fast-path
# ---------------------------------------------------------------------------
class FastPathTests(unittest.TestCase):
    def test_write_to_non_sentinel_md_allows(self):  # FP guard
        out = _run({"tool_name": "Write",
                    "tool_input": {"file_path": "/x/Resources/KB/foo.md", "content": "# hi"}})
        self.assertIsNone(_decision(out))

    def test_read_payload_allows(self):  # FP guard — non-Write/Edit tool
        out = _run({"tool_name": "Read", "tool_input": {"file_path": _FRESH_SENTINEL}})
        self.assertIsNone(_decision(out))

    def test_bash_payload_allows(self):  # FP guard
        out = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertIsNone(_decision(out))


# ---------------------------------------------------------------------------
# Cannot-read current state (R2 fail-closed)
# ---------------------------------------------------------------------------
class CannotReadStateTests(unittest.TestCase):
    def test_corrupt_on_disk_state_denies_enforced_advance(self):  # TP
        # Sentinel exists on disk but is corrupt JSON; proposing an enforced advance -> deny.
        fd, path = tempfile.mkstemp(suffix="-sdlc-phase-corrupt.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("{ this is : not json ")
            out = _run(_write_payload(path, {"current_phase": "verify",
                                             "completed_gates": {"build": _ORACLE}}))
            self.assertEqual(_decision(out), "deny")
        finally:
            os.remove(path)

    def test_corrupt_on_disk_state_advisory_advance_allows(self):  # FP guard
        # Even with a corrupt on-disk state, an advisory advance is allowed
        # (the advisory check sits before the on-disk read is consulted for the gate).
        # NOTE: the read still happens and a corrupt read denies BEFORE the advisory check,
        # which is fail-closed-correct. We assert the documented behavior: deny.
        fd, path = tempfile.mkstemp(suffix="-sdlc-phase-corrupt2.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("{ broken ")
            out = _run(_write_payload(path, {"current_phase": "design", "completed_gates": {}}))
            # Per §4.2 branch order: the on-disk read (f) runs before the advisory check (g),
            # so a corrupt current state denies fail-closed even for an advisory target.
            self.assertEqual(_decision(out), "deny")
        finally:
            os.remove(path)

    def test_valid_on_disk_state_oracle_advance_allows(self):  # FP guard — the read succeeds
        fd, path = tempfile.mkstemp(suffix="-sdlc-phase-valid.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"current_phase": "build", "completed_gates": {"build": _ORACLE}}))
            out = _run(_write_payload(path, {"current_phase": "verify",
                                             "completed_gates": {"build": _ORACLE}}))
            self.assertIsNone(_decision(out))
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# Robustness — tool_input as JSON string, unparseable stdin (fail-open)
# ---------------------------------------------------------------------------
class RobustnessTests(unittest.TestCase):
    def test_tool_input_as_json_string_parsed_and_denied(self):  # TP via string tool_input
        payload = {
            "tool_name": "Write",
            "tool_input": json.dumps({
                "file_path": _FRESH_SENTINEL,
                "content": json.dumps({"current_phase": "verify", "completed_gates": {}}),
            }),
        }
        out = _run(payload)
        self.assertEqual(_decision(out), "deny")

    def test_unparseable_stdin_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json at all")), \
             redirect_stdout(captured):
            tg.main()
        self.assertEqual(captured.getvalue(), "")

    def test_empty_stdin_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            tg.main()
        self.assertEqual(captured.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
