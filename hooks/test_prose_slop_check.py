"""Tests for prose-slop-check.py: DORMANT PostToolUse:Write quality hook.

Covers the pure detector (find_slop / should_warn) + the scope gate, and carries
named FP-guards (C4 boundary coverage). The hook NEVER blocks (WARN-only), so the
"true positive" here is "emits a warning", not "blocks".
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "prose_slop_check",
    str(Path(__file__).parent / "prose-slop-check.py"),
)
psc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(psc)


def _run(file_path: str, content: str) -> str:
    """Invoke main() with a PostToolUse:Write payload; return stderr text."""
    payload = {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stderr(captured):
        rc = psc.main()
    return captured.getvalue(), rc


WIKI = "Resources/KB/some-page.md"
WORK = "Projects/Agent-Governance-Research/work/2026-06-02-note.md"


class DetectorTests(unittest.TestCase):
    def test_two_distinct_slop_words_detected(self):
        d, t, hits = psc.find_slop("We delve into the tapestry of options.")
        self.assertGreaterEqual(d, 2)
        self.assertTrue(psc.should_warn(d, t))

    def test_same_word_thrice_detected(self):
        d, t, _ = psc.find_slop("foster and foster and foster the thing")
        self.assertEqual(t, 3)
        self.assertTrue(psc.should_warn(d, t))

    def test_clean_technical_prose_silent(self):
        d, t, _ = psc.find_slop("The hook reads the registry, computes age, warns if stale.")
        self.assertFalse(psc.should_warn(d, t))


class ScopeGateTests(unittest.TestCase):
    def test_warns_on_wiki_path(self):
        err, rc = _run(WIKI, "We delve into the vibrant tapestry of the realm.")
        self.assertIn("prose-slop-check WARN", err)
        self.assertEqual(rc, 0)  # WARN-only never blocks

    def test_warns_on_work_path(self):
        err, _ = _run(WORK, "Furthermore, we showcase the multifaceted approach.")
        self.assertIn("prose-slop-check WARN", err)


class ProseSlopBoundaryTests(unittest.TestCase):
    """Named FP-guards (C4 boundary coverage). Each docstring names its boundary_axis."""

    def test_fp_borderline_technical_words_silent(self):
        """FP-PS-01 boundary_axis: 'hallmark LLM-slop vs legitimate technical register'.
        robust/comprehensive/crucial/significant/fundamental are EXCLUDED from the list
        by calibration: a page full of them must NOT warn."""
        text = ("This is a robust, comprehensive design. The crucial, significant, "
                "fundamental decision leverages the existing landscape seamlessly.")
        d, t, _ = psc.find_slop(text)
        self.assertFalse(psc.should_warn(d, t), "borderline technical words must not trip the detector")

    def test_fp_slop_inside_code_fence_silent(self):
        """FP-PS-02 boundary_axis: 'prose vs fenced code'. Slop words inside a code
        fence (e.g. a string literal or example) are not prose."""
        text = "Here is an example:\n```\ndelve tapestry multifaceted furthermore moreover\n```\n"
        d, t, _ = psc.find_slop(text)
        self.assertFalse(psc.should_warn(d, t))

    def test_fp_slop_inside_table_silent(self):
        """FP-PS-03 boundary_axis: 'prose vs markdown table'. A glossary/table row
        listing slop words (e.g. a banned-words table) is not prose."""
        text = "| word | verdict |\n|---|---|\n| delve | banned |\n| tapestry | banned |\n| foster | banned |\n"
        d, t, _ = psc.find_slop(text)
        self.assertFalse(psc.should_warn(d, t))

    def test_fp_single_stray_word_silent(self):
        """FP-PS-04 boundary_axis: 'real slop density vs one-off'. A single stray
        slop word (below both thresholds) must NOT warn."""
        d, t, _ = psc.find_slop("This will showcase the result.")
        self.assertEqual((d, t), (1, 1))
        self.assertFalse(psc.should_warn(d, t))

    def test_fp_raw_layer_path_not_linted(self):
        """FP-PS-05 boundary_axis: 'wiki/work layer vs raw layer'. Inbox/Clippings/
        Daily Notes are human/external prose: out of scope even if slop-dense."""
        err, _ = _run("Inbox/some-dump.md", "We delve into the vibrant tapestry of the realm, moreover.")
        self.assertEqual(err, "")

    def test_fp_substring_not_matched(self):
        """FP-PS-06 boundary_axis: 'whole word vs substring'. 'fostering' contains
        'foster' but \\b word-boundary anchoring should still match 'foster' only as a
        whole word: 'realm' must not match inside 'realms'? Guard the common false
        substring case: 'foster' must not fire on unrelated 'fostered' check is moot,
        but 'real' inside 'really' must NOT count as 'realm'."""
        d, t, _ = psc.find_slop("I really think the area is well understood.")
        self.assertEqual((d, t), (0, 0))

    def test_tp_genuinely_sloppy_paragraph_warns(self):
        """TP-PS-01: a genuinely LLM-sloppy paragraph (multiple hallmark words) warns."""
        err, _ = _run(WIKI, "We delve into the multifaceted, vibrant tapestry; furthermore "
                            "this fosters a realm that underscores the paramount interplay.")
        self.assertIn("prose-slop-check WARN", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
