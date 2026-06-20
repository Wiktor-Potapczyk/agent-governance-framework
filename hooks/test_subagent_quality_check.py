"""Smoke tests for subagent-quality-check.py: SubagentStop hook.

Covers the three block checks (empty output, error-refusal short output,
substantial-output-without-structure), the pass path on a well-structured
response, and the fail-open path on malformed input.
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
    "subagent_quality_check",
    str(Path(__file__).parent / "subagent-quality-check.py"),
)
sqc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sqc)

# Pure detection logic (extracted 2026-06-02): the boundary tests below exercise
# it directly (no I/O, no log writes).
from _subagent_quality_logic import classify_subagent_output  # noqa: E402


def _blocked(msg: str) -> bool:
    return classify_subagent_output(msg)[0]


def _run(payload: dict, log_dir: Path) -> tuple[int, str]:
    """Invoke main() with stdin=payload, log files redirected to log_dir."""
    payload_str = json.dumps(payload)
    captured = io.StringIO()
    exit_code = None
    # Redirect log_path and gov_log_path by patching os.path.dirname of __file__
    with mock.patch.object(sqc.os.path, "abspath", return_value=str(log_dir / "subagent-quality-check.py")), \
         mock.patch.object(sys, "stdin", io.StringIO(payload_str)), \
         redirect_stdout(captured):
        try:
            sqc.main()
        except SystemExit as e:
            exit_code = e.code
    return (exit_code if exit_code is not None else 0), captured.getvalue()


class CheckEmptyOutputTests(unittest.TestCase):
    def test_empty_output_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test-agent",
                "agent_id": "abc",
                "last_assistant_message": "",
                "transcript_path": "/tmp/session-x.jsonl",
            }, Path(td))
            self.assertEqual(rc, 0)
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("empty", result["reason"].lower())

    def test_three_char_output_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": "ok",
                "transcript_path": "",
            }, Path(td))
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")


class CheckErrorRefusalTests(unittest.TestCase):
    def test_short_apology_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": "I apologize but I cannot help with this task.",
                "transcript_path": "",
            }, Path(td))
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("error or refusal", result["reason"].lower())

    def test_short_cannot_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": "I cannot complete this.",
                "transcript_path": "",
            }, Path(td))
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")

    def test_long_response_with_error_word_does_not_block(self):
        # Error keyword present but message > 100 chars → check 2 skipped, check 3 evaluated
        msg = "I cannot tell you why this happened. Here is what I found.\n\n" + ("# Section\n\n- bullet\n" * 5)
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": msg,
                "transcript_path": "",
            }, Path(td))
            # Should pass: message > 100 chars AND has structure (# header + bullets)
            self.assertEqual(out, "")


class CheckNoStructureTests(unittest.TestCase):
    def test_long_unstructured_blocks(self):
        # >500 chars of plain prose, no headers/bullets/tables/code/numbered
        prose = "This is plain prose. " * 30  # ~570 chars
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": prose,
                "transcript_path": "",
            }, Path(td))
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("no structure", result["reason"].lower())

    def test_long_with_headers_passes(self):
        msg = "# Heading\n\nSome text. " + ("blah " * 100) + "\n\n## Sub\n\nMore."
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": msg,
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")

    def test_long_with_bullets_passes(self):
        msg = "Here is the report:\n\n" + ("- item\n" * 50) + "\n\nEnd."
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": msg,
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")

    def test_long_with_code_block_passes(self):
        msg = "Here is the code:\n\n```python\n" + ("x = 1\n" * 80) + "```\n\nEnd."
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": msg,
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")

    def test_long_with_table_passes(self):
        msg = ("Report:\n\n| a | b |\n|---|---|\n" + ("| x | y |\n" * 60) + "\n\nEnd. " + ("text " * 50))
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": msg,
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")


class PassThroughTests(unittest.TestCase):
    def test_short_normal_passes(self):
        # >5 chars, no error keywords, <500 chars: passes all 3 checks
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "agent_type": "test",
                "last_assistant_message": "Found 3 files matching the pattern.",
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")

    def test_stop_hook_active_returns_silently(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out = _run({
                "stop_hook_active": True,
                "last_assistant_message": "anything",
                "transcript_path": "",
            }, Path(td))
            self.assertEqual(out, "")


class FailOpenTests(unittest.TestCase):
    def test_malformed_json_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             redirect_stdout(captured):
            sqc.main()
        self.assertEqual(captured.getvalue(), "")

    def test_empty_stdin_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            sqc.main()
        self.assertEqual(captured.getvalue(), "")


class SubagentQualityBoundaryTests(unittest.TestCase):
    """Named FP-guards (boundary-test harness sprint 6). Each docstring names its
    boundary_axis. FP-SQ-04 + FP-SQ-05 were the two over-application bugs the harness
    found; both FIXED 2026-06-02 and now pass as real assertions (see
    finding_subagent_quality_check_overfires)."""

    def test_fp_short_valid_answer_silent(self):
        """FP-SQ-01 boundary_axis: 'short refusal vs short valid answer (no keyword)'."""
        self.assertFalse(_blocked("Done. 4/4 checks pass; no defects found."))

    def test_fp_exactly_five_chars_silent(self):
        """FP-SQ-02 boundary_axis: 'len<5 empty vs len==5 minimal valid'."""
        self.assertFalse(_blocked("Hello"))

    def test_fp_long_keyword_in_prose_silent(self):
        """FP-SQ-03 boundary_axis: 'refusal keyword in SHORT vs in LONG message'.
        CHECK 2 only applies <100 chars; a long structured message containing
        'I cannot' in prose must not be treated as a refusal."""
        msg = "## Analysis\n\n- I cannot find a simpler form. " + ("detail. " * 30)
        self.assertFalse(_blocked(msg))

    def test_fp_short_negative_finding_with_keyword_silent(self):
        """FP-SQ-04 boundary_axis: 'refusal vs valid short NEGATIVE FINDING with refusal keyword'.
        FIXED 2026-06-02 (finding_subagent_quality_check_overfires): CHECK 2 now skips
        when a result-signal token ('reproduce', 'works', ...) co-occurs with the refusal
        keyword: a finding, not a refusal. Real refusals (no result-signal) still block."""
        self.assertFalse(_blocked("I cannot reproduce the bug; it works on main."))

    def test_fp_long_colon_structured_report_silent(self):
        """FP-SQ-05 boundary_axis: 'no markup vs label:value report (no markdown)'.
        FIXED 2026-06-02 (finding_subagent_quality_check_overfires): CHECK 3 now counts
        >=3 'Label: value' lines OR a known REPORT header as structure: the unfenced
        QA/PENTEST/PM report format CLAUDE.md mandates. Plain prose (no labels) still blocks.
        Addresses the format-pushback misfire (reference_subagent_stop_hook_causes_format_pushback)."""
        report = (
            "PENTEST REPORT\n"
            "Target: the boundary harness pure-logic decision function.\n"
            "Method: fed synthetic inputs through the pure logic and asserted "
            "block-vs-silent across each adjacent-safe boundary, comparing every "
            "case against the documented misfire class for this hook family, then "
            "re-ran every positive case to confirm the designed blocks still fire "
            "after the narrowing change so no real low-quality output slips through.\n"
            "Result: designed boundaries behave as specified; two over-application "
            "bugs surfaced in the subagent-quality checks and were narrowed.\n"
            "Untested surface: the live wrapper stdin/stdout I/O path is not exercised here.\n"
            "Conclusion: the harness covers the region it targets and the fix is contained."
        )
        self.assertGreater(len(report), 500)
        self.assertFalse(_blocked(report))


if __name__ == "__main__":
    unittest.main()
