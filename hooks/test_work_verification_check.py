"""Smoke tests for work-verification-check.py — Stop hook.

Three checks:
1. QA/Pentest skill invoked + report present + zero execution tools → block.
1b. Inline QA/Pentest REPORT on non-Quick without skill invocation → block.
2. Response asks user + non-Quick + < 3 tool_use blocks → block.
3. Zero-work non-Quick → soft warn only (no block).
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "work_verification_check",
    str(Path(__file__).parent / "work-verification-check.py"),
)
wvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wvc)


def _write_transcript(td: Path, events: list[dict]) -> str:
    p = td / "session.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return str(p)


def _user(text: str = "go") -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(blocks: list[dict]) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}}


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _tool(name: str, inp: dict | None = None) -> dict:
    return {"type": "tool_use", "name": name, "input": inp or {}}


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(wvc, "emit_event", None), \
         redirect_stdout(captured):
        # Patch open() for the log_path append — but that's in main(); fine as-is,
        # log writes are wrapped in try/except so they're harmless during tests.
        wvc.main()
    return captured.getvalue()


def _run_with_stderr(payload: dict) -> tuple[str, str]:
    """Return (stdout, stderr) from a hook run. Used for WARN-path assertions."""
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(wvc, "emit_event", None), \
         redirect_stdout(captured_out), \
         redirect_stderr(captured_err):
        wvc.main()
    return captured_out.getvalue(), captured_err.getvalue()


class GuardTests(unittest.TestCase):
    def test_stop_hook_active_returns_silently(self):
        out = _run({"stop_hook_active": True, "transcript_path": "/x"})
        self.assertEqual(out, "")

    def test_missing_transcript_returns_silently(self):
        out = _run({})
        self.assertEqual(out, "")

    def test_nonexistent_transcript_returns_silently(self):
        out = _run({"transcript_path": "/no/such/path.jsonl"})
        self.assertEqual(out, "")

    def test_empty_stdin_returns_silently(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            wvc.main()
        self.assertEqual(captured.getvalue(), "")

    def test_malformed_json_returns_silently(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             redirect_stdout(captured):
            wvc.main()
        self.assertEqual(captured.getvalue(), "")

    def test_no_user_message_returns_silently(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant([_text("Just an assistant response, no user msg.")]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class Check1ProcessQAExecutionTests(unittest.TestCase):
    def test_qa_skill_with_qa_report_zero_tools_blocks(self):
        # process-qa invoked + QA REPORT block + zero Read/Bash/MCP → block
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _text("QA REPORT\nPASS: 3 / 3\nFAIL: none\nUntested: none deliberately"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("ZERO tool usage", result["reason"])

    def test_qa_skill_with_read_only_passes_check1(self):
        # Read/Grep fallback is acceptable for some claim types — should NOT block
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _tool("Read", {"file_path": "/x"}),
                    _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            # Acceptable — check1 doesn't block when Read/Grep present
            self.assertEqual(out, "")

    def test_qa_skill_with_bash_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _tool("Bash", {"command": "true"}),
                    _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class Check1BehavioralClaimWarnTests(unittest.TestCase):
    def test_behavioral_claim_with_read_only_emits_warn(self):
        # process-qa invoked + QA REPORT present + only Read/Grep tools used
        # + work-item text contains a behavioral keyword → WARN to stderr, no block.
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _tool("Read", {"file_path": "/x"}),
                    _tool("Grep", {"pattern": "hook"}),
                    _text(
                        "QA REPORT\n"
                        "PASS: 1 / 1\n"
                        "FAIL: none\n"
                        "Untested: none deliberately\n\n"
                        "Verified that the hook fires on every Stop event."
                    ),
                ]),
            ])
            stdout, stderr = _run_with_stderr({"transcript_path": tp})
            # Hook must NOT block — no JSON decision on stdout
            self.assertEqual(stdout, "", "Expected no stdout (no block decision)")
            # Hook MUST emit the behavioral-claim WARN on stderr
            self.assertIn(
                "WARN: behavioral claim without execution tool",
                stderr,
                f"Expected WARN in stderr; got: {stderr!r}",
            )

    def test_non_behavioral_claim_with_read_only_is_silent(self):
        # Same setup but work-item text has no behavioral keyword → no WARN, no block.
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _tool("Read", {"file_path": "/x"}),
                    _text(
                        "QA REPORT\n"
                        "PASS: 1 / 1\n"
                        "FAIL: none\n"
                        "Untested: none deliberately\n\n"
                        "Confirmed the config file is present and the path is registered."
                    ),
                ]),
            ])
            stdout, stderr = _run_with_stderr({"transcript_path": tp})
            self.assertEqual(stdout, "", "Expected no block decision")
            self.assertNotIn("WARN: behavioral claim", stderr)


class Check1bInlineReportTests(unittest.TestCase):
    def test_inline_qa_on_non_quick_without_skill_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\n\nQA REPORT\nPASS: 2 / 2\nFAIL: none\nUntested: none"),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("bypasses the QA process", result["reason"])

    def test_inline_pentest_on_non_quick_without_skill_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\n\nPENTEST REPORT\nVerdict: SHIP\nUntested: none"),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("PENTEST REPORT", result["reason"])

    def test_inline_qa_on_quick_passes(self):
        # Quick tasks aren't required to invoke /process-qa
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none"),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_narrative_qa_mention_passes(self):
        # "the earlier QA REPORT" prose shouldn't trigger (regex requires structural marker)
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\nRecapping: the earlier QA REPORT showed PASS on all claims."),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class Check2PrematureEscalationTests(unittest.TestCase):
    def test_asks_user_non_quick_low_tools_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\n\nDo you want me to proceed?"),
                    _tool("Read", {"file_path": "/x"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("asking the user for help", result["reason"])

    def test_asks_user_non_quick_three_tools_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\n\nWould you like me to continue?"),
                    _tool("Read", {"file_path": "/a"}),
                    _tool("Grep", {"pattern": "x"}),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_asks_user_quick_low_tools_passes(self):
        # Quick + asks user is fine — soft path, no enforcement
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("Do you want me to proceed?"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class Check3ZeroWorkSoftWarnTests(unittest.TestCase):
    def test_non_quick_zero_tools_does_not_block(self):
        # Soft check — emits warn log entry but doesn't block
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Analysis\n\nHere is my reasoning..."),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class HappyPathTests(unittest.TestCase):
    def test_quick_task_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Read", {"file_path": "/x"}),
                    _text("Done."),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


# --- CHECK 4 (SA-4 file-existence / fabrication detection) tests ---
# Sprint A AC1.1 / AC1.2 / AC1.3. PRD §9 Q9 mechanism: Write-trace + path-existence
# + tool_result block parsing. Non-blocking per Q8 ergonomic framing — fires WARN
# to stderr, never blocks. CHECK 4 is a stderr-only signal; we detect it by running
# the hook as a subprocess and reading stderr, since main() doesn't return stderr.


def _run_subprocess(payload: dict) -> tuple[int, str, str]:
    """Run the hook as a subprocess to capture stderr (CHECK 4 writes WARN there)."""
    import subprocess

    hook_path = str(Path(__file__).parent / "work-verification-check.py")
    p = subprocess.run(
        ["python", hook_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return p.returncode, p.stdout, p.stderr


def _workflow_tool_use_entry(wf_name: str) -> dict:
    """assistant entry with a Workflow tool_use block (entry 1 of three-entry shape)."""
    return _assistant([_tool("Workflow", {"name": wf_name})])


def _tool_result_wrapper_entry() -> dict:
    """user entry that is a tool_result wrapper (entry 2 of three-entry shape).
    Must NOT be treated as a real user turn by the verification check."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "wf_test_b23",
                    "content": [{"type": "text", "text": "workflow subagent output"}],
                }
            ],
        },
    }


