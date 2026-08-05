"""Smoke tests for raw-frontmatter-check.py: PostToolUse Write/Edit hook (ADVISORY)."""

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
    "raw_frontmatter_check",
    str(Path(__file__).parent / "raw-frontmatter-check.py"),
)
rfc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfc)


class HasWikiTagTests(unittest.TestCase):
    def test_wiki_in_list(self):
        fm = "---\ntags: [wiki, reference]\n---\nBody"
        self.assertTrue(rfc.has_wiki_tag(fm))

    def test_no_wiki_tag(self):
        fm = "---\ntags: [research, analysis]\n---\nBody"
        self.assertFalse(rfc.has_wiki_tag(fm))

    def test_wiki_status_not_tag(self):
        # `wiki_status:` is a separate field, not a tag: must not false-trigger
        fm = "---\ntags: [research]\nwiki_status: bootstrap\n---\nBody"
        self.assertFalse(rfc.has_wiki_tag(fm))

    def test_no_frontmatter(self):
        self.assertFalse(rfc.has_wiki_tag("plain body"))

    def test_unterminated_frontmatter(self):
        self.assertFalse(rfc.has_wiki_tag("---\ntags: [wiki]\n"))


class ParseFrontmatterFieldsTests(unittest.TestCase):
    def test_extracts_top_level_fields(self):
        fm = "---\ndate: 2026-05-24\ntags: [research]\nstatus: active\n---\nBody"
        fields = rfc.parse_frontmatter_fields(fm)
        self.assertEqual(fields, {"date", "tags", "status"})

    def test_skips_list_items(self):
        # `- item` lines should not be parsed as fields
        fm = "---\ntags:\n  - research\n  - analysis\nstatus: active\n---\nBody"
        fields = rfc.parse_frontmatter_fields(fm)
        self.assertIn("tags", fields)
        self.assertIn("status", fields)
        self.assertNotIn("research", fields)

    def test_no_frontmatter_empty_set(self):
        self.assertEqual(rfc.parse_frontmatter_fields("plain body"), set())

    def test_unterminated_frontmatter(self):
        self.assertEqual(rfc.parse_frontmatter_fields("---\ndate: x\nno close"), set())


class IsInScopeTests(unittest.TestCase):
    def test_projects_md_in_scope(self):
        p = rfc.VAULT / "Projects" / "X" / "work" / "test.md"
        self.assertTrue(rfc.is_in_scope(p))

    def test_state_excluded(self):
        p = rfc.VAULT / "Projects" / "X" / "STATE.md"
        self.assertFalse(rfc.is_in_scope(p))

    def test_claude_md_excluded(self):
        p = rfc.VAULT / "CLAUDE.md"
        self.assertFalse(rfc.is_in_scope(p))

    def test_inbox_excluded(self):
        p = rfc.VAULT / "Inbox" / "raw.md"
        self.assertFalse(rfc.is_in_scope(p))

    def test_claude_dir_excluded(self):
        p = rfc.VAULT / ".claude" / "hooks" / "x.md"
        self.assertFalse(rfc.is_in_scope(p))

    def test_resources_kb_excluded(self):
        # Wiki layer: handled by wiki-citation-check
        p = rfc.VAULT / "Resources" / "KB" / "note.md"
        self.assertFalse(rfc.is_in_scope(p))

    def test_non_md_excluded(self):
        p = rfc.VAULT / "Projects" / "X" / "work" / "data.json"
        self.assertFalse(rfc.is_in_scope(p))

    def test_resources_outside_kb_in_scope(self):
        p = rfc.VAULT / "Resources" / "Observability" / "daily-digest.md"
        self.assertTrue(rfc.is_in_scope(p))


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(rfc, "log", lambda *a, **k: None), \
         redirect_stdout(captured):
        rfc.main()
    return captured.getvalue()


def _make_in_scope_file(content: str) -> Path:
    # Write into a real in-vault path so is_in_scope passes
    target_dir = rfc.VAULT / "Projects" / "your-project" / "work" / "_scratch"
    target_dir.mkdir(parents=True, exist_ok=True)
    p = target_dir / "test-raw-frontmatter-smoke.md"
    p.write_text(content, encoding="utf-8")
    return p


class MainEndToEndTests(unittest.TestCase):
    def tearDown(self):
        scratch = rfc.VAULT / "Projects" / "your-project" / "work" / "_scratch"
        if scratch.is_dir():
            for item in scratch.iterdir():
                try:
                    item.unlink()
                except Exception:
                    pass
            try:
                scratch.rmdir()
            except Exception:
                pass

    def test_disabled_returns_silently(self):
        with mock.patch.object(rfc, "DISABLED", True):
            out = _run({"tool_name": "Write", "tool_input": {"file_path": "/x"}})
            self.assertEqual(out, "")

    def test_non_write_tool_returns_silently(self):
        out = _run({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        self.assertEqual(out, "")

    def test_missing_file_path_returns_silently(self):
        out = _run({"tool_name": "Write", "tool_input": {}})
        self.assertEqual(out, "")

    def test_out_of_scope_silent(self):
        p = rfc.VAULT / "Projects" / "X" / "STATE.md"
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")

    def test_missing_required_fields_emits_advisory(self):
        p = _make_in_scope_file("---\ndate: 2026-05-24\n---\nBody")
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("missing required fields", ctx)
        self.assertIn("tags", ctx)
        self.assertIn("status", ctx)

    def test_no_frontmatter_emits_advisory(self):
        p = _make_in_scope_file("plain body, no frontmatter")
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("No frontmatter", ctx)

    def test_complete_frontmatter_silent(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [research]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")

    def test_wiki_tagged_file_skipped(self):
        # Files with #wiki tag are handled by wiki-citation-check, this hook skips them
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [wiki]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
