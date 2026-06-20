"""Unit tests for _wiki_citation_logic.

Run: pytest .claude/hooks/test_wiki_citation_logic.py -v
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# Ensure hooks dir is importable
_HOOK_DIR = Path(__file__).parent
if str(_HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOK_DIR))

import pytest  # noqa: E402

from _wiki_citation_logic import (  # noqa: E402
    EXCLUDE_FILES,
    format_findings_message,
    has_wiki_tag,
    is_wiki_path,
    is_wiki_path_by_tag,
    is_wiki_path_unconditional,
    normalize_rel_path,
    parse_source_field,
    validate_source_entries,
)


# ---------------------------------------------------------------------------
# normalize_rel_path
# ---------------------------------------------------------------------------

class TestNormalizeRelPath:
    def test_backslash_to_forward(self):
        assert normalize_rel_path(r"Resources\KB\foo.md") == "Resources/KB/foo.md"

    def test_strip_leading_slash(self):
        assert normalize_rel_path("/Resources/KB/foo.md") == "Resources/KB/foo.md"

    def test_already_normalized(self):
        assert normalize_rel_path("Resources/KB/foo.md") == "Resources/KB/foo.md"


# ---------------------------------------------------------------------------
# is_wiki_path family
# ---------------------------------------------------------------------------

class TestIsWikiPathUnconditional:
    def test_resources_kb_is_unconditional(self):
        assert is_wiki_path_unconditional("Resources/KB/foo.md") is True

    def test_notes_is_not_unconditional(self):
        assert is_wiki_path_unconditional("Notes/foo.md") is False

    def test_excludes_index_md(self):
        for excluded in EXCLUDE_FILES:
            assert is_wiki_path_unconditional(f"Resources/KB/{excluded}") is False

    def test_backslash_paths_normalized(self):
        assert is_wiki_path_unconditional(r"Resources\KB\foo.md") is True


class TestIsWikiPathByTag:
    def test_notes_path(self):
        assert is_wiki_path_by_tag("Notes/foo.md") is True

    def test_projects_archive_only(self):
        assert is_wiki_path_by_tag("Projects/X/archive/foo.md") is True
        assert is_wiki_path_by_tag("Projects/X/work/foo.md") is False

    def test_resources_kb_is_not_by_tag(self):
        # KB is unconditional, NOT by-tag
        assert is_wiki_path_by_tag("Resources/KB/foo.md") is False

    def test_excludes_state_md(self):
        assert is_wiki_path_by_tag("Notes/STATE.md") is False


class TestIsWikiPathCombined:
    def test_unconditional_path(self):
        assert is_wiki_path("Resources/KB/foo.md") is True

    def test_by_tag_path(self):
        assert is_wiki_path("Notes/foo.md") is True

    def test_non_wiki_path(self):
        assert is_wiki_path("CLAUDE.md") is False
        assert is_wiki_path("Inbox/foo.md") is False


# ---------------------------------------------------------------------------
# has_wiki_tag
# ---------------------------------------------------------------------------

class TestHasWikiTag:
    def test_yaml_list_with_wiki(self):
        content = "---\ntags: [wiki, foo]\n---\nbody"
        assert has_wiki_tag(content) is True

    def test_yaml_list_with_hash_prefix(self):
        content = "---\ntags: [#wiki, foo]\n---\nbody"
        assert has_wiki_tag(content) is True

    def test_no_frontmatter(self):
        assert has_wiki_tag("just body, no frontmatter") is False

    def test_tags_without_wiki(self):
        content = "---\ntags: [research, analysis]\n---\nbody"
        assert has_wiki_tag(content) is False

    def test_malformed_frontmatter_no_close(self):
        content = "---\ntags: [wiki]\nbody"  # no closing ---
        assert has_wiki_tag(content) is False

    def test_multiline_yaml_tags_block(self):
        """Regression guard: multiline block-list form with '- wiki' → True."""
        multiline = "---\ntags:\n  - wiki\n  - foo\nstatus: active\n---\nbody"
        assert has_wiki_tag(multiline) is True

    def test_multiline_quoted_hash_prefix(self):
        """'- \"#wiki\"' (quoted, hash-prefixed) must match."""
        content = '---\ntags:\n  - "#wiki"\n  - moc\n---\nbody'
        assert has_wiki_tag(content) is True

    def test_multiline_without_wiki(self):
        """Multiline tags list with no wiki item → False."""
        content = "---\ntags:\n  - moc\n  - research\n---\nbody"
        assert has_wiki_tag(content) is False

    def test_multiline_wiki_derived_no_false_positive(self):
        """'- wiki-derived' must NOT match (substring, not exact)."""
        content = "---\ntags:\n  - wiki-derived\n  - moc\n---\nbody"
        assert has_wiki_tag(content) is False

    def test_multiline_wikilink_no_false_positive(self):
        """'- wikilink' must NOT match: spec-named negative case (exact match only)."""
        content = "---\ntags:\n  - wikilink\n  - moc\n---\nbody"
        assert has_wiki_tag(content) is False

    def test_no_frontmatter_multiline_variant(self):
        """No frontmatter at all → False (belt-and-suspenders for multiline path)."""
        assert has_wiki_tag("tags:\n  - wiki\nbody") is False


# ---------------------------------------------------------------------------
# parse_source_field
# ---------------------------------------------------------------------------

class TestParseSourceField:
    def test_no_frontmatter_returns_none(self):
        assert parse_source_field("just body") is None

    def test_no_source_field_returns_empty_list(self):
        content = "---\ntags: [wiki]\n---\nbody"
        assert parse_source_field(content) == []

    def test_single_source_entry(self):
        content = (
            "---\n"
            "tags: [wiki]\n"
            "source:\n"
            "  - path: Inbox/test.md\n"
            "    sha256: abc123\n"
            "---\n"
            "body"
        )
        entries = parse_source_field(content)
        assert entries is not None
        assert len(entries) == 1
        assert entries[0]["path"] == "Inbox/test.md"
        assert entries[0]["sha256"] == "abc123"

    def test_multiple_source_entries(self):
        content = (
            "---\n"
            "source:\n"
            "  - path: a.md\n"
            "    sha256: aaa\n"
            "  - path: b.md\n"
            "    sha256: bbb\n"
            "---\n"
        )
        entries = parse_source_field(content)
        assert entries is not None
        assert len(entries) == 2
        assert entries[0]["path"] == "a.md"
        assert entries[1]["path"] == "b.md"

    def test_quoted_values_unquoted(self):
        content = (
            "---\n"
            "source:\n"
            '  - path: "Inbox/test.md"\n'
            "---\n"
        )
        entries = parse_source_field(content)
        assert entries is not None
        assert entries[0]["path"] == "Inbox/test.md"


# ---------------------------------------------------------------------------
# validate_source_entries (filesystem-touching)
# ---------------------------------------------------------------------------

class TestValidateSourceEntries:
    def test_empty_entries_produces_missing_source(self, tmp_path: Path):
        findings, blocking = validate_source_entries([], tmp_path)
        codes = [f["code"] for f in findings]
        assert "MISSING_SOURCE" in codes
        assert blocking is True

    def test_missing_path_field(self, tmp_path: Path):
        findings, blocking = validate_source_entries([{"sha256": "abc"}], tmp_path)
        codes = [f["code"] for f in findings]
        assert "EMPTY_SOURCE_PATH" in codes
        assert blocking is True

    def test_orphan_citation_when_file_absent(self, tmp_path: Path):
        findings, blocking = validate_source_entries(
            [{"path": "does-not-exist.md", "sha256": "x"}],
            tmp_path,
        )
        codes = [f["code"] for f in findings]
        assert "ORPHAN_CITATION" in codes
        assert blocking is True

    def test_source_drift_when_hash_mismatches(self, tmp_path: Path):
        src = tmp_path / "src.md"
        src.write_text("hello", encoding="utf-8")
        findings, blocking = validate_source_entries(
            [{"path": "src.md", "sha256": "0" * 64}],
            tmp_path,
        )
        codes = [f["code"] for f in findings]
        assert "SOURCE_DRIFT" in codes
        # SOURCE_DRIFT is severity=warning, not blocking
        assert blocking is False

    def test_clean_pass_with_correct_hash(self, tmp_path: Path):
        src = tmp_path / "src.md"
        content = b"hello"
        src.write_bytes(content)
        actual_hash = hashlib.sha256(content).hexdigest()
        findings, blocking = validate_source_entries(
            [{"path": "src.md", "sha256": actual_hash}],
            tmp_path,
        )
        # No findings = clean pass
        assert findings == []
        assert blocking is False

    def test_missing_sha_is_warning(self, tmp_path: Path):
        src = tmp_path / "src.md"
        src.write_text("x", encoding="utf-8")
        findings, blocking = validate_source_entries(
            [{"path": "src.md"}],  # no sha256
            tmp_path,
        )
        codes = [f["code"] for f in findings]
        assert "MISSING_SHA" in codes
        assert blocking is False


# ---------------------------------------------------------------------------
# format_findings_message
# ---------------------------------------------------------------------------

class TestFormatFindingsMessage:
    def test_empty_findings_just_path(self):
        msg = format_findings_message("a.md", [], has_blocking=False)
        assert "a.md" in msg
        assert "blocking-level" not in msg

    def test_with_blocking_finding(self):
        findings = [{"code": "ORPHAN", "severity": "error", "message": "missing"}]
        msg = format_findings_message("a.md", findings, has_blocking=True)
        assert "ORPHAN" in msg
        assert "missing" in msg
        assert "blocking-level" in msg


# ---------------------------------------------------------------------------
# inline-flow source form (2026-06-01): '- {path: X, type: Y, anchor: Z}'
# ---------------------------------------------------------------------------

class TestInlineFlowSource:
    def test_inline_flow_single_entry(self):
        content = (
            "---\n"
            "source:\n"
            "- {path: CLAUDE.md, type: schema-doctrine, anchor: n8n Working Patterns, "
            "ingested_at: '2026-05-10T21:42:04Z'}\n"
            "---\nbody\n"
        )
        entries = parse_source_field(content)
        assert entries == [{
            "path": "CLAUDE.md",
            "type": "schema-doctrine",
            "anchor": "n8n Working Patterns",
            "ingested_at": "2026-05-10T21:42:04Z",
        }]

    def test_inline_flow_value_with_colon_preserved(self):
        # timestamp value contains colons: split on FIRST colon only
        content = (
            "---\nsource:\n"
            "- {path: a.md, ingested_at: '2026-05-10T21:42:04Z'}\n---\n"
        )
        entries = parse_source_field(content)
        assert entries[0]["ingested_at"] == "2026-05-10T21:42:04Z"

    def test_block_list_still_parses(self):
        content = (
            "---\nsource:\n"
            '  - path: "x.md"\n'
            "    type: clipping\n"
            '    sha256: "abc"\n---\n'
        )
        entries = parse_source_field(content)
        assert entries == [{"path": "x.md", "type": "clipping", "sha256": "abc"}]


# ---------------------------------------------------------------------------
# type: schema-doctrine: skip SHA, enforce anchor existence (2026-06-01)
# ---------------------------------------------------------------------------

class TestSchemaDoctrineSource:
    def _doc(self, tmp_path: Path) -> Path:
        src = tmp_path / "DOCTRINE.md"
        src.write_text(
            "# Title\n\n## n8n Working Patterns (2026)\n\nbody\n",
            encoding="utf-8",
        )
        return src

    def test_existing_anchor_clean_no_sha_needed(self, tmp_path: Path):
        self._doc(tmp_path)
        findings, blocking = validate_source_entries(
            [{"path": "DOCTRINE.md", "type": "schema-doctrine",
              "anchor": "n8n Working Patterns"}],
            tmp_path,
        )
        assert findings == []
        assert blocking is False

    def test_stale_sha_ignored_no_drift(self, tmp_path: Path):
        # a wrong sha must NOT produce SOURCE_DRIFT for schema-doctrine
        self._doc(tmp_path)
        findings, _ = validate_source_entries(
            [{"path": "DOCTRINE.md", "type": "schema-doctrine",
              "anchor": "n8n Working Patterns", "sha256": "deadbeef"}],
            tmp_path,
        )
        assert [f["code"] for f in findings] == []

    def test_fabricated_anchor_blocks(self, tmp_path: Path):
        self._doc(tmp_path)
        findings, blocking = validate_source_entries(
            [{"path": "DOCTRINE.md", "type": "schema-doctrine",
              "anchor": "Nonexistent Section"}],
            tmp_path,
        )
        assert "ORPHAN_ANCHOR" in [f["code"] for f in findings]
        assert blocking is True

    def test_missing_anchor_blocks(self, tmp_path: Path):
        self._doc(tmp_path)
        findings, blocking = validate_source_entries(
            [{"path": "DOCTRINE.md", "type": "schema-doctrine"}],
            tmp_path,
        )
        assert "MISSING_ANCHOR" in [f["code"] for f in findings]
        assert blocking is True

    def test_missing_file_still_orphan(self, tmp_path: Path):
        findings, blocking = validate_source_entries(
            [{"path": "GONE.md", "type": "schema-doctrine",
              "anchor": "Whatever"}],
            tmp_path,
        )
        assert "ORPHAN_CITATION" in [f["code"] for f in findings]
        assert blocking is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