class Check1bWorkflowQANotBlockedTests(unittest.TestCase):
    """B-2 fix (2026-06-11): Workflow process-qa invocation must set has_process_qa=True
    so CHECK 1b does NOT fire ('inline QA without skill').

    Plan Step 2 acceptance criterion (iii):
    Workflow process-qa with QA REPORT in transcript must NOT trigger CHECK 1b block.
    """

    def test_b2_workflow_process_qa_with_qa_report_not_blocked_by_check1b(self):
        """Acceptance item (iii): Workflow process-qa (three-entry shape) with QA REPORT
        relay text on a non-Quick task → CHECK 1b must NOT fire."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                # Real user message (classification turn)
                _user(),
                # Workflow tool_use  — entry 1
                _workflow_tool_use_entry("process-qa"),
                # tool_result wrapper — entry 2 (not a real user turn)
                _tool_result_wrapper_entry(),
                # Relay text — entry 3 (contains QA REPORT + non-Quick classification)
                _assistant([
                    _text(
                        "TASK TYPE: Build\n\n"
                        "QA SCOPE\nClaims: 2\n\n"
                        "QA REPORT\nPASS: 2 / 2\nFAIL: none\nUntested: none deliberately"
                    ),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "", (
                "B-2: Workflow process-qa + QA REPORT must NOT trigger CHECK 1b "
                "'inline QA without skill invocation' block"
            ))

    def test_b2_workflow_scriptpath_process_qa_not_blocked(self):
        """scriptPath form: .claude/workflows/process-qa.js → same B-2 protection."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_tool("Workflow", {"scriptPath": ".claude/workflows/process-qa.js"})]),
                _tool_result_wrapper_entry(),
                _assistant([
                    _text(
                        "TASK TYPE: Research\n\n"
                        "QA SCOPE\nClaims: 1\n\n"
                        "QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"
                    ),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "", "scriptPath-based Workflow process-qa must also clear CHECK 1b")


class Check1WorkflowQAZeroToolsNotBlockedTests(unittest.TestCase):
    """B-3 fix (2026-06-11): Workflow process-qa with QA REPORT relay and ZERO main-transcript
    execution tools must NOT be blocked by CHECK 1 (zero-tool-call path).

    The workflow's Bash/MCP calls run inside the subagent and are invisible to the main
    transcript's execution_tools list — the zero-execution-tools block must be suppressed.

    Plan Step 2 acceptance criteria (iv) and (v).
    """

    def test_b3_workflow_process_qa_zero_main_transcript_tools_not_blocked(self):
        """Acceptance item (iv): Workflow process-qa + QA REPORT relay + ZERO main-transcript
        Bash/MCP/Read tool calls → CHECK 1 must NOT block."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                # Three-entry Workflow shape — no Bash/MCP/Read in any of the three entries
                _workflow_tool_use_entry("process-qa"),
                _tool_result_wrapper_entry(),
                _assistant([
                    _text(
                        "TASK TYPE: Build\n\n"
                        "QA SCOPE\nClaims: 3\n\n"
                        "QA REPORT\nPASS: 3 / 3\nFAIL: none\nUntested: none deliberately"
                    ),
                ]),
            ])
            out = _run({"transcript_path": tp})
            self.assertEqual(out, "", (
                "B-3: Workflow process-qa + QA REPORT relay + zero main-transcript "
                "execution tools must NOT be blocked by CHECK 1"
            ))


class Check1GuardIntegrityTests(unittest.TestCase):
    """B-3 guard integrity (plan Step 2 acceptance item v):
    Skill-path process-qa with zero execution tools MUST still be blocked by CHECK 1.
    Inline QA REPORT without process-qa MUST still be blocked by CHECK 1b.
    The B-3 suppression is keyed on the workflow-invocation flag, not on Workflow presence.
    """

    def test_b3_guard_skill_path_zero_tools_still_blocked(self):
        """Acceptance item (v) part A: Skill-path process-qa + QA REPORT + zero execution
        AND zero Read tools → CHECK 1 must still block. B-3 must not suppress this."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    # No Bash / MCP / Read — pure text output
                    _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block",
                             "B-3 guard: Skill-path process-qa with zero tools must still block")
            self.assertIn("ZERO tool usage", result["reason"])

    def test_b3_guard_inline_qa_without_any_skill_still_blocked_by_check1b(self):
        """Acceptance item (v) part B: inline QA REPORT on non-Quick WITHOUT any
        process-qa (Skill or Workflow) → CHECK 1b must still block.
        B-2 must not accidentally suppress this."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text("TASK TYPE: Build\n\nQA REPORT\nPASS: 2 / 2\nFAIL: none\nUntested: none"),
                    _tool("Bash", {"command": "true"}),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block",
                             "B-3 guard: inline QA without any process-qa (Skill or Workflow) must still block")
            self.assertIn("bypasses the QA process", result["reason"])

    def test_b3_guard_unrelated_workflow_does_not_suppress_check1(self):
        """Guard integrity: a Workflow tool_use for a NON-QA workflow (e.g. process-planning)
        must NOT suppress CHECK 1 for a subsequent Skill-path process-qa with zero tools.
        Suppression must be keyed on the QA-specific workflow, not any Workflow presence."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                # process-planning workflow ran first (unrelated)
                _workflow_tool_use_entry("process-planning"),
                _tool_result_wrapper_entry(),
                _assistant([_text("PLANNING SCOPE\nGoal: x")]),
                # Then process-qa was invoked via Skill (not Workflow) with zero tools
                _assistant([
                    _tool("Skill", {"skill": "process-qa"}),
                    _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"),
                ]),
            ])
            out = _run({"transcript_path": tp})
            result = json.loads(out)
            self.assertEqual(result["decision"], "block",
                             "An unrelated Workflow before Skill-path process-qa must not suppress CHECK 1")


