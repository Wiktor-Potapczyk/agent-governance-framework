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


class SelfQaWarnTests(unittest.TestCase):
    """2026-09-21: nothing recorded whether the verifier was the builder. The
    one controlled comparison in the record (Module-8B, 2026-09-18) had a
    main-session self-check at 6/6 and an independent rerun of the same six
    claims at 5/6. A Build turn that files its QA through the Skill path in
    the main session is a self-check; the hook now says so on stderr (WARN,
    never a block) so the entry carries the fact."""

    def _turn(self, tools, task_type="Build", via_workflow=False):
        blocks = [_text(f"IMPLIES: x\nTASK TYPE: {task_type}\nAPPROACH: a\nMISSED: m\nMUST DISPATCH: process-qa")]
        if via_workflow:
            blocks.append(_tool("Workflow", {"scriptPath": "C:/x/.claude/workflows/process-qa.js"}))
        else:
            blocks.append(_tool("Skill", {"skill": "process-qa"}))
        blocks.extend(_tool(t, {"command": "true"}) for t in tools)
        blocks.append(_text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately"))
        return [_user(), _assistant(blocks)]

    def test_a_build_turn_filing_its_own_qa_is_warned(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), self._turn(["Bash"]))
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertEqual(out, "")
            self.assertIn("SELF-QA", err)

    def test_a_workflow_qa_is_not_warned(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), self._turn([], via_workflow=True))
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertEqual(out, "")
            self.assertNotIn("SELF-QA", err)

    def test_an_analysis_turn_is_warned_too(self):
        """Build review N9: the self-check warning covered Build only. A
        self-verified Analysis or Planning is the same shape."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), self._turn(["Bash"], task_type="Analysis"))
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertEqual(out, "")
            self.assertIn("SELF-QA", err)

    def test_a_quick_turn_is_not_warned(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), self._turn(["Bash"], task_type="Quick"))
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertNotIn("SELF-QA", err)

    def test_read_only_bash_on_a_qa_turn_is_named(self):
        """Build review N9: Bash counted as execution whatever it ran. When every
        Bash call of a QA turn is a read, the turn is told so."""
        with tempfile.TemporaryDirectory() as td:
            blocks = [_text("IMPLIES: x\nTASK TYPE: Build\nAPPROACH: a\nMISSED: m\nMUST DISPATCH: process-qa"),
                      _tool("Skill", {"skill": "process-qa"}),
                      _tool("Bash", {"command": "cat .claude/hooks/x.py"}),
                      _tool("Bash", {"command": "sed -n 1,40p .claude/hooks/x.py | head"}),
                      _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately")]
            tp = _write_transcript(Path(td), [_user(), _assistant(blocks)])
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertEqual(out, "")
            self.assertIn("READ-ONLY-QA", err)

    def test_a_real_run_on_a_qa_turn_is_not_flagged_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            blocks = [_text("IMPLIES: x\nTASK TYPE: Build\nAPPROACH: a\nMISSED: m\nMUST DISPATCH: process-qa"),
                      _tool("Skill", {"skill": "process-qa"}),
                      _tool("Bash", {"command": "cat .claude/hooks/x.py"}),
                      _tool("Bash", {"command": "echo {} | python .claude/hooks/x.py"}),
                      _text("QA REPORT\nPASS: 1 / 1\nFAIL: none\nUntested: none deliberately")]
            tp = _write_transcript(Path(td), [_user(), _assistant(blocks)])
            out, err = _run_with_stderr({"transcript_path": tp})
            self.assertNotIn("READ-ONLY-QA", err)


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
        relay text on a non-Quick task → CHECK 1b must NOT fire.

        End-to-end: runs the hook as a real subprocess over the stdin→stdout
        protocol (no monkeypatching; emit_event intentionally left live,
        matching the CHECK-4 subprocess precedent)."""
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
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertEqual(stdout, "", (
                "B-2: Workflow process-qa + QA REPORT must NOT trigger CHECK 1b "
                "'inline QA without skill invocation' block"
            ))
            self.assertEqual(rc, 0, "hook must exit 0 (no block) for Workflow process-qa")

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

    def test_r18_project_nested_relative_claim_silent(self):
        """R18 tune: a bare project-relative claim whose file exists under
        Projects/<name>/ is not a fabrication (sampling: 0 of 17 real)."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text(
                    "TASK TYPE: Build\n"
                    "Saved to "
                    "work/2026-09-06-mine-sig-sampling.md for review."
                )]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_r18_bare_state_md_claim_silent(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text(
                    "TASK TYPE: Build\n"
                    "Progress was written to STATE.md today."
                )]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_r18_tilde_path_existing_silent(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text(
                    "TASK TYPE: Build\n"
                    "The key is already stored at "
                    "~/.claude/CLAUDE.md by an earlier session."
                )]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_r18_markdown_link_capture_silent(self):
        """R18 tune: a markdown self-link swallows '](path' into the capture;
        the path part alone exists, so no fabrication."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text(
                    "TASK TYPE: Build\n"
                    "Saved to "
                    "[Resources/KB/index.md](Resources/KB/index.md) as planned."
                )]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertNotIn("FABRICATION_DETECTED", stderr)

    def test_r18_truly_missing_relative_path_still_fires(self):
        """Detector not neutered: a relative claim matching nothing anywhere
        (root, expanduser, Projects globs) still fires."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _user(),
                _assistant([_text(
                    "TASK TYPE: Build\n"
                    "Saved to "
                    "work/zz-no-such-file-r18-fixture.md just now."
                )]),
            ])
            rc, stdout, stderr = _run_subprocess({"transcript_path": tp})
            self.assertIn("FABRICATION_DETECTED", stderr)

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
        (it might have been created in a prior turn). Silent."""
        # Use a known-existing file in the vault
        existing = "Projects/Agent-Governance-Research/STATE.md"
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


