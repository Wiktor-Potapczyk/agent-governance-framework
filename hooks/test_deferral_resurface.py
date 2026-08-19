"""Tests for deferral-resurface.py (Guard B, Mechanism B countermeasure).

Sweep mode: proposal-generating only, zero writes outside the one proposal
file. Close-advisor mode: warn-only on status-flip writes. pytest style.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "deferral_resurface",
    str(Path(__file__).parent / "deferral-resurface.py"),
)
drs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drs)


def _fixture_project(tmp_path):
    proj = tmp_path / "Projects" / "Fixture-Project"
    (proj / "work").mkdir(parents=True)
    (proj / "archive").mkdir(parents=True)
    (proj / "task_plan.md").write_text(
        "# Plan\n"
        "- [x] shipped item\n"
        "## Future Work (deferred)\n"
        "- [ ] Caveman deep-dive, token compression for MEMORY.md\n"
        "## Other\n"
        "- [ ] open ticket under a non-deferral heading\n"
        "MM1 routed to Batch 2, Tier 3 (MEDIUM), effort XS\n",
        encoding="utf-8",
    )
    (proj / "work" / "2026-05-08-backlog.md").write_text(
        "REPORT-ONLY: two candidate guards, ticketed separately\n"
        "This line is plain prose.\n"
        "Second guard marked owner-decision-pending for now\n",
        encoding="utf-8",
    )
    (proj / "archive" / "old-notes.md").write_text(
        "Item parked: HOLD until the import test runs\n",
        encoding="utf-8",
    )
    return proj


def _tree_snapshot(root):
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _run_sweep(proj):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = drs.main(["--project", str(proj)])
    return rc, out.getvalue()


def test_sweep_finds_markers_with_file_line_quote(tmp_path):
    proj = _fixture_project(tmp_path)
    rc, _ = _run_sweep(proj)
    assert rc == 0
    proposals = list((proj / "work").glob("*deferral-resurface-proposal.md"))
    assert len(proposals) == 1
    text = proposals[0].read_text(encoding="utf-8")
    assert "task_plan.md:4" in text and "Caveman deep-dive" in text
    assert "task_plan.md:7" in text and "Tier 3" in text
    assert "2026-05-08-backlog.md:1" in text and "REPORT-ONLY" in text
    assert "2026-05-08-backlog.md:3" in text and "owner-decision-pending" in text
    assert "old-notes.md:1" in text and "HOLD until" in text
    assert "plain prose" not in text
    assert "non-deferral heading" not in text


def test_sweep_proposal_has_owner_disposition_lines(tmp_path):
    proj = _fixture_project(tmp_path)
    _run_sweep(proj)
    text = next((proj / "work").glob("*deferral-resurface-proposal.md")).read_text(encoding="utf-8")
    assert text.count("adopt / re-ticket / reject") >= 5


def test_clean_project_yields_explicit_zero_proposal(tmp_path):
    proj = tmp_path / "Projects" / "Clean-Project"
    (proj / "work").mkdir(parents=True)
    (proj / "task_plan.md").write_text("# Plan\n- [x] all done\n", encoding="utf-8")
    rc, _ = _run_sweep(proj)
    assert rc == 0
    text = next((proj / "work").glob("*deferral-resurface-proposal.md")).read_text(encoding="utf-8")
    assert "Zero deferral-class items found" in text


def test_sweep_writes_nothing_outside_the_proposal_file(tmp_path):
    proj = _fixture_project(tmp_path)
    before = _tree_snapshot(tmp_path)
    _run_sweep(proj)
    after = _tree_snapshot(tmp_path)
    new_files = set(after) - set(before)
    assert len(new_files) == 1
    assert next(iter(new_files)).endswith("deferral-resurface-proposal.md")
    for name in before:
        assert after[name] == before[name], f"pre-existing file changed: {name}"


def test_sweep_skips_prior_proposal_files(tmp_path):
    proj = _fixture_project(tmp_path)
    (proj / "work" / "2026-01-01-deferral-resurface-proposal.md").write_text(
        "old proposal quoting Tier 3 and HOLD and DEFER markers\n", encoding="utf-8",
    )
    _run_sweep(proj)
    latest = max((proj / "work").glob("*deferral-resurface-proposal.md"))
    text = latest.read_text(encoding="utf-8")
    assert "old proposal quoting" not in text


def test_sweep_names_untested_surface_in_header(tmp_path):
    proj = _fixture_project(tmp_path)
    _run_sweep(proj)
    text = next((proj / "work").glob("*deferral-resurface-proposal.md")).read_text(encoding="utf-8")
    assert "Untested surface" in text or "untested surface" in text


# ------------------------------------------------------- dash-glyph exemption
# Glyphs built via chr(codepoint), not literal characters, so this source
# file never carries the glyphs it is testing for.

_DASH_GLYPHS = [
    (chr(0x2012), "figure dash"),
    (chr(0x2013), "en dash"),
    (chr(0x2014), "em dash"),
    (chr(0x2015), "horizontal bar"),
    (chr(0x2212), "minus sign"),
    (chr(0xFF0D), "fullwidth hyphen-minus"),
    (chr(0xFE58), "small em dash"),
]

_FENCED_BLOCK_RE = re.compile(r"^`{3,}.*?^`{3,}\s*$", re.MULTILINE | re.DOTALL)


def _strip_fenced_blocks(text):
    return _FENCED_BLOCK_RE.sub("", text)


def test_quoted_hits_are_wrapped_in_a_fenced_code_block(tmp_path):
    proj = _fixture_project(tmp_path)
    _run_sweep(proj)
    text = next((proj / "work").glob("*deferral-resurface-proposal.md")).read_text(encoding="utf-8")
    assert "```" in text
    assert "Caveman deep-dive" in _FENCED_BLOCK_RE.findall(text)[0]


def test_sweep_proposal_has_no_dash_glyphs_outside_fenced_blocks(tmp_path):
    """Regression for the 2026-08-11 post-review Finding 2 fix: quoted source
    lines may legitimately carry dash glyphs (task_plan.md prose does); once
    fenced, those glyphs must never land in the report's own authored prose."""
    proj = tmp_path / "Projects" / "Dash-Project"
    (proj / "work").mkdir(parents=True)
    em, en, minus = chr(0x2014), chr(0x2013), chr(0x2212)
    (proj / "task_plan.md").write_text(
        "# Plan\n"
        f"- [ ] Tier 3 item with an em dash {em} quoted verbatim, en dash "
        f"{en} too, and a minus sign {minus} for good measure\n",
        encoding="utf-8",
    )
    rc, _ = _run_sweep(proj)
    assert rc == 0
    text = next((proj / "work").glob("*deferral-resurface-proposal.md")).read_text(encoding="utf-8")
    # Sanity: the glyphs really were captured verbatim inside the quote.
    assert em in text and en in text and minus in text
    stripped = _strip_fenced_blocks(text)
    for glyph, name in _DASH_GLYPHS:
        assert glyph not in stripped, f"{name} leaked outside a fenced block"


