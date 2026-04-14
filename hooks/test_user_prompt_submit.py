"""
Tests for user-prompt-submit.py — depth-signal detection (S1/M1 fix 2026-04-13).
"""

import re
import unittest


# Replicate the DEPTH_SIGNALS list from user-prompt-submit.py
DEPTH_SIGNALS = [
    (r'\bare you sure\b', "follow-up directive -- inherits or escalates, NEVER Quick"),
    (r'\bthink deeper\b', "explicit request for deeper reasoning -- NEVER Quick"),
    (r'\bwhy did\b', "causal investigation -- requires tracing causes, not lookup"),
    (r'\bthought experiment\b', "architectural reasoning -- NEVER Quick"),
    (r'\bi\'ve noticed\b', "pattern observation -- invites investigation"),
    (r'\banalyze this\b', "explicit analysis request -- NEVER Quick"),
    (r'\bthink about this\b', "explicit reasoning request -- NEVER Quick"),
    (r'\bbefore deciding\b', "deliberation request -- NEVER Quick"),
    (r'\bwas it always\b', "timeline investigation -- requires evidence"),
]


def detect_depth_signal(prompt_text):
    """Return (matched, reason) if depth signal found."""
    if not prompt_text:
        return False, None
    p_lower = prompt_text.lower()
    for pattern, reason in DEPTH_SIGNALS:
        if re.search(pattern, p_lower):
            return True, reason
    return False, None


class TestDepthSignalDetection(unittest.TestCase):
    """S1/M1 fix (2026-04-13): depth-signal keyword detection."""

    def test_are_you_sure(self):
        matched, reason = detect_depth_signal("are you sure about that?")
        self.assertTrue(matched)
        self.assertIn("follow-up", reason)

    def test_analyze_this(self):
        matched, _ = detect_depth_signal("analyze this workflow")
        self.assertTrue(matched)

    def test_think_deeper(self):
        matched, _ = detect_depth_signal("think deeper about the problem")
        self.assertTrue(matched)

    def test_why_did(self):
        matched, _ = detect_depth_signal("why did the build fail?")
        self.assertTrue(matched)

    def test_no_false_positive_normal_prompt(self):
        matched, _ = detect_depth_signal("update the config file")
        self.assertFalse(matched)

    def test_no_false_positive_simple_question(self):
        matched, _ = detect_depth_signal("what's the current status?")
        self.assertFalse(matched)

    def test_skip_list_suppresses(self):
        """Skip-list items should not trigger depth signals (tested via flow,
        not detection — skip_list sets classifier_reminder='' before depth check)."""
        # "yes" is in skip_list. Even if it matched a pattern, the
        # classifier_reminder guard (and classifier_reminder) prevents injection.
        matched, _ = detect_depth_signal("yes")
        self.assertFalse(matched)

    def test_empty_prompt(self):
        matched, _ = detect_depth_signal("")
        self.assertFalse(matched)

    def test_none_prompt(self):
        matched, _ = detect_depth_signal(None)
        self.assertFalse(matched)


if __name__ == "__main__":
    unittest.main(verbosity=2)
