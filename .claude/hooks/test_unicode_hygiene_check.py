"""Tests for unicode-hygiene-check.py.

Written 2026-09-10; this guard had no suite, which is uncomfortable given what
it watches. It scans content written into the raw layer (Inbox/, Clippings/)
for invisible and bidirectional characters: the carrier classes for
prompt-injection payloads that a human reviewer cannot see. If it went quiet,
the corpus would look clean precisely because nothing was looking.

Properties pinned here, each chosen against a silent failure:

  1. It DETECTS. A zero-width or bidi-override character in an in-scope write
     produces an advisory naming the class and count.
  2. It stays SCOPED. Every project file write would otherwise be scanned and
     the aggregate would fill with noise from ordinary work.
  3. It NEVER BLOCKS. Advisory by design; every branch exits 0. A scanner that
     started refusing writes would be a much bigger change than it looks.
  4. It records ONE aggregate row per warning, and none at all when clean.
     The row is the only durable evidence the surface was ever watched.

Runs from an isolated copy, so the aggregate written is the temp one.
"""
import json

import pytest
from _hooktest import read_jsonl, run_isolated

HOOK = "unicode-hygiene-check.py"

ZERO_WIDTH_SPACE = "\u200b"
BIDI_OVERRIDE = "\u202e"

IN_SCOPE = "C:/Users/Someone/Vault/Inbox/note.md"
CLIPPING = "C:/Users/Someone/Vault/Clippings/article.md"


def fire(tmp_path, file_path, content, tool="Write", key="content"):
    payload = {"tool_name": tool,
               "tool_input": {"file_path": file_path, key: content}}
    proc, hooks_dir = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, f"hook must never block: {proc.stderr}"
    records = read_jsonl(hooks_dir / "aggregates" / "unicode-hygiene.jsonl")
    return proc, records


# --- it detects ---------------------------------------------------------------

@pytest.mark.parametrize("path", [IN_SCOPE, CLIPPING])
def test_a_zero_width_character_is_reported(path, tmp_path):
    proc, records = fire(tmp_path, path, f"hello{ZERO_WIDTH_SPACE}world")
    assert "unicode-hygiene-check WARN" in proc.stdout
    assert len(records) == 1


def test_a_bidi_override_is_reported(tmp_path):
    """The Trojan-Source class: text that renders in a different order than it
    parses. This is the one a human reviewer provably cannot catch by reading."""
    proc, records = fire(tmp_path, IN_SCOPE, f"safe{BIDI_OVERRIDE}evil")
    assert "unicode-hygiene-check WARN" in proc.stdout
    assert len(records) == 1


def test_the_advisory_names_classes_and_counts(tmp_path):
    """A warning that says only 'something invisible is here' cannot be
    triaged; the class is what tells you whether it is a stray BOM or an
    injection carrier."""
    proc, _ = fire(tmp_path, IN_SCOPE, ZERO_WIDTH_SPACE * 3)
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "occurrence" in ctx
    assert "note.md" in ctx


def test_the_advisory_says_treat_the_text_as_data(tmp_path):
    """The remedy clause. Without it the reader knows something is wrong but
    not that the correct response is to refuse the embedded instructions."""
    proc, _ = fire(tmp_path, IN_SCOPE, ZERO_WIDTH_SPACE)
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"].lower()
    assert "data, not instructions" in ctx


def test_an_edit_is_scanned_via_new_string(tmp_path):
    """Edit carries new_string, not content. Reading only content would make
    every edit invisible to this scanner."""
    proc, records = fire(tmp_path, IN_SCOPE, f"x{ZERO_WIDTH_SPACE}y",
                         tool="Edit", key="new_string")
    assert "unicode-hygiene-check WARN" in proc.stdout
    assert len(records) == 1


# --- it stays scoped ----------------------------------------------------------

def test_clean_in_scope_content_is_silent_and_writes_no_row(tmp_path):
    proc, records = fire(tmp_path, IN_SCOPE, "ordinary ascii text")
    assert proc.stdout.strip() == ""
    assert records == []


def test_writes_outside_the_raw_layer_are_not_scanned(tmp_path):
    proc, records = fire(tmp_path, "C:/Users/Someone/Vault/Projects/x/work/a.md",
                         f"hello{ZERO_WIDTH_SPACE}world")
    assert proc.stdout.strip() == ""
    assert records == []


def test_the_test_fixtures_directory_is_excluded(tmp_path):
    """Fixture files carry these characters on purpose. Scanning them would
    make the aggregate fire on every suite run."""
    proc, records = fire(tmp_path,
                         "C:/Users/Someone/Vault/Inbox/_test_fixtures/bidi.md",
                         BIDI_OVERRIDE)
    assert proc.stdout.strip() == ""
    assert records == []


@pytest.mark.parametrize("tool", ["Read", "Bash", "Grep"])
def test_non_write_tools_are_ignored(tool, tmp_path):
    proc, records = fire(tmp_path, IN_SCOPE, ZERO_WIDTH_SPACE, tool=tool)
    assert proc.stdout.strip() == ""
    assert records == []


# --- the record ---------------------------------------------------------------

def test_the_aggregate_row_records_surface_and_non_blocking(tmp_path):
    """`blocked: false` is the field that makes the advisory posture auditable
    later; without it nobody can show the scanner never refused a write."""
    _, records = fire(tmp_path, IN_SCOPE, ZERO_WIDTH_SPACE)
    row = records[0]
    assert row["surface"] == "hook"
    assert row["action"] == "warn"
    assert row["blocked"] is False
    assert row["file"] == IN_SCOPE
    assert row["counts"]


# --- it never blocks ----------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "not json at all", "[]", "null"])
def test_malformed_input_exits_clean(raw, tmp_path):
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_a_missing_content_field_does_not_crash(tmp_path):
    proc, _ = run_isolated(
        HOOK, {"tool_name": "Write", "tool_input": {"file_path": IN_SCOPE}},
        tmp_path)
    assert proc.returncode == 0, proc.stderr