def _run_hook(raw):
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(raw)), redirect_stderr(captured):
        rc = drs.main([])
    return captured.getvalue(), rc


def test_advisor_warns_on_status_done_flip():
    payload = {"tool_name": "Edit", "tool_input": {
        "file_path": "Projects/your-project/STATE.md",
        "new_string": "status: done\n",
    }}
    err, rc = _run_hook(json.dumps(payload))
    assert rc == 0, "advisor never blocks"
    assert "deferral-resurface" in err


def test_advisor_warns_on_status_archived_flip():
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": "Projects/X/PROJECT.md",
        "content": "---\nstatus: archived\n---\n",
    }}
    err, rc = _run_hook(json.dumps(payload))
    assert rc == 0
    assert "deferral-resurface" in err


def test_advisor_silent_on_ordinary_status(tmp_path):
    payload = {"tool_name": "Edit", "tool_input": {
        "file_path": "Projects/X/STATE.md",
        "new_string": "status: active\n",
    }}
    err, rc = _run_hook(json.dumps(payload))
    assert (err, rc) == ("", 0)


def test_advisor_silent_on_non_project_file():
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": "Resources/KB/page.md",
        "content": "status: done\n",
    }}
    err, rc = _run_hook(json.dumps(payload))
    assert (err, rc) == ("", 0)


def test_advisor_malformed_payload_exits_zero():
    err, rc = _run_hook("{not json")
    assert (err, rc) == ("", 0)
