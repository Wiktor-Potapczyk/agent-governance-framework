"""Smoke tests for memory-dedup-check.py: PreToolUse Write hook.

Soft warning only: emits additionalContext when token-overlap exceeds 65%
against an existing memory file. Never blocks. Pure functions covered
directly; main() covered via in-process stdin/stdout mocking.
"""

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
    "memory_dedup_check",
    str(Path(__file__).parent / "memory-dedup-check.py"),
)
mdc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mdc)


class IsMemoryFileTests(unittest.TestCase):
    def test_memory_file_recognized(self):
        self.assertTrue(mdc.is_memory_file(
            "/c/Users/X/.claude/projects/Foo/memory/feedback_x.md"
        ))

    def test_windows_path_recognized(self):
        self.assertTrue(mdc.is_memory_file(
            "C:\\Users\\X\\.claude\\projects\\Foo\\memory\\feedback_x.md"
        ))

    def test_memory_md_index_excluded(self):
        self.assertFalse(mdc.is_memory_file(
            "/c/.claude/projects/Foo/memory/MEMORY.md"
        ))

    def test_non_md_excluded(self):
        self.assertFalse(mdc.is_memory_file(
            "/c/.claude/projects/Foo/memory/data.json"
        ))

    def test_non_memory_path_excluded(self):
        self.assertFalse(mdc.is_memory_file("/c/Users/X/Desktop/note.md"))

    def test_empty_path(self):
        self.assertFalse(mdc.is_memory_file(""))


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_dedupes(self):
        tokens = mdc.tokenize("Foo bar BAR baz")
        self.assertEqual(tokens, {"foo", "bar", "baz"})

    def test_excludes_short_words(self):
        # Tokens shorter than 3 chars excluded
        tokens = mdc.tokenize("a be cat dog")
        self.assertNotIn("a", tokens)
        self.assertNotIn("be", tokens)
        self.assertIn("cat", tokens)
        self.assertIn("dog", tokens)


class ExtractDescriptionTests(unittest.TestCase):
    def test_from_content_plain(self):
        content = "---\nname: foo\ndescription: A note about X\nstatus: active\n---\nBody"
        self.assertEqual(mdc.extract_description_from_content(content), "A note about X")

    def test_from_content_quoted(self):
        content = '---\ndescription: "A note about X"\n---\n'
        self.assertEqual(mdc.extract_description_from_content(content), "A note about X")

    def test_from_content_missing(self):
        content = "---\nname: foo\nstatus: active\n---\nBody"
        self.assertEqual(mdc.extract_description_from_content(content), "")


class SimilarityTests(unittest.TestCase):
    def test_identical(self):
        a = {"foo", "bar", "baz"}
        self.assertEqual(mdc.compute_similarity(a, a), 1.0)

    def test_disjoint(self):
        self.assertEqual(mdc.compute_similarity({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial(self):
        sim = mdc.compute_similarity({"a", "b", "c", "d"}, {"a", "b", "x", "y"})
        # 2 overlap / 6 union = 1/3
        self.assertAlmostEqual(sim, 1/3, places=4)

    def test_empty_returns_zero(self):
        self.assertEqual(mdc.compute_similarity(set(), {"a"}), 0.0)
        self.assertEqual(mdc.compute_similarity({"a"}, set()), 0.0)


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        mdc.main()
    return captured.getvalue()


def _write_memory_file(memdir: Path, name: str, desc: str) -> None:
    (memdir / name).write_text(
        f"---\nname: {name[:-3]}\ndescription: {desc}\nstatus: active\n---\nBody.",
        encoding="utf-8",
    )


class MainEndToEndTests(unittest.TestCase):
    def test_non_memory_path_silent(self):
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": "/c/Users/X/Desktop/note.md", "content": "x"},
        })
        self.assertEqual(out.strip(), "{}")

    def test_empty_stdin_silent(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            mdc.main()
        self.assertEqual(captured.getvalue().strip(), "{}")

    def test_malformed_json_silent(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("garbage")), \
             redirect_stdout(captured):
            mdc.main()
        self.assertEqual(captured.getvalue().strip(), "{}")

    def test_novel_memory_file_passes(self):
        with tempfile.TemporaryDirectory() as td:
            memdir = Path(td) / ".claude" / "projects" / "Foo" / "memory"
            memdir.mkdir(parents=True)
            _write_memory_file(memdir, "existing_a.md", "alpha bravo charlie delta")
            new_path = memdir / "new_topic.md"
            content = (
                "---\nname: new-topic\ndescription: postgresql performance tuning indexes\n"
                "status: active\n---\nBody."
            )
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": str(new_path), "content": content},
            })
            self.assertEqual(out.strip(), "{}")

    def test_near_duplicate_warns(self):
        with tempfile.TemporaryDirectory() as td:
            memdir = Path(td) / ".claude" / "projects" / "Foo" / "memory"
            memdir.mkdir(parents=True)
            _write_memory_file(memdir, "existing_a.md", "postgresql performance tuning indexes")
            new_path = memdir / "new_b.md"
            content = (
                "---\nname: new-b\ndescription: postgresql performance tuning indexes\n"
                "status: active\n---\nBody."
            )
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": str(new_path), "content": content},
            })
            result = json.loads(out)
            self.assertIn("additionalContext", result)
            self.assertIn("MEMORY DEDUP", result["additionalContext"])
            self.assertIn("existing_a.md", result["additionalContext"])

    def test_missing_description_silent(self):
        with tempfile.TemporaryDirectory() as td:
            memdir = Path(td) / ".claude" / "projects" / "Foo" / "memory"
            memdir.mkdir(parents=True)
            new_path = memdir / "new.md"
            content = "---\nname: new\nstatus: active\n---\nBody"
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": str(new_path), "content": content},
            })
            self.assertEqual(out.strip(), "{}")

    def test_too_few_tokens_silent(self):
        with tempfile.TemporaryDirectory() as td:
            memdir = Path(td) / ".claude" / "projects" / "Foo" / "memory"
            memdir.mkdir(parents=True)
            new_path = memdir / "new.md"
            # Only 2 tokens >= 3 chars: "foo" and "bar"
            content = "---\nname: new\ndescription: foo bar\nstatus: active\n---\nBody"
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": str(new_path), "content": content},
            })
            self.assertEqual(out.strip(), "{}")

    def test_self_excluded(self):
        # Updating an existing file (same basename) should not flag itself as a dup
        with tempfile.TemporaryDirectory() as td:
            memdir = Path(td) / ".claude" / "projects" / "Foo" / "memory"
            memdir.mkdir(parents=True)
            _write_memory_file(memdir, "topic.md", "alpha bravo charlie delta echo")
            path = memdir / "topic.md"
            content = (
                "---\nname: topic\ndescription: alpha bravo charlie delta echo\n"
                "status: active\n---\nUpdated body."
            )
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": content},
            })
            self.assertEqual(out.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
