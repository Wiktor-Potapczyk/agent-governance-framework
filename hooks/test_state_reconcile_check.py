"""Tests for state-reconcile-check.py.

Every case is a real contradiction taken from the three occurrences on 2026-08-06, plus
the negatives that matter more: a hook that flags dated history gets disabled within a
day, and then it protects nothing.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state-reconcile-check.py")

spec = importlib.util.spec_from_file_location("state_reconcile_check", HOOK)
src = importlib.util.module_from_spec(spec)
spec.loader.exec_module(src)


def find(text):
    return src.find_contradictions(text.split("\n"))


# --- RULE A: a task closed above, still open below -------------------------------

def test_task_closed_and_open_is_flagged():
    """Occurrence two, verbatim in shape: 218/219/220 closed at the top of the track
    while a separate entry for the same three sat open twenty lines down."""
    out = find(
        "- [x] **ALL FOUR ENFORCEMENT FIXES SHIPPED** covering tasks 218, 219 and 220.\n"
        "- [ ] **OWNER-GATED enforcement items (tasks 218, 219, 220).** pending a ruling.\n"
    )
    assert len(out) >= 1
    assert any("218" in f for f in out)
    assert any("still described as open" in f for f in out)


def test_all_three_numbers_reported_not_just_the_first():
    out = find(
        "- [x] closed covering tasks 218, 219 and 220\n"
        "- [ ] still open for tasks 218, 219, 220\n"
    )
    joined = " ".join(out)
    assert all(n in joined for n in ("218", "219", "220"))


def test_task_only_closed_is_silent():
    assert find("- [x] **done (task 211)** shipped and verified\n") == []


def test_task_only_open_is_silent():
    assert find("- [ ] **not started (task 211)** nothing yet\n") == []


def test_unrelated_numbers_do_not_collide():
    """A bare number that is not a task reference must not match."""
    assert find(
        "- [x] shipped 219 files across the wave\n"
        "- [ ] **task 400** unrelated work\n"
    ) == []


# --- RULE A, PROSE FORM: STATE.md has no checkboxes ------------------------------
# These are lifted from the real STATE.md on 2026-08-06, where the checkbox-only
# version of this hook was silent while the file plainly contradicted itself.

def test_prose_owner_gated_versus_shipped_is_flagged():
    """Four consecutive lines from the real STATE.md, including the Active Milestone
    line, which is what establishes 218/219/220 as task numbers at all."""
    out = find(
        "## Active Milestone\n"
        "The strongest candidate is the enforcement trio (tasks 219, 218, 220).\n"
        "### Still open\n"
        "- **Owner-gated:** the infrastructure-shape grep (218), the force-push deny "
        "fix (219), the git identity hazard (220).\n"
        "## Next\n"
        "The four enforcement items (219, 218, 220, 211) all shipped and are closed.\n"
    )
    joined = " ".join(out)
    assert all(n in joined for n in ("218", "219", "220"))


def test_reconciling_the_documented_way_silences_the_hook():
    """The fix the hook itself recommends -- mark the old entry SUPERSEDED -- must
    actually silence it, including when the stale heading above is left in place and the
    superseding line still quotes open-sounding words from the text it replaced."""
    assert find(
        "## Active Milestone\n"
        "The enforcement trio (tasks 219, 218, 220) shipped and is closed.\n"
        "### Still open\n"
        "- SUPERSEDED (all three shipped 2026-08-06): the deny fix, held for a fresh "
        "agent, owner-gated at the time. Was tasks 218, 219, 220.\n"
    ) == []


def test_a_bare_number_never_called_a_task_is_ignored():
    """The deliberate tradeoff: a parenthesised number the file never calls a task is
    noise, not a finding. Without this guard the real files reported five bogus tasks
    from list markers like '(1) success metric ...'."""
    assert find(
        "### Still open\n"
        "- **Owner-gated:** the infrastructure-shape grep (218)\n"
        "## Next\n"
        "The enforcement items (218) all shipped.\n"
    ) == []


def test_open_section_heading_scopes_its_bullets():
    """A bullet with no marker of its own is open because of the heading above it."""
    out = find(
        "### Still open\n"
        "- the mechanism behind the held artefacts (211)\n"
        "## Next\n"
        "- [x] task 211 shipped\n"
    )
    assert any("211" in f for f in out)


def test_open_section_ends_at_the_next_same_level_heading():
    """A bullet AFTER the open section closes must not inherit it."""
    assert find(
        "### Still open\n"
        "- nothing here\n"
        "### Shipped\n"
        "- the enforcement work (219)\n"
        "## Next\n"
        "- [x] task 219 shipped\n"
    ) == []


def test_a_year_in_parentheses_is_not_a_task_number():
    assert find(
        "- **Owner-gated:** the audit (2026)\n"
        "- [x] shipped in (2026)\n"
    ) == []


def test_open_wins_the_tie_on_a_mixed_line():
    """'shipped, but still owner-gated' is an open claim, not a closing one."""
    out = find(
        "- The trio shipped but (219) is still owner-gated.\n"
        "- [x] task 219 done\n"
    )
    assert any("219" in f for f in out)


# --- RULE B: two commits both asserted as current --------------------------------

def test_two_current_shas_flagged():
    """Occurrence three: frontmatter still carried the pre-rewrite SHAs while the body
    recorded the new tips."""
    out = find(
        "milestone: 'wave COMPLETE: framework 9c7574d, research 36878f8'\n"
        "## Status\n"
        "Both repos are current at b5b602c.\n"
    )
    assert any("current state" in f for f in out)


def test_a_transition_is_not_a_contradiction():
    """'old to new' on one line is a migration record, not two competing claims."""
    assert not any(
        "current state" in f
        for f in find("## Track: rewritten, framework 9c7574d to b5b602c, verified.\n")
    )


def test_single_current_sha_is_silent():
    assert find("last_action: 'shipped at b5b602c, CI green'\n") == []


# --- RULE C: a stale header beside a shipped claim -------------------------------

def test_stale_header_flagged_when_file_ships_it():
    out = find(
        "## PUBLICATION BUILD: framework SHIPPED, research repo NOT STARTED\n"
        "- [x] research repo SHIPPED, 7 findings published\n"
    )
    assert any("section header" in f for f in out)


def test_stale_header_alone_is_silent():
    """Nothing has shipped, so 'NOT STARTED' is simply true."""
    assert find("## Track: research repo NOT STARTED\n- [ ] do the thing\n") == []


# --- THE LOAD-BEARING NEGATIVES: history must never be flagged -------------------

def test_dated_history_is_never_flagged():
    """A dated completed entry stays true forever. Rewriting it destroys the audit
    trail the file exists for."""
    assert find(
        "## Status\nBoth repos current at b5b602c.\n"
        "- [x] **2026-08-05:** shipped at 9c7574d, CI green on that tip.\n"
        "- [x] **2026-07-29:** earlier wave shipped at 54094bb.\n"
    ) == []


def test_dated_stale_marker_is_not_flagged():
    out = find(
        "- [x] shipped 2026-08-06\n"
        "## 2026-08-05: research repo NOT STARTED at that point\n"
    )
    assert not any("section header" in f for f in out)


def test_clean_file_is_silent():
    assert find(
        "---\nmilestone: 'shipped at b5b602c'\n---\n"
        "## Status\nCurrent and clean.\n"
        "- [x] **task 219** done\n- [ ] **task 300** next\n"
    ) == []


# --- wiring ----------------------------------------------------------------------

def _run(payload):
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True)


def test_only_fires_on_state_files(tmp_path):
    other = tmp_path / "notes.md"
    other.write_text("- [x] task 1 done\n- [ ] task 1 open\n", encoding="utf-8")
    r = _run({"tool_name": "Write", "tool_input": {"file_path": str(other)}})
    assert r.stdout.strip() == ""


def test_fires_on_task_plan(tmp_path):
    f = tmp_path / "task_plan.md"
    f.write_text("- [x] closed (task 42)\n- [ ] open (task 42)\n", encoding="utf-8")
    r = _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    assert "STATE-RECONCILE" in r.stdout
    assert "42" in r.stdout


def test_never_blocks_and_always_exits_zero(tmp_path):
    f = tmp_path / "STATE.md"
    f.write_text("- [x] closed (task 42)\n- [ ] open (task 42)\n", encoding="utf-8")
    r = _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0
    assert "deny" not in r.stdout
    assert json.loads(r.stdout)["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_missing_file_is_survivable(tmp_path):
    r = _run({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "STATE.md")}})
    assert r.returncode == 0


def test_garbage_stdin_is_survivable():
    r = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True)
    assert r.returncode == 0


# --- TELEMETRY (2026-08-07): self-logs to hook-activity.jsonl -------------------
# conftest.py's session-scoped autouse fixture redirects HOOK_ACTIVITY_LOG_PATH to
# a throwaway file for the whole suite run and sets it in os.environ, which the
# subprocess launched by _run() inherits automatically (no explicit env= passed).

def _new_records_since(log_path, before_count):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as fh:
        lines = [l for l in fh if l.strip()]
    return [json.loads(l) for l in lines[before_count:]]


def _record_count(log_path):
    if not os.path.exists(log_path):
        return 0
    with open(log_path, encoding="utf-8") as fh:
        return sum(1 for l in fh if l.strip())


def test_advisory_fire_logs_a_record(tmp_path):
    log_path = os.environ["HOOK_ACTIVITY_LOG_PATH"]
    before = _record_count(log_path)
    f = tmp_path / "STATE.md"
    f.write_text("- [x] closed (task 42)\n- [ ] open (task 42)\n", encoding="utf-8")
    _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    new = _new_records_since(log_path, before)
    assert any(
        r.get("hook") == "state-reconcile-check" and r.get("decision") == "advisory"
        for r in new
    )


def test_silent_fire_logs_a_record(tmp_path):
    log_path = os.environ["HOOK_ACTIVITY_LOG_PATH"]
    before = _record_count(log_path)
    f = tmp_path / "STATE.md"
    f.write_text(
        "---\nmilestone: 'shipped at b5b602c'\n---\n"
        "## Status\nCurrent and clean.\n"
        "- [x] **task 219** done\n- [ ] **task 300** next\n",
        encoding="utf-8",
    )
    _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    new = _new_records_since(log_path, before)
    assert any(
        r.get("hook") == "state-reconcile-check" and r.get("decision") == "silent"
        for r in new
    )


# --- CALIBRATION DEFECT 5 (2026-08-07): regression fixtures ----------------------
# Each pair below is lifted, near-verbatim, from a real live false fire in this
# project's own STATE.md / task_plan.md on 2026-08-07 (em dashes swapped for plain
# punctuation only; every task number, verdict word and marker phrase is unchanged).
# Confirmed against a reconstruction of the pre-fix RULE A logic: all three pairs
# produced a finding under the old whole-line marker search and produce none here.

def test_regression_task_222_range_phrase_survives_a_later_unrelated_marker():
    """STATE.md line 24 vs line 262 (2026-08-07). Both record task 222 done; the old
    code flipped the second line to open because 'owner-gated' and 'blocked' describe
    a DIFFERENT, later clause in the same paragraph (a queued the owner decision), not
    task 222's own status."""
    out = find(
        "**SHIPPED 2026-08-06 late evening: Harness Utilization Analysis** "
        "(task_plan tasks 222 to 227). the owner's ask after the context-engineering "
        "post, executed as six sequential tracks under the framework.\n"
        "**0. Harness Utilization Analysis: CLOSED with QA PASS 2026-08-06 late "
        "evening** (tasks 222 to 227 all done). The delta PM checkpoint caught the "
        "interim state where Active Milestone said SHIPPED before this section knew "
        "about it, both sections now agree. The one new decision it queues for "
        "the owner is owner-gated but not externally blocked.\n"
    )
    assert out == []


