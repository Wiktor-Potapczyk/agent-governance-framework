"""Smoke tests for wiki-citation-check.py — PostToolUse Write hook (thin wrapper).

The pure-logic half is tested in test_wiki_citation_logic.py. These tests cover
only the wrapper's I/O routing: stdin parsing, tool-name filter, wiki-path
gating, content reading, additionalContext emission.
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
    "wiki_citation_check",
    str(Path(__file__).parent / "wiki-citation-check.py"),
)
wcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wcc)


def _run(payload: dict) -> tuple[int, str]:
    payload_str = json.dumps(payload)
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(payload_str)), \
         mock.patch.object(wcc, "log_decision", lambda *a, **k: None), \
         redirect_stdout(captured):
        rc = wcc.main()
    return rc, captured.getvalue()


class ToolNameFilterTests(unittest.TestCase):
    def test_read_passes(self):
        rc, out = _run({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_bash_passes(self):
        rc, out = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_glob_passes(self):
        rc, out = _run({"tool_name": "Glob", "tool_input": {"pattern": "*"}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


class PathFilterTests(unittest.TestCase):
    def test_missing_file_path_passes(self):
        rc, out = _run({"tool_name": "Write", "tool_input": {}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_path_outside_vault_passes(self):
        rc, out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/elsewhere/foo.md"},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_non_wiki_path_in_vault_passes(self):
        # An arbitrary in-vault path that isn't a wiki path
        p = str(wcc.VAULT / "Projects" / "X" / "work" / "test.md")
        rc, out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": p},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


class WikiPathGatingTests(unittest.TestCase):
    def test_kb_path_with_valid_source_passes(self):
        # Write a temp file under Resources/KB/ with valid source frontmatter.
        # We exercise the wrapper end-to-end (it reads from disk) — but use a real
        # source file as the citation target so SHA matches.
        kb_dir = wcc.VAULT / "Resources" / "KB"
        if not kb_dir.exists():
            self.skipTest("Resources/KB not present in this environment")
        # Use CLAUDE.md as the cited source — it exists, has a stable hash
        claude_md = wcc.VAULT / "CLAUDE.md"
        if not claude_md.is_file():
            self.skipTest("CLAUDE.md not present in this environment")
        import hashlib
        sha = hashlib.sha256(claude_md.read_bytes()).hexdigest()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=str(kb_dir), delete=False, encoding="utf-8"
        ) as tf:
            tf.write(
                "---\n"
                "date: 2026-05-24\n"
                "tags: [wiki]\n"
                "status: active\n"
                "wiki_status: bootstrap\n"
                "source:\n"
                f"  - {{path: CLAUDE.md, type: schema-doctrine, sha256: {sha}, ingested_at: '2026-05-24T00:00:00Z'}}\n"
                "---\n"
                "# Test wiki page\n\nBody."
            )
            test_path = tf.name
        try:
            rc, out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": test_path},
            })
            self.assertEqual(rc, 0)
            # Should pass cleanly OR emit advisory; either way exit 0
        finally:
            Path(test_path).unlink(missing_ok=True)

    def test_notes_without_wiki_tag_passes(self):
        # Files under Notes/ are wiki-layer ONLY if they carry #wiki tag.
        # A Notes/ file lacking the tag should pass without check.
        notes_dir = wcc.VAULT / "Notes"
        if not notes_dir.exists():
            self.skipTest("Notes/ not present in this environment")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=str(notes_dir), delete=False, encoding="utf-8"
        ) as tf:
            tf.write(
                "---\n"
                "date: 2026-05-24\n"
                "tags: [research]\n"
                "status: active\n"
                "---\n"
                "Plain research note without #wiki tag."
            )
            test_path = tf.name
        try:
            rc, out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": test_path},
            })
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")  # silent pass — not a wiki file
        finally:
            Path(test_path).unlink(missing_ok=True)


class MalformedInputTests(unittest.TestCase):
    def test_malformed_json_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             mock.patch.object(wcc, "log_decision", lambda *a, **k: None), \
             redirect_stdout(captured):
            rc = wcc.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")

    def test_empty_stdin_passes(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             mock.patch.object(wcc, "log_decision", lambda *a, **k: None), \
             redirect_stdout(captured):
            rc = wcc.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")


class WikiCitationBoundaryTests(unittest.TestCase):
    """Named FP-guards (boundary-test harness sprint 8). Each docstring names its
    boundary_axis. The two exemption axes (type:generated, type:schema-doctrine)
    are origin:regression — they were real SOURCE_DRIFT misfires before their
    exemptions shipped. A misfire would surface as SOURCE_DRIFT in the output."""

    def _drift(self, out: str) -> bool:
        return "SOURCE_DRIFT" in out or "SOURCE DRIFT" in out.upper()

    def test_fp_generated_source_no_sha_silent(self):
        """FP-WC-01 boundary_axis: 'curated source (SHA-pinned) vs type:generated (SHA-exempt)'.
        origin: regression (the registry.json SOURCE_DRIFT misfire). A #wiki page citing an
        auto-generated file as type:generated WITHOUT a sha256 must NOT raise SOURCE_DRIFT —
        the SHA legitimately changes every regeneration."""
        kb_dir = wcc.VAULT / "Resources" / "KB"
        gen = wcc.VAULT / ".claude" / "registry.json"
        if not kb_dir.exists() or not gen.is_file():
            self.skipTest("KB or registry.json not present")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=str(kb_dir),
                                          delete=False, encoding="utf-8") as tf:
            tf.write(
                "---\ndate: 2026-06-02\ntags: [wiki]\nstatus: active\nwiki_status: bootstrap\n"
                "source:\n"
                "  - {path: .claude/registry.json, type: generated, ingested_at: '2026-06-02T00:00:00Z'}\n"
                "---\n# Registry note\n\nSummarizes the generated registry inventory."
            )
            test_path = tf.name
        try:
            rc, out = _run({"tool_name": "Write", "tool_input": {"file_path": test_path}})
            self.assertEqual(rc, 0)
            self.assertFalse(self._drift(out), f"type:generated raised drift: {out[:200]}")
        finally:
            Path(test_path).unlink(missing_ok=True)

    def test_fp_schema_doctrine_source_silent(self):
        """FP-WC-02 boundary_axis: 'volatile doctrine whole-file SHA vs schema-doctrine (anchor-enforced)'.
        origin: regression (the CLAUDE.md drift misfire). A page citing CLAUDE.md as
        type:schema-doctrine must NOT raise SOURCE_DRIFT on whole-file hash churn."""
        kb_dir = wcc.VAULT / "Resources" / "KB"
        claude_md = wcc.VAULT / "CLAUDE.md"
        if not kb_dir.exists() or not claude_md.is_file():
            self.skipTest("KB or CLAUDE.md not present")
        import hashlib
        sha = hashlib.sha256(claude_md.read_bytes()).hexdigest()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=str(kb_dir),
                                          delete=False, encoding="utf-8") as tf:
            tf.write(
                "---\ndate: 2026-06-02\ntags: [wiki]\nstatus: active\nwiki_status: bootstrap\n"
                "source:\n"
                f"  - {{path: CLAUDE.md, type: schema-doctrine, anchor: '## Conventions', sha256: {sha}, ingested_at: '2026-06-02T00:00:00Z'}}\n"
                "---\n# Doctrine note\n\nReferences the Conventions section."
            )
            test_path = tf.name
        try:
            rc, out = _run({"tool_name": "Write", "tool_input": {"file_path": test_path}})
            self.assertEqual(rc, 0)
            self.assertFalse(self._drift(out), f"schema-doctrine raised drift: {out[:200]}")
        finally:
            Path(test_path).unlink(missing_ok=True)

    def test_fp_notes_without_wiki_tag_silent(self):
        """FP-WC-03 boundary_axis: 'wiki-tagged file vs untagged Notes file'.
        A Notes/ file without a #wiki tag is raw-layer and the check must not activate."""
        notes_dir = wcc.VAULT / "Notes"
        if not notes_dir.exists():
            self.skipTest("Notes/ not present")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=str(notes_dir),
                                          delete=False, encoding="utf-8") as tf:
            tf.write("---\ndate: 2026-06-02\ntags: [research]\nstatus: active\n---\nPlain note.")
            test_path = tf.name
        try:
            rc, out = _run({"tool_name": "Write", "tool_input": {"file_path": test_path}})
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")
        finally:
            Path(test_path).unlink(missing_ok=True)

    def test_fp_non_wiki_vault_path_silent(self):
        """FP-WC-04 boundary_axis: 'Resources/KB wiki path vs Projects/*/work path'.
        A work-artifact path in the vault is raw-layer — the check must not activate."""
        p = str(wcc.VAULT / "Projects" / "X" / "work" / "scratch.md")
        rc, out = _run({"tool_name": "Write", "tool_input": {"file_path": p}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
