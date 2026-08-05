"""Smoke tests for tag-variant-check.py: PostToolUse Write hook (ADVISORY)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "tag_variant_check",
    str(Path(__file__).parent / "tag-variant-check.py"),
)
tvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tvc)


class ParseFrontmatterTagsTests(unittest.TestCase):
    def test_inline_list_with_brackets(self):
        fm = "---\ntags: [research, analysis]\nstatus: active\n---\nBody"
        self.assertEqual(set(tvc.parse_frontmatter_tags(fm)), {"research", "analysis"})

    def test_inline_list_hash_prefixed(self):
        fm = "---\ntags: [#research, #analysis]\n---\nBody"
        self.assertEqual(set(tvc.parse_frontmatter_tags(fm)), {"research", "analysis"})

    def test_comma_separated_no_brackets(self):
        fm = "---\ntags: research, analysis\n---\nBody"
        self.assertEqual(set(tvc.parse_frontmatter_tags(fm)), {"research", "analysis"})

    def test_block_list_form(self):
        fm = "---\ntags:\n  - research\n  - analysis\nstatus: active\n---\nBody"
        self.assertEqual(set(tvc.parse_frontmatter_tags(fm)), {"research", "analysis"})

    def test_no_frontmatter(self):
        self.assertEqual(tvc.parse_frontmatter_tags("plain body"), [])

    def test_no_tags_field(self):
        fm = "---\ndate: 2026-05-24\nstatus: active\n---\nBody"
        self.assertEqual(tvc.parse_frontmatter_tags(fm), [])


class IsInScopeTests(unittest.TestCase):
    def test_projects_md_in_scope(self):
        p = tvc.VAULT / "Projects" / "X" / "work" / "x.md"
        self.assertTrue(tvc.is_in_scope(p))

    def test_claude_md_excluded(self):
        p = tvc.VAULT / "CLAUDE.md"
        self.assertFalse(tvc.is_in_scope(p))

    def test_claude_dir_excluded(self):
        p = tvc.VAULT / ".claude" / "hooks" / "x.md"
        self.assertFalse(tvc.is_in_scope(p))

    def test_non_md_excluded(self):
        p = tvc.VAULT / "Projects" / "X" / "data.json"
        self.assertFalse(tvc.is_in_scope(p))


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(tvc, "log", lambda *a, **k: None), \
         redirect_stdout(captured):
        tvc.main()
    return captured.getvalue()


def _make_in_scope_file(content: str, basename: str = "test-tag-variant-smoke.md") -> Path:
    target_dir = tvc.VAULT / "Projects" / "your-project" / "work" / "_scratch_tags"
    target_dir.mkdir(parents=True, exist_ok=True)
    p = target_dir / basename
    p.write_text(content, encoding="utf-8")
    return p


class MainEndToEndTests(unittest.TestCase):
    def tearDown(self):
        scratch = tvc.VAULT / "Projects" / "your-project" / "work" / "_scratch_tags"
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

    def test_disabled_silent(self):
        with mock.patch.object(tvc, "DISABLED", True):
            out = _run({"tool_name": "Write", "tool_input": {"file_path": "/x"}})
            self.assertEqual(out, "")

    def test_non_write_tool_silent(self):
        out = _run({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        self.assertEqual(out, "")

    def test_out_of_scope_silent(self):
        p = tvc.VAULT / "CLAUDE.md"
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")

    def test_canonical_tags_silent(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [research, analysis]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")

    def test_project_nested_tag_silent(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [project/your-project]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        self.assertEqual(out, "")

    def test_known_alias_emits_suggestion(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [complete]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("complete", ctx)
        self.assertIn("done", ctx)
        self.assertIn("canonical", ctx)

    def test_known_alias_with_delete_action(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [state]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("DELETE", ctx)

    def test_unknown_variant_emits_suggestion(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [some-totally-unknown-tag]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("unknown variant", ctx.lower())

    def test_numeric_tag_flagged_delete(self):
        p = _make_in_scope_file(
            "---\ndate: 2026-05-24\ntags: [12345]\nstatus: active\n---\nBody"
        )
        out = _run({"tool_name": "Write", "tool_input": {"file_path": str(p)}})
        result = json.loads(out)
        ctx = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("DELETE", ctx)


if __name__ == "__main__":
    unittest.main()