def test_regression_task_226_open_items_citation_does_not_reopen_it():
    """task_plan.md line 61 vs line 82 (2026-08-07). Task 226 is DONE at its own
    checkbox; a SEPARATE, still-open item ('1. MUST') cites 'Task 226' only as the
    provenance of a defect it found, not as a claim about task 226's own status."""
    out = find(
        "- [ ] **1. MUST - Feature (a) telemetry-integrity hook-code fixes "
        "(KR1).** Four known bugs: accumulator reset on re-classification; "
        "session-attributed-as-unknown on the two largest sinks; "
        "reviewer-scope-violation-check.py double emission (new defect, found in "
        "Task 226 review, distinct from the 2026-08-04 head-read fix already "
        "shipped as 2e49df3); skill-routing-check.py's detail null blind spot.\n"
        "- [x] Task 226 - Track 5 DONE 2026-08-06. architect-reviewer and "
        "adversarial-reviewer both returned; research-synthesizer merged them into "
        "artifact section 7 (12 owner-gated recommendations, telemetry integrity "
        "first).\n"
    )
    assert out == []


def test_regression_task_232_origin_citation_does_not_reopen_it():
    """task_plan.md line 53 vs line 57 (2026-08-07). Task 232 is DONE at its own
    checkbox; a later prose paragraph names it only as the ORIGIN of the current
    section ('the five queued rulings from Task 232 came back today'), and a
    DIFFERENT, later clause in that same paragraph happens to say 'blocked' about an
    unrelated Write."""
    out = find(
        "- [x] Task 232 - DONE 2026-08-07. Closure QA 7/7 PASS; closing "
        "pm-orchestrator checkpoint ran against the increment frame.\n"
        "Origin: the five queued rulings from Task 232 came back today. Ruling one "
        "surfaced a session-critical fact: the owner believes the config gate is set, "
        "but a live-fire test in this session proved it is not. Ruling four "
        "authorized the MEMORY.md shrink, but the Write itself is blocked this "
        "session by the same config gate, so scope here is DESIGN only.\n"
    )
    assert out == []


