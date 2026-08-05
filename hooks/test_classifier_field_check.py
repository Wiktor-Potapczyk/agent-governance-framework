"""
Tests for classifier-field-check.py: Stop hook that verifies classifier fields.
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


import importlib.util  # noqa: E402
import os  # noqa: E402

_cfc_spec = importlib.util.spec_from_file_location(
    "classifier_field_check",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "classifier-field-check.py"),
)
cfc = importlib.util.module_from_spec(_cfc_spec)
_cfc_spec.loader.exec_module(cfc)

_FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'


def _eval_missing(text):
    """Mirror classifier-field-check.main() field logic exactly (lines ~95-124).

    Kept as a faithful copy (the file's existing 'simulate' convention): the
    field detection is inline in main() and the hook writes to governance-log on
    block, so running it end-to-end would pollute the log."""
    is_quick = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*Quick', text, re.IGNORECASE))
    has_implies = bool(re.search(r'IMPLIES:', text, re.IGNORECASE))
    has_type = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):', text, re.IGNORECASE))
    has_approach = bool(re.search(r'APPROACH:', text, re.IGNORECASE))
    has_missed = bool(re.search(r'MISSED:', text, re.IGNORECASE))
    has_md = bool(re.search(r'MUST DISPATCH:', text, re.IGNORECASE))
    missing = []
    if not has_implies:
        missing.append("IMPLIES")
    if not has_type:
        missing.append("TASK TYPE")
    if not is_quick:
        if not has_approach:
            missing.append("APPROACH")
        if not has_missed:
            missing.append("MISSED")
        if not has_md:
            missing.append("MUST DISPATCH")
    if not is_quick and has_md and not missing:
        dm = re.search(r'MUST DISPATCH:\s*(.+)', text, re.IGNORECASE)
        if dm and not re.search(r'\bpm\b', dm.group(1).lower()):
            missing.append("pm in MUST DISPATCH")
    return missing


class ClassifierFieldBoundaryTests(unittest.TestCase):
    """Named FP-guards (boundary-test harness sprint 9). Each docstring names its
    boundary_axis."""

    def test_fp_quick_minimal_fields_silent(self):
        """FP-CF-01 boundary_axis: 'Quick field set (IMPLIES+TYPE+JUSTIFICATION) vs non-Quick set'.
        A Quick task must NOT be blocked for missing APPROACH/MISSED/MUST DISPATCH."""
        text = "IMPLIES: trivial rename\nTASK TYPE: Quick\nJUSTIFICATION: one-field edit"
        self.assertEqual(_eval_missing(text), [])

    def test_fp_fenced_classification_not_detected_silent(self):
        """FP-CF-02 boundary_axis: 'fenced example classification vs live classification'.
        A classification block inside ``` (quoting the template) is stripped by the real
        strip_fences, so it is not treated as a live classification."""
        fenced = "Example:\n```\nTASK TYPE: Build\nMUST DISPATCH: process-qa, pm\n```\n"
        cleaned = cfc.strip_fences(fenced)
        self.assertNotRegex(
            cleaned,
            r'(?:TASK TYPE|CLASSIFICATION):\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)',
        )

    def test_fp_pm_orchestrator_satisfies_pm_silent(self):
        """FP-CF-03 boundary_axis: 'literal pm / pm-orchestrator satisfies the PM requirement'.
        origin: regression (SA-2 finding: \\bpm\\b matches 'pm-orchestrator'). A non-Quick
        task declaring 'pm-orchestrator' (not bare 'pm') must NOT be flagged 'pm missing'."""
        text = ("IMPLIES: x\nTASK TYPE: Analysis\nAPPROACH: a\nMISSED: none\n"
                "MUST DISPATCH: process-qa, pm-orchestrator")
        self.assertEqual(_eval_missing(text), [])

    def test_tp_nonquick_missing_missed_blocks(self):
        """TP-CF-01: a non-Quick classification missing MISSED is flagged."""
        text = "IMPLIES: x\nTASK TYPE: Build\nAPPROACH: a\nMUST DISPATCH: process-qa, pm"
        self.assertIn("MISSED", _eval_missing(text))


# B6 (2026-06-16, two-gate): REVERSIBILITY / DETECTABILITY are ACCEPTED (captured),
# never REQUIRED. These tests guard against (a) accidentally making them mandatory and
# (b) a Quick task being blocked because it declares irreversible-surface.
_REVERSIBILITY_RX = re.compile(r'REVERSIBILITY:\s*([^\n]+)', re.IGNORECASE)
_DETECTABILITY_RX = re.compile(r'DETECTABILITY:\s*([^\n]+)', re.IGNORECASE)


class TestTwoGateFields(unittest.TestCase):
    """B6: the two new advisory autonomy fields are accept-not-require + captured."""

    def test_classification_with_both_fields_not_blocked(self):
        """A classification carrying both new fields is NOT blocked (fields accepted)."""
        text = (
            "IMPLIES: edit helper then test\nTASK TYPE: Quick\n"
            "JUSTIFICATION: single edit\n"
            "REVERSIBILITY: reversible\nDETECTABILITY: self-detectable"
        )
        self.assertEqual(_eval_missing(text), [])

    def test_classification_without_fields_not_blocked(self):
        """Absence of the new fields never blocks (they are not required)."""
        text = "IMPLIES: trivial rename\nTASK TYPE: Quick\nJUSTIFICATION: one-field edit"
        self.assertEqual(_eval_missing(text), [])

    def test_quick_irreversible_surface_not_blocked(self):
        """A Quick task declaring REVERSIBILITY: irreversible-surface stays Quick (no block).
        The hard stop is the Gate-1 PreToolUse deny, never this Stop hook."""
        text = (
            "IMPLIES: delete the unused helper\nTASK TYPE: Quick\n"
            "JUSTIFICATION: explicit imperative\n"
            "REVERSIBILITY: irreversible-surface"
        )
        self.assertEqual(_eval_missing(text), [])

    def test_fields_extracted_for_emit(self):
        """The capture regexes (mirror of the hook's emit block) extract both values."""
        text = (
            "TASK TYPE: Build\nREVERSIBILITY: irreversible-surface\n"
            "DETECTABILITY: needs-detector\n"
        )
        rev = _REVERSIBILITY_RX.search(text)
        det = _DETECTABILITY_RX.search(text)
        self.assertIsNotNone(rev)
        self.assertIsNotNone(det)
        self.assertEqual(rev.group(1).strip(), "irreversible-surface")
        self.assertEqual(det.group(1).strip(), "needs-detector")


if __name__ == "__main__":
    unittest.main(verbosity=2)
