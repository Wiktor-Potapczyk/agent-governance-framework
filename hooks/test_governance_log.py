"""
Unit tests for governance-log.py — specifically extract_dispatch_names().

P0 fix (2026-04-09): must_dispatch field was capturing trailing reasoning text
after comma-separated agent/skill names. extract_dispatch_names() filters to
only known names from KNOWN_DISPATCH_NAMES set.

Run: python .claude/hooks/test_governance_log.py
"""

import importlib.util
import os
import sys
import unittest

# Load the module under test
HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.py")
spec = importlib.util.spec_from_file_location("governance_log", HOOK_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

extract_dispatch_names = mod.extract_dispatch_names
KNOWN_DISPATCH_NAMES = mod.KNOWN_DISPATCH_NAMES


class TestExtractDispatchNames(unittest.TestCase):
    """Tests for the P0 must_dispatch parsing fix."""

    # --- Clean inputs (no trailing text) ---

    def test_single_name(self):
        self.assertEqual(extract_dispatch_names("process-qa"), "process-qa")

    def test_two_names(self):
        self.assertEqual(extract_dispatch_names("process-qa, pm"), "process-qa, pm")

    def test_three_names(self):
        self.assertEqual(
            extract_dispatch_names("process-analysis, adversarial-reviewer, process-qa"),
            "process-analysis, adversarial-reviewer, process-qa",
        )

    def test_all_process_skills(self):
        self.assertEqual(
            extract_dispatch_names("process-build, architect-review, process-qa, pm"),
            "process-build, architect-review, process-qa, pm",
        )

    # --- None / empty / n/a ---

    def test_none_value(self):
        self.assertIsNone(extract_dispatch_names(None))

    def test_empty_string(self):
        self.assertIsNone(extract_dispatch_names(""))

    def test_none_text(self):
        self.assertEqual(extract_dispatch_names("none"), "none")

    def test_none_with_period(self):
        self.assertEqual(extract_dispatch_names("none."), "none")

    def test_na_text(self):
        self.assertEqual(extract_dispatch_names("N/A"), "none")

    def test_na_lowercase(self):
        self.assertEqual(extract_dispatch_names("n/a"), "none")

    # --- Trailing reasoning text (the P0 bug) ---

    def test_trailing_reasoning_short(self):
        self.assertEqual(
            extract_dispatch_names("process-qa Let me run QA on the paper."),
            "process-qa",
        )

    def test_trailing_reasoning_two_names(self):
        self.assertEqual(
            extract_dispatch_names(
                "process-qa, pm Let me break down the reviewer's feedback and respond to each point"
            ),
            "process-qa, pm",
        )

    def test_trailing_reasoning_long(self):
        raw = (
            "process-build, process-qa This is too many files to edit inline "
            "— it would destroy context. Let me use parallel agents."
        )
        self.assertEqual(extract_dispatch_names(raw), "process-build, process-qa")

    def test_trailing_reasoning_with_numbers(self):
        raw = (
            "process-analysis, process-qa Let me check which 3 tasks. "
            "From STATE.md Next: 1. Test in fresh session 2. Set API key"
        )
        self.assertEqual(extract_dispatch_names(raw), "process-analysis, process-qa")

    def test_trailing_reasoning_multiline_collapsed(self):
        raw = (
            "process-qa, pm The approach: 1. Generate a secure token "
            "2. W4: Validate token in Calculate Snooze"
        )
        self.assertEqual(extract_dispatch_names(raw), "process-qa, pm")

    # --- Garbage / malformed inputs ---

    def test_question_mark(self):
        self.assertIsNone(extract_dispatch_names("?"))

    def test_garbage_text(self):
        self.assertIsNone(extract_dispatch_names("until the next field label"))

    def test_partial_match_no_name(self):
        """A token like 'architect-review,' should still match after stripping punctuation."""
        self.assertEqual(
            extract_dispatch_names("architect-review, but no Agent tool used"),
            "architect-review",
        )

    # --- Edge cases ---

    def test_name_with_extra_whitespace(self):
        self.assertEqual(
            extract_dispatch_names("  process-qa ,  pm  "),
            "process-qa, pm",
        )

    def test_case_insensitive(self):
        """Names should match case-insensitively."""
        self.assertEqual(extract_dispatch_names("Process-QA, PM"), "process-qa, pm")

    def test_known_names_set_not_empty(self):
        """Sanity check: KNOWN_DISPATCH_NAMES should have reasonable count."""
        self.assertGreater(len(KNOWN_DISPATCH_NAMES), 30)

    def test_all_process_skills_in_known(self):
        """All process-* skills must be in the known set."""
        for name in ["process-qa", "process-analysis", "process-build",
                      "process-planning", "process-research", "process-pentest"]:
            self.assertIn(name, KNOWN_DISPATCH_NAMES, f"{name} missing from KNOWN_DISPATCH_NAMES")

    def test_pm_in_known(self):
        """pm is in MUST DISPATCH for every non-Quick task — must be known."""
        self.assertIn("pm", KNOWN_DISPATCH_NAMES)

    # --- Real data from governance-log.jsonl (regression tests) ---

    def test_real_data_long_reasoning_1(self):
        raw = (
            "process-qa Let me build a structured research findings document "
            "from the calculation files — tracing every claim to its source."
        )
        self.assertEqual(extract_dispatch_names(raw), "process-qa")

    def test_real_data_long_reasoning_2(self):
        raw = (
            "process-qa Let me save state first, then kick off the experiment."
        )
        self.assertEqual(extract_dispatch_names(raw), "process-qa")

    def test_real_data_pipe_delimited(self):
        raw = (
            "architect-review, but no Agent tool used | Yes (keyword match) "
            "| Yes (declared item missing) |"
        )
        self.assertEqual(extract_dispatch_names(raw), "architect-review")


class TestKnownNamesCompleteness(unittest.TestCase):
    """Verify KNOWN_DISPATCH_NAMES covers the agents/skills that appear in MUST DISPATCH."""

    def test_common_dispatch_names(self):
        """Names frequently seen in MUST DISPATCH should all be in the set."""
        common = [
            "process-qa", "pm", "process-build", "process-analysis",
            "process-planning", "process-research", "architect-review",
            "adversarial-reviewer", "technical-researcher", "prompt-engineer",
            "blueprint-mode", "implementation-plan", "research-orchestrator",
        ]
        for name in common:
            self.assertIn(name, KNOWN_DISPATCH_NAMES, f"{name} missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
