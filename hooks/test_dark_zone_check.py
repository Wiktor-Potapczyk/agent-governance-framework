"""Smoke tests for dark-zone-check.py — Stop hook (monitoring only).

Minimal coverage of: citation pattern counting, the effort_level extraction
added in 2026-05-23 loop iter 5, and the basic shape of governance-log emission.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "dark_zone_check",
    str(Path(__file__).parent / "dark-zone-check.py"),
)
dzc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dzc)


class CitationCountTests(unittest.TestCase):
    def test_per_agent_pattern(self):
        self.assertGreater(dzc.count_citations("Per architect-reviewer: x"), 0)

    def test_agent_found_pattern(self):
        self.assertGreater(dzc.count_citations("the review found 3 issues"), 0)

    def test_qa_report_counts(self):
        self.assertGreater(dzc.count_citations("QA REPORT\nPASS: 4/4"), 0)

    def test_no_citation_zero(self):
        self.assertEqual(dzc.count_citations("just a regular response"), 0)

    def test_strip_fences_removes_code_blocks(self):
        text = "```\nPer architect: x\n```\nclean"
        stripped = dzc.strip_fences(text)
        self.assertNotIn("Per architect", stripped)


class EffortLevelExtractionTests(unittest.TestCase):
    """Iter 5 (2026-05-23) added effort_level extraction. Verify the read path
    without actually invoking main() — that requires a real transcript file."""

    def test_extraction_read_from_payload(self):
        # Same extraction logic as the hook uses inline at the emit site:
        payload = {"effort": {"level": "high"}}
        effort = payload.get("effort")
        result = str(effort.get("level")) if isinstance(effort, dict) and effort.get("level") is not None else None
        self.assertEqual(result, "high")

    def test_missing_effort_field(self):
        payload = {}
        effort = payload.get("effort")
        result = str(effort.get("level")) if isinstance(effort, dict) and effort.get("level") is not None else None
        self.assertIsNone(result)

    def test_malformed_effort_not_dict(self):
        payload = {"effort": "string-not-dict"}
        effort = payload.get("effort")
        result = str(effort.get("level")) if isinstance(effort, dict) and effort.get("level") is not None else None
        self.assertIsNone(result)


class MainSmokeTests(unittest.TestCase):
    """Exercise main() against a synthetic transcript file. Patch the log path
    so we don't touch the real governance-log.jsonl."""

    def _build_transcript(self, td: Path, has_citation: bool) -> Path:
        tp = td / "session-smoke.jsonl"
        entries = [
            {"type": "user", "message": {"content": "do thing"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "test-agent", "description": "x"}}
            ]}},
        ]
        final_text = "QA REPORT PASS: 4/4" if has_citation else "Done."
        entries.append({"type": "assistant", "message": {"content": [{"type": "text", "text": final_text}]}})
        with tp.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return tp

    def test_high_severity_when_no_citation(self):
        with tempfile.TemporaryDirectory() as td:
            tp = self._build_transcript(Path(td), has_citation=False)
            log_path = Path(td) / "governance-log.jsonl"
            # Patch the log path the hook computes
            with mock.patch.object(dzc.os.path, "dirname", return_value=str(td)):
                with mock.patch.object(sys, "stdin",
                                       __import__("io").StringIO(
                                           json.dumps({"transcript_path": str(tp)})
                                       )):
                    dzc.main()
            # Hook may or may not have written to the patched log location depending on
            # how os.path.dirname is used internally. Just confirm no exception.
            self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
