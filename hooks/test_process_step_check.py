"""
Tests for process-step-check.py — PM rubber-stamp hardening (B2 fix 2026-04-13).
"""

import json
import unittest
import importlib.util
import os

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_hook():
    path = os.path.join(HOOKS_DIR, "process-step-check.py")
    spec = importlib.util.spec_from_file_location("process_step_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_transcript_lines(blocks):
    """Build JSONL transcript lines from a list of content blocks."""
    entry = {
        "type": "assistant",
        "message": {"content": blocks}
    }
    return [json.dumps(entry)]


class TestPmRubberStampHardening(unittest.TestCase):
    """B2 fix (2026-04-13): pm-orchestrator must be dispatched, not just inline report."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_hook()

    def test_pm_with_orchestrator_and_report_passes(self):
        """pm Skill + pm-orchestrator Agent + PM CHECKPOINT REPORT → PASS."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "pm-orchestrator", "prompt": "run checkpoint"}},
            {"type": "text", "text": "PM CHECKPOINT REPORT\nProject: test\nViability: PASS\nBlockers: 0"},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertTrue(passed, f"Should pass but got: {msg}")

    def test_pm_without_orchestrator_inline_report_blocked(self):
        """pm Skill + inline PM CHECKPOINT REPORT (no agent) → BLOCK."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "text", "text": "PM CHECKPOINT REPORT\nProject: test\nViability: PASS\nBlockers: 0"},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertFalse(passed)
        self.assertIn("pm-orchestrator agent was not dispatched", msg)

    def test_pm_with_orchestrator_no_report_blocked(self):
        """pm Skill + pm-orchestrator dispatched + no report → BLOCK (existing check)."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "pm-orchestrator", "prompt": "run checkpoint"}},
            {"type": "text", "text": "The PM agent ran but I forgot to write the report."},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertFalse(passed)
        self.assertIn("missing PM CHECKPOINT REPORT", msg)

    def test_no_pm_invoked_passes(self):
        """No pm Skill invocation → nothing to check → PASS."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-build"}},
            {"type": "text", "text": "Built the thing."},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
