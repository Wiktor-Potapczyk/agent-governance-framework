"""Tests for plain-language-guard.py, the warn-only PostToolUse Write|Edit hook.

Written BEFORE the hook (declarative-first). Every log path is monkeypatched to
tmp; the live aggregates file and hook-activity.jsonl are never touched (the
hooks conftest.py redirects _governance_logger session-wide; the aggregates
path is patched per-test here). pytest style, no unittest.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "plain_language_guard",
    str(Path(__file__).parent / "plain-language-guard.py"),
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

IN_SCOPE = "C:\\Users\\exampleuser\\Workspace\\Projects\\your-project\\work\\2026-08-11-note.md"
KB_SCOPE = "Resources/KB/some-page.md"
REPO_SCOPE = "Projects/your-project/framework-repo/docs/architecture.md"
OUT_SCOPE = "Inbox/some-dump.md"
BACKUPS = "Projects/your-project/work/backups/scratch.md"

VIOLATING = "Utilize the API prior to commencing the export. Several various issues.\n"
CLEAN = "The hook works.\n"
MM1_MARKED = (
    "<!-- MM1 -->\nThis command permanently deletes the production table and it "
    "cannot be undone by any later action, so you must confirm that a verified "
    "backup exists before you run the command and you must proceed only after "
    "the owner has approved the deletion in writing.\n<!-- /MM1 -->\n"
)


def _run(tmp_path, file_path, content=None, new_string=None, tool="Write"):
    """Invoke main() with a PostToolUse payload; return (stderr, rc, log_lines)."""
    log = tmp_path / "plain-language-warnings.jsonl"
    tool_input = {"file_path": file_path}
    if content is not None:
        tool_input["content"] = content
    if new_string is not None:
        tool_input["new_string"] = new_string
    payload = {"tool_name": tool, "tool_input": tool_input, "session_id": "test-session"}
    captured = io.StringIO()
    with mock.patch.object(guard, "AGG_LOG_PATH", str(log)), \
         mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stderr(captured):
        rc = guard.main()
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return captured.getvalue(), rc, lines


def test_in_scope_findings_one_record_plus_advisory(tmp_path):
    err, rc, lines = _run(tmp_path, IN_SCOPE, content=VIOLATING)
    assert rc == 0
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["path"].endswith("2026-08-11-note.md")
    assert record["total_findings"] > 0
    assert "plain-language-guard" in err and "PL-5" in err


def test_in_scope_clean_write_one_zero_record_no_advisory(tmp_path):
    """The B1 zero-finding logging case, verbatim from the plan-of-record Stage 2 gate."""
    err, rc, lines = _run(tmp_path, IN_SCOPE, content=CLEAN)
    assert rc == 0
    assert err == ""
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["total_findings"] == 0
    counts = record["per_rule_finding_counts"]
    assert sorted(counts.keys()) == sorted(f"PL-{i}" for i in range(1, 11))
    assert all(v == 0 for v in counts.values())


def test_record_carries_all_five_fields(tmp_path):
    _, _, lines = _run(tmp_path, IN_SCOPE, content=CLEAN)
    record = json.loads(lines[0])
    assert set(record.keys()) == {"ts", "session", "path", "per_rule_finding_counts", "total_findings"}
    assert record["session"] == "test-session"


def test_kb_and_framework_repo_paths_in_scope(tmp_path):
    # The log accumulates in one tmp file: one new record per in-scope write.
    for i, path in enumerate((KB_SCOPE, REPO_SCOPE), start=1):
        _, _, lines = _run(tmp_path, path, content=CLEAN)
        assert len(lines) == i, path
        assert json.loads(lines[-1])["path"] == path


def test_out_of_scope_write_produces_nothing(tmp_path):
    err, rc, lines = _run(tmp_path, OUT_SCOPE, content=VIOLATING)
    assert (err, rc, lines) == ("", 0, [])


def test_backups_path_produces_nothing(tmp_path):
    err, rc, lines = _run(tmp_path, BACKUPS, content=VIOLATING)
    assert (err, rc, lines) == ("", 0, [])


def test_edit_payload_scanned_via_new_string(tmp_path):
    err, rc, lines = _run(tmp_path, IN_SCOPE, new_string=VIOLATING, tool="Edit")
    assert rc == 0
    assert len(lines) == 1
    assert json.loads(lines[0])["total_findings"] > 0
    assert "PL-5" in err


def test_forced_exception_fails_open(tmp_path):
    with mock.patch.object(guard, "scan", side_effect=RuntimeError("forced")):
        err, rc, lines = _run(tmp_path, IN_SCOPE, content=VIOLATING)
    assert rc == 0
    assert lines == []


def test_marked_mm1_content_logs_zero_finding_record(tmp_path):
    err, rc, lines = _run(tmp_path, IN_SCOPE, content=MM1_MARKED)
    assert rc == 0
    assert err == ""
    assert len(lines) == 1
    assert json.loads(lines[0])["total_findings"] == 0


def test_exactly_one_line_per_invocation(tmp_path):
    _, _, lines = _run(tmp_path, IN_SCOPE, content=VIOLATING)
    assert len(lines) == 1


def test_shipped_block_set_is_empty_and_cannot_block(tmp_path):
    assert guard.BLOCK_ENABLED_RULES == set()
    worst = VIOLATING * 20 + "It should be noted that basically WDAC breaks. The write is blocked.\n"
    _, rc, _ = _run(tmp_path, IN_SCOPE, content=worst)
    assert rc == 0, "with the shipped config no input may produce a blocking decision"


def test_block_path_exists_and_consults_the_set(tmp_path):
    """The Stage 4 machinery is present in code but OFF: enabling a rule flips
    the decision to a block (exit 2) for a violating write."""
    with mock.patch.object(guard, "BLOCK_ENABLED_RULES", {"PL-5"}):
        err, rc, lines = _run(tmp_path, IN_SCOPE, content=VIOLATING)
    assert rc == 2
    assert "BLOCK" in err
    assert len(lines) == 1, "the per-write record is appended even on a block"


def test_unclosed_marker_hygiene_advisory_surfaces(tmp_path):
    text = "<!-- MM1 -->\nExempt to end of file.\n"
    err, rc, lines = _run(tmp_path, IN_SCOPE, content=text)
    assert rc == 0
    assert "MM1" in err
    assert json.loads(lines[0])["total_findings"] == 0


def test_no_writes_to_guarded_files_in_source():
    source = (Path(__file__).parent / "plain-language-guard.py").read_text(encoding="utf-8")
    assert "governance-log.jsonl" not in source
    assert "MEMORY.md" not in source
    assert "hook-activity.jsonl" not in source, "activity logging must go through _governance_logger"