class Check4FileExistenceTests(unittest.TestCase):
    """CHECK 4 — fabrication detection. WARN to stderr, no block."""

    def test_tp_fabricated_tmp_path_fires_fabrication_detected(self):
        """TP1: agent claims Write to /tmp/nonexistent path → FABRICATION_DETECTED."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text(
                        "TASK TYPE: Build\nI wrote the report to "
                        "/tmp/nonexistent_sa5_xyz_2026.md."
                    ),
                ]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertIn("FABRICATION_DETECTED", stderr)
            self.assertIn("/tmp/nonexistent_sa5_xyz_2026.md", stderr)

    def test_tp_subagent_tool_result_fabrication_fires(self):
        """TP2: sub-agent tool_result block claims Write to nonexistent path → fires.
        Q9 mechanism explicitly requires tool_result parsing, not just assistant blocks."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text("TASK TYPE: Build\nDispatching sub-agent.")]),
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "sub_1",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "I created the design at "
                                            "/tmp/fake_subagent_design_sa5.md as "
                                            "requested."
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                },
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertIn("FABRICATION_DETECTED", stderr)
            self.assertIn("/tmp/fake_subagent_design_sa5.md", stderr)

    def test_fp_write_trace_present_silent(self):
        """FP-guard 1: Write tool_use in trace → not a fabrication, silent."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _tool("Write", {
                        "file_path": "Projects/Agent-Governance-Research/STATE.md",
                        "content": "x",
                    }),
                    _text(
                        "TASK TYPE: Build\n"
                        "I wrote the file to "
                        "Projects/Agent-Governance-Research/STATE.md."
                    ),
                ]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_fp_failure_language_guard_silent(self):
        """FP-guard 2: agent says 'I tried to write X but failed' → silent.
        Failure-language window (100 chars) catches legitimate failure reports."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text(
                        "TASK TYPE: Build\n"
                        "I tried to write the report to /tmp/blocked_sa5.md "
                        "but the operation failed with a permission error."
                    ),
                ]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_fp_no_write_claim_language_silent(self):
        """FP-guard 3: agent returns inline content without Write-claim language → silent.
        Some agents legitimately return content inline; only Write-claim-language fires."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text(
                        "TASK TYPE: Analysis\n"
                        "Here is my analysis: the system behaves correctly under "
                        "load. No file output produced."
                    ),
                ]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_fp_subagent_reports_write_failure_silent(self):
        """FP-guard 4 (adversarial CR): sub-agent reports legitimate Write failure → silent.
        Critical case: 'I attempted to write X but Write returned an error.'
        The path is fabricated-looking (doesn't exist) BUT failure-language guard wins."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text("TASK TYPE: Build\nDispatching sub-agent.")]),
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "sub_2",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "I attempted to write the design to "
                                            "/tmp/blocked_subagent_sa5.md but the "
                                            "Write tool returned an error: permission "
                                            "denied. Reporting failure rather than "
                                            "fabricating completion."
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                },
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_existing_real_path_not_fabrication(self):
        """Edge case: claim references an EXISTING file with no Write trace.
        Per Q9 mechanism: if path exists on disk, it's not a fabrication
        (it might have been created in a prior turn). Silent.
        Note: this test uses a path that must exist in the adopter's installation.
        Substitute a real path from your project if this test fails on a fresh clone."""
        # Use a known-existing file relative to the vault root (hooks/ dir is 2 levels down)
        existing = "hooks/work-verification-check.py"
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([
                    _text(
                        f"TASK TYPE: Build\nThe report was saved at {existing} "
                        "from an earlier turn."
                    ),
                ]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)


if __name__ == "__main__":
    unittest.main()
