"""Tests for claude-md-provenance-check.py (Guard A, Mechanism A countermeasure).

Warn-only PostToolUse hook scoped to the vault-root CLAUDE.md: a rule-shaped
change with no inline origin citation gets a one-line warning. pytest style.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "claude_md_provenance_check",
    str(Path(__file__).parent / "claude-md-provenance-check.py"),
)
cmpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmpc)

CLAUDE_MD = os.path.join(cmpc.VAULT_ROOT, "CLAUDE.md")

BANNED_GLYPHS = "‒–—―−⸺⸻﹘－"


def _run(file_path, new_string=None, content=None, raw=None):
    if raw is None:
        tool_input = {"file_path": file_path}
        if new_string is not None:
            tool_input["new_string"] = new_string
        if content is not None:
            tool_input["content"] = content
        raw = json.dumps({"tool_name": "Edit", "tool_input": tool_input})
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(raw)), redirect_stderr(captured):
        rc = cmpc.main()
    return captured.getvalue(), rc


RULE_CITED = (
    "## CRITICAL RULE: Example Rule (2026-08-11)\n\n"
    "**Never do the thing without checking.** Derived from "
    "[[2026-08-10-caveman-postmortem]] Mechanism A.\n"
)

RULE_UNCITED = (
    "## CRITICAL RULE: Example Rule\n\n"
    "**Never do the thing without checking.** This is enforced at runtime.\n"
)


def test_cited_rule_addition_silent():
    err, rc = _run(CLAUDE_MD, new_string=RULE_CITED)
    assert (err, rc) == ("", 0)


def test_uncited_rule_shaped_addition_warns():
    err, rc = _run(CLAUDE_MD, new_string=RULE_UNCITED)
    assert rc == 0, "warn-only: the hook must never block"
    assert "provenance" in err.lower() or "origin citation" in err.lower()


def test_warn_text_contains_no_dash_glyphs():
    err, _ = _run(CLAUDE_MD, new_string=RULE_UNCITED)
    assert err
    assert not any(g in err for g in BANNED_GLYPHS)


def test_non_claude_md_path_out_of_scope():
    err, rc = _run("Projects/your-project/work/CLAUDE-notes.md", new_string=RULE_UNCITED)
    assert (err, rc) == ("", 0)


def test_nested_claude_md_out_of_scope():
    err, rc = _run(os.path.join(cmpc.VAULT_ROOT, "Projects", "X", "CLAUDE.md"), new_string=RULE_UNCITED)
    assert (err, rc) == ("", 0)


def test_trivial_non_rule_edit_silent():
    err, rc = _run(CLAUDE_MD, new_string="87 agents, 164 skills, across 34 installed plugins.")
    assert (err, rc) == ("", 0)


def test_memo_name_counts_as_provenance():
    text = "## New Rule\n**Always check twice.** Per feedback_no_push_without_asking.md.\n"
    err, rc = _run(CLAUDE_MD, new_string=text)
    assert (err, rc) == ("", 0)


def test_dated_parenthetical_counts_as_provenance():
    text = "**Never rely on memory for IDs (2026-08-11, session ruling).**\n"
    err, rc = _run(CLAUDE_MD, new_string=text)
    assert (err, rc) == ("", 0)


def test_write_payload_full_content_scanned():
    err, rc = _run(CLAUDE_MD, content=RULE_UNCITED)
    assert rc == 0
    assert err != ""


def test_malformed_payload_exits_zero():
    err, rc = _run(None, raw="{not json")
    assert (err, rc) == ("", 0)


def test_empty_stdin_exits_zero():
    err, rc = _run(None, raw="")
    assert (err, rc) == ("", 0)


def test_hook_cannot_emit_blocking_decision():
    """No code path returns nonzero: the worst uncited rule text still allows."""
    worst = "## CRITICAL RULE: X\n**Never** and **must** and CRITICAL RULE everywhere.\n"
    _, rc = _run(CLAUDE_MD, new_string=worst)
    assert rc == 0
    source = (Path(__file__).parent / "claude-md-provenance-check.py").read_text(encoding="utf-8")
    assert "return 2" not in source and "exit(2)" not in source