class SessionWiringTests(unittest.TestCase):
    """Defect 2 (2026-08-07): the entry-point log_fire() call fired before
    session was ever wired in, always logging session=None even though
    `payload` (with session_id) was already in scope. Reproduces the broken
    shape first (a synthetic Stop-hook invocation with a populated
    session_id), then asserts it populates."""

    def test_session_populates_from_payload(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": activity_log}):
                _run({"session_id": "test-workverify-1"})
            self.assertTrue(os.path.exists(activity_log))
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hook"], "work-verification-check")
        self.assertEqual(records[0]["session"], "test-workverify-1")


if __name__ == "__main__":
    unittest.main()


# --- harness audit 1 (2026-09-21): the turn starts at the user -----------------

def _skill_body() -> dict:
    """The real shape of the entry Claude Code appends after a Skill call
    (session 7a74290c line 1702): a user entry with a text block, isMeta and a
    sourceToolUseID. It is not the user."""
    return {"type": "user", "isMeta": True, "sourceToolUseID": "toolu_01", "message": {"role": "user", "content": [
        {"type": "text", "text": "Base directory for this skill: C:/x/.claude/skills/process-qa\n# QA\n..."}]}}


def _tool_result(tid: str = "t1") -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


def _cls(task_type: str = "Build") -> dict:
    return _text(f"IMPLIES: x\nTASK TYPE: {task_type}\nAPPROACH: a\nMISSED: m\nMUST DISPATCH: process-qa")


_QA = _text("QA SCOPE: 1 claims, detail in Demo/work/qa-log.md\nQA REPORT:\nPASS: 1 / 1 | FAIL: none | Untested: none deliberately | Verifier: main-session")
_HOOK_FEEDBACK = "Stop hook feedback:\nWORK VERIFICATION: QA REPORT block produced on a non-Quick task without invoking /process-qa"


class TurnBoundaryTests(unittest.TestCase):
    """W1 and W2 of the dispatch-and-work-verification evaluation: the skill body
    and the hook feedback are user entries that are not the user. Taking them as
    the turn start hid the classification, the Skill call and earlier tools."""

    def test_a_qa_report_with_zero_tools_after_the_skill_body_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]),
                      _tool_result("t0"), _skill_body(), _assistant([_QA])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out, out)
            self.assertIn("ZERO tool usage", out)

    def test_an_inline_qa_report_after_another_skills_body_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "n8n-patterns"})]),
                      _tool_result("t0"), _skill_body(), _assistant([_QA])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out, out)
            self.assertIn("without invoking /process-qa", out)

    def test_tools_before_the_skill_body_count(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Bash", {"command": "python x.py"})]), _tool_result("t1"),
                      _assistant([_tool("Skill", {"skill": "process-qa"})]), _tool_result("t2"), _skill_body(), _assistant([_QA])]
            out, err = _run_with_stderr({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)
            self.assertIn("SELF-QA", err)

    def test_re_posting_a_blocked_report_on_the_retry_is_blocked_again(self):
        """Three real cases in the owner's session 7a74290c (lines 1715, 1857,
        2315): blocked for an inline QA report, then the same report re-posted
        with no tools and no skill call, and passed."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls("Analysis")]), _assistant([_tool("Bash", {"command": "python x.py"})]), _tool_result("t1"),
                      _assistant([_QA]), _user(_HOOK_FEEDBACK), _assistant([_QA])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out, out)
            self.assertIn("without invoking /process-qa", out)

    def test_a_retry_that_invokes_the_skill_and_runs_something_passes(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls("Analysis")]), _assistant([_QA]), _user(_HOOK_FEEDBACK),
                      _assistant([_tool("Skill", {"skill": "process-qa"})]), _tool_result("t2"), _skill_body(),
                      _assistant([_tool("Bash", {"command": "python x.py"})]), _tool_result("t3"), _assistant([_QA])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)

    def test_a_new_user_message_after_the_skill_body_starts_a_new_turn(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tool_result("t0"), _skill_body(),
                      _assistant([_text("ok")]), _user("thanks, what is the weather"), _assistant([_text("I cannot check that.")])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)


# --- harness audit 1, review findings A3, A7, A8, A9, A10, S1, S9 ----------------

def _run_capturing(payload: dict) -> tuple[str, str, list]:
    """Run the hook with a recording emit_event, returning (stdout, stderr, events)."""
    events: list = []

    def fake(event, hook, session, extra=None, environment=None):
        events.append({"event": event, "hook": hook, **(extra or {})})

    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(wvc, "emit_event", fake), \
         redirect_stdout(out), redirect_stderr(err):
        wvc.main()
    return out.getvalue(), err.getvalue(), events


def _tres(tid: str, content: str = "ok") -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": content}]}}


class ReviewFindingsTests(unittest.TestCase):

    def test_a_bolded_qa_report_is_still_a_qa_report(self):
        """Review A3: markdown decoration around the header hid the report from CHECK 1."""
        for header in ("**QA REPORT**", "**QA REPORT:**", "## QA REPORT", "> QA REPORT"):
            with tempfile.TemporaryDirectory() as td:
                events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                          _assistant([_text(f"{header}\nPASS: 3 / 3\nFAIL: none\nUntested: none deliberately")])]
                out = _run({"transcript_path": _write_transcript(Path(td), events)})
                self.assertIn('"block"', out, header)
                self.assertIn("ZERO tool usage", out, header)

    def test_a_headered_inline_report_without_the_skill_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_text("## QA REPORT\nPASS: 2 / 2\nFAIL: none")])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn("without invoking /process-qa", out)

    def test_invoking_process_qa_without_a_verdict_is_blocked(self):
        """Review A9: Skill(process-qa) satisfied dispatch-compliance and, with no
        report written, work-verification had nothing to check."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                      _assistant([_tool("Bash", {"command": "python x.py"})]), _tres("t1"), _assistant([_text("Done, the work is complete.")])]
            out, _, events_seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out, out)
            self.assertIn("without a verdict", out)
            self.assertTrue(any(e.get("check") == "qa-invoked-without-verdict" for e in events_seen), events_seen)

    def test_the_no_claims_line_is_a_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                      _assistant([_text("no verifiable claims\n\nNothing here can be run.")])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)

    def test_three_identical_calls_do_not_satisfy_the_escalation_gate(self):
        """Review A8: CHECK 2 counted calls, not approaches."""
        read = _tool("Read", {"file_path": "C:/x.py"})
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([read]), _tres("t1"), _assistant([read]), _tres("t2"), _assistant([read]), _tres("t3"),
                      _assistant([_text("Would you like me to take approach A or approach B?")])]
            out, _, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out, out)
            self.assertTrue(any(e.get("check") == "premature-escalation" for e in seen), seen)
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([read]), _tres("t1"),
                      _assistant([_tool("Grep", {"pattern": "x"})]), _tres("t2"), _assistant([_tool("Bash", {"command": "python x.py"})]), _tres("t3"),
                      _assistant([_text("Would you like me to take approach A or approach B?")])]
            out = _run({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)

    def test_the_zero_tool_block_writes_an_event(self):
        """Review A7: CHECK 1 and CHECK 2 blocks left no governance event."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(), _assistant([_QA])]
            out, _, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out)
            self.assertTrue(any(e.get("event") == "block" and e.get("check") == "zero-tool-qa" for e in seen), seen)

    def test_the_warnings_write_events_too(self):
        """Review A10: SELF-QA and READ-ONLY-QA were stderr-only."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                      _assistant([_tool("Bash", {"command": "cat x.py"})]), _tres("t1", "print(1)"), _assistant([_QA])]
            out, err, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)
            self.assertIn("SELF-QA", err)
            self.assertIn("READ-ONLY-QA", err, "silent-failure item 9: the read-only warning never fired on a real transcript shape")
            checks = {e.get("check") for e in seen if e.get("event") == "warn"}
            self.assertIn("self-qa", checks)
            self.assertIn("read-only-qa", checks)

    def test_a_tool_result_larger_than_the_old_window_does_not_hide_the_turn(self):
        """Silent-failure item 1: one 300 KB tool_result pushed the classification
        and the Skill call out of the fixed 200 KB tail."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                      _assistant([_tool("Bash", {"command": "cat big"})]), _tres("t1", "x" * 300_000), _assistant([_QA])]
            out, err, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)
            self.assertIn("READ-ONLY-QA", err)

    def test_the_pass_event_names_the_boundary_it_used(self):
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "process-qa"})]), _tres("t0"), _skill_body(),
                      _assistant([_tool("Bash", {"command": "python x.py"})]), _tres("t1"), _assistant([_QA])]
            out, _, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)
            passes = [e for e in seen if e.get("event") == "pass"]
            self.assertEqual(len(passes), 1, seen)
            self.assertEqual(passes[0].get("turn_boundary"), "skill-body")
            self.assertEqual(passes[0].get("tool_count"), 1)  # Skill alone is not work; the Bash call is
            self.assertEqual(passes[0].get("task_type"), "build")


class ArchitectReviewTests(unittest.TestCase):
    """Architect review of the audit-1 build (2026-09-21): findings 2, 3, 4, 6, 8."""

    def test_a_fenced_quote_of_the_templates_is_not_a_report_or_a_classification(self):
        """Finding 2: no fence stripping here while the sibling hook got it, and the
        widened header regex made a quoted template a hard false block."""
        with tempfile.TemporaryDirectory() as td:
            quote = ("Here is what the classifier and QA blocks look like, as documentation only:\n```\nIMPLIES: x\nTASK TYPE: Build\n"
                     "MUST DISPATCH: process-qa\n```\nand\n```\nQA REPORT\nPASS: 3 / 3\nFAIL: none\n```\nThat is not this turn.")
            events = [_user("what do the blocks look like?"), _assistant([_text(quote)])]
            out, _, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertEqual(out, "", out)
            self.assertFalse(any(e.get("event") == "block" for e in seen), seen)

    def test_a_missing_boundary_helper_is_said_on_stderr(self):
        """Finding 3: the fallback to the old rule was silent, and the old rule is
        the W2 bug this plan closes."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Bash", {"command": "python x.py"})]), _tres("t1"), _assistant([_text("done")])]
            tp = _write_transcript(Path(td), events)
            err = io.StringIO()
            with mock.patch.dict(sys.modules, {"_turn_boundary": None}), \
                 mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"transcript_path": tp}))), \
                 mock.patch.object(wvc, "emit_event", None), redirect_stdout(io.StringIO()), redirect_stderr(err):
                wvc.main()
            self.assertIn("_turn_boundary", err.getvalue())

    def test_the_fabrication_check_survives_a_non_dict_line(self):
        """Finding 4: CHECK 4 kept its own boundary scan and crashed on a list line,
        failing the whole hook open."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Bash", {"command": "python x.py"})]), _tres("t1"),
                      _assistant([_text("I wrote the file to Projects/Nowhere/work/ghost.md and it is done.")])]
            tp = _write_transcript(Path(td), events)
            with open(tp, "a", encoding="utf-8") as fh:
                fh.write("[1, 2, 3]\n")
            out, _, seen = _run_capturing({"transcript_path": tp})
            self.assertTrue(any(e.get("event") == "fabrication_detected" for e in seen), seen)

    def test_a_misspelt_task_type_is_non_quick_here_too(self):
        """Finding 8: plan task 7 shipped without a test in this file."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls("Bild")]), _assistant([_QA])]
            out, err, _ = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn("without invoking /process-qa", out)
            self.assertIn("bild", err.lower())

    def test_every_block_event_names_the_boundary(self):
        """Finding 6: two of the four block paths lacked turn_boundary."""
        with tempfile.TemporaryDirectory() as td:
            events = [_user("build it"), _assistant([_cls()]), _assistant([_tool("Skill", {"skill": "n8n-patterns"})]), _tres("t0"), _skill_body(), _assistant([_QA])]
            out, _, seen = _run_capturing({"transcript_path": _write_transcript(Path(td), events)})
            self.assertIn('"block"', out)
            blocks = [e for e in seen if e.get("event") == "block"]
            self.assertTrue(blocks and all("turn_boundary" in e for e in blocks), seen)
