"""Tests for session-start-orientation.py.

Written 2026-09-10; this guard had no suite. It is the first thing a session
reads: which project is active, its status and last action, the open task-plan
items, and the recent decisions. Everything downstream inherits whatever it
says, so a wrong answer here is not a missing feature, it is a session that
confidently orients on the wrong project.

Its worst failure is silent by construction. Every path is wrapped so session
start never breaks, which means a broken extractor degrades to an empty
orientation and looks like a quiet session rather than a fault. These tests
assert on CONTENT, not merely on a clean exit.

Fixtures build a whole temp vault, so nothing reads the real Projects/ tree.
"""
import json

import pytest
from _hooktest import isolate, run_isolated


HOOK = "session-start-orientation.py"

STATE = """---
status: active
last_action: 'Closed the harness design and verified three findings'
---
# Demo

## Recent Decisions
- 2026-09-01 chose option A because it is reversible
- 2026-09-02 dropped the second sweep
- 2026-09-03 ruled the estimate untouched
- 2026-09-04 this one is beyond the cap
"""

PLAN = """# Plan
- [x] done item
- [ ] first open item
- [ ] second open item
"""


def make_vault(tmp_path, projects, override=None):
    """projects: {relative_identity: (state_text_or_None, plan_text_or_None)}"""
    hook = isolate(HOOK, tmp_path)
    vault = hook.parent.parent.parent          # vault/.claude/hooks -> vault
    for name, (state, plan) in projects.items():
        d = vault / "Projects" / name
        d.mkdir(parents=True, exist_ok=True)
        if state is not None:
            (d / "STATE.md").write_text(state, encoding="utf-8")
        if plan is not None:
            (d / "task_plan.md").write_text(plan, encoding="utf-8")
    if override is not None:
        (vault / ".claude" / "active-project.txt").write_text(override,
                                                              encoding="utf-8")
    return vault


def orient(tmp_path):
    proc, _ = run_isolated(HOOK, {"session_id": "s-1"}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "hook emitted nothing"
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return out["hookSpecificOutput"]["additionalContext"]


# --- what it reports ----------------------------------------------------------

def test_it_names_the_active_project(tmp_path):
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    assert "Active project: Demo" in orient(tmp_path)


def test_status_and_last_action_come_from_frontmatter(tmp_path):
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    text = orient(tmp_path)
    assert "Status: active" in text
    assert "Closed the harness design" in text


def test_open_items_are_listed_and_completed_ones_are_not(tmp_path):
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    text = orient(tmp_path)
    assert "first open item" in text
    assert "second open item" in text
    assert "done item" not in text


def test_recent_decisions_are_capped_at_three(tmp_path):
    """The cap is the difference between orientation and a wall of history."""
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    text = orient(tmp_path)
    assert "chose option A" in text
    assert "beyond the cap" not in text


def test_open_items_are_capped_at_ten(tmp_path):
    plan = "# Plan\n" + "\n".join(f"- [ ] item number {i}" for i in range(15))
    make_vault(tmp_path, {"Demo": (STATE, plan)})
    text = orient(tmp_path)
    assert "item number 0" in text
    assert "item number 14" not in text


def test_a_very_long_item_is_truncated(tmp_path):
    plan = "# Plan\n- [ ] " + ("x" * 400)
    make_vault(tmp_path, {"Demo": (STATE, plan)})
    assert "..." in orient(tmp_path)


def test_no_open_tasks_says_so_rather_than_going_quiet(tmp_path):
    """Silence reads as 'nothing loaded'; the explicit line reads as 'nothing
    open'. Those mean very different things at session start."""
    make_vault(tmp_path, {"Demo": (STATE, "# Plan\n- [x] all done\n")})
    assert "No open tasks found" in orient(tmp_path)


# --- which project it picks ---------------------------------------------------

def test_the_override_file_wins(tmp_path):
    make_vault(tmp_path, {"Alpha": (STATE, PLAN), "Beta": (STATE, PLAN)},
               override="Beta")
    assert "Active project: Beta" in orient(tmp_path)


def test_without_an_override_the_most_recent_state_wins(tmp_path):
    import os
    import time
    vault = make_vault(tmp_path, {"Older": (STATE, PLAN), "Newer": (STATE, PLAN)})
    old = vault / "Projects" / "Older" / "STATE.md"
    past = time.time() - 86400
    os.utime(old, (past, past))
    assert "Active project: Newer" in orient(tmp_path)


def test_a_nested_project_is_discoverable(tmp_path):
    """Projects nest one level (Personal/Finance). A single-star scan would
    make every nested project invisible to orientation."""
    make_vault(tmp_path, {"Group/Nested": (STATE, PLAN)}, override="Group/Nested")
    assert "Nested" in orient(tmp_path)


# --- the instructions it carries ---------------------------------------------

def test_it_points_at_the_recall_stack_before_grep(tmp_path):
    """This block exists because the default reflex is raw Grep over the
    memory folder, which is the wrong first move."""
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    text = orient(tmp_path)
    assert "mcp__qmd__query" in text
    assert "Grep" in text


def test_it_says_the_summary_is_not_the_canonical_state(tmp_path):
    """Without this line the summary gets treated as the source of truth, which
    is exactly the compaction failure the vault's doctrine warns about."""
    text = orient(tmp_path)
    assert "orientation only" in text
    assert "canonical" in text


# --- it must never break session start ---------------------------------------

def test_a_project_with_no_state_file_still_emits(tmp_path):
    make_vault(tmp_path, {"Demo": (None, PLAN)}, override="Demo")
    text = orient(tmp_path)
    assert "Active project:" in text


def test_no_projects_directory_at_all_still_emits_valid_json(tmp_path):
    isolate(HOOK, tmp_path)
    proc, _ = run_isolated(HOOK, {"session_id": "s"}, tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"


@pytest.mark.parametrize("raw", ["", "not json at all", "[]"])
def test_malformed_payloads_never_break_session_start(raw, tmp_path):
    make_vault(tmp_path, {"Demo": (STATE, PLAN)})
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"] \
        == "SessionStart"


def test_a_corrupt_state_file_degrades_without_crashing(tmp_path):
    make_vault(tmp_path, {"Demo": ("\x00\x01 not markdown at all", PLAN)},
               override="Demo")
    text = orient(tmp_path)
    assert "Active project: Demo" in text
