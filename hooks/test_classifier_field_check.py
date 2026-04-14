"""
Tests for classifier-field-check.py — Stop hook that verifies classifier fields.
Step 3.1 (2026-04-13): JUSTIFICATION enforcement for Quick.
"""

import re
import unittest


def check_quick_justification(classifier_text):
    """Simulate the Quick JUSTIFICATION check from classifier-field-check.py."""
    is_quick = bool(re.search(
        r'(?:TASK TYPE|CLASSIFICATION):\s*Quick', classifier_text, re.IGNORECASE
    ))
    if not is_quick:
        return True  # Non-Quick doesn't need JUSTIFICATION
    has_justification = bool(re.search(r'JUSTIFICATION:', classifier_text, re.IGNORECASE))
    return has_justification


class TestQuickJustification(unittest.TestCase):
    """S1 fix (2026-04-13): Quick must have JUSTIFICATION field."""

    def test_quick_without_justification_blocked(self):
        """Quick classification without JUSTIFICATION should fail."""
        text = (
            "IMPLIES: Simple file move\n"
            "TASK TYPE: Quick\n"
        )
        self.assertFalse(check_quick_justification(text))

    def test_quick_with_justification_passes(self):
        """Quick classification with JUSTIFICATION should pass."""
        text = (
            "IMPLIES: Simple file move\n"
            "TASK TYPE: Quick\n"
            "JUSTIFICATION: Single file move, no judgment needed\n"
        )
        self.assertTrue(check_quick_justification(text))

    def test_non_quick_without_justification_passes(self):
        """Non-Quick classification should not require JUSTIFICATION."""
        text = (
            "IMPLIES: Complex analysis\n"
            "TASK TYPE: Analysis\n"
            "APPROACH: inline\n"
            "MISSED: nothing\n"
            "MUST DISPATCH: process-qa, pm\n"
        )
        self.assertTrue(check_quick_justification(text))

    def test_justification_case_insensitive(self):
        """JUSTIFICATION check should be case-insensitive."""
        text = (
            "IMPLIES: test\n"
            "TASK TYPE: Quick\n"
            "justification: it's simple\n"
        )
        self.assertTrue(check_quick_justification(text))


class TestMultilinePmCheck(unittest.TestCase):
    """B4 fix regression: multiline PM enforcement in classifier-field-check."""

    def test_pm_on_line2_not_blocked(self):
        """PM on second line of multiline MUST DISPATCH should pass."""
        FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'
        text = (
            "IMPLIES: test\n"
            "TASK TYPE: Build\n"
            "APPROACH: build\n"
            "MUST DISPATCH:\n"
            "  process-build,\n"
            "  pm,\n"
            "  process-qa\n"
            "MISSED: nothing"
        )
        dispatch_match = re.search(
            r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
            text, re.DOTALL | re.IGNORECASE
        )
        self.assertIsNotNone(dispatch_match)
        dispatch_text = re.sub(r'\s+', ' ', dispatch_match.group(1).strip()).lower()
        self.assertTrue(re.search(r'\bpm\b', dispatch_text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