def test_folded_prose_clause_counts_as_closed():
    """Candidate rule validated and adopted: 'folded into X' is a closing verdict
    for its own clause, matching task_plan.md's real usage ('task 228 folded into
    the PRD ratification package')."""
    out = find(
        "- [ ] **item still open for a different reason.**\n"
        "Note: task 228 folded into the PRD ratification package, same recommendation.\n"
    )
    assert out == []


# --- CALIBRATION DEFECT 5: armed controls -----------------------------------------
# A fix that silences everything is itself a regression. Each of these is a genuine
# contradiction and MUST still fire after the calibration change above.

def test_armed_control_checkbox_open_versus_checkbox_closed_still_fires():
    """A real contradiction across two checkbox lines, each carrying extra prose in
    a second clause, so the fix's clause-splitting cannot accidentally swallow it."""
    out = find(
        "- [x] Task 501 - DONE 2026-08-07. Everything shipped cleanly; nothing "
        "else to report.\n"
        "- [ ] Task 501 - still needs review; blocked pending owner ruling. "
        "Distinct concern noted elsewhere.\n"
    )
    assert any("501" in f for f in out)
    assert any("still described as open" in f for f in out)


def test_armed_control_prose_still_open_versus_checkbox_closed_still_fires():
    """A prose claim ('task N is still open/blocked') against a checkbox close must
    still fire -- the fix narrows OPEN_MARKER scope to the clause, it does not
    disable the rule."""
    out = find(
        "- [x] Task 502 - DONE 2026-08-07. Shipped and verified.\n"
        "Note: task 502 is still open and blocked pending review from the "
        "reviewer.\n"
    )
    assert any("502" in f for f in out)


def test_armed_control_same_clause_open_marker_still_binds():
    """The open item's own subject is still open with no textual marker of its own
    (the checkbox itself is the marker) -- a still-open subject citing an unrelated
    already-closed task in a later clause must not mask its OWN contradiction."""
    out = find(
        "- [x] Task 601 - DONE 2026-08-06. Already shipped.\n"
        "- [ ] Task 601 - re-opened; the QA re-derivation found a live defect. "
        "Distinct from Task 602, found while reviewing Task 601 output.\n"
    )
    assert any("601" in f for f in out)
