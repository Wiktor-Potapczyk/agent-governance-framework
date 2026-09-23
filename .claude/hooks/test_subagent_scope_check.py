"""Tests for subagent-scope-check.py.

Written 2026-09-10; this guard had no suite despite carrying the vault's only
record of what a dispatched subagent actually touched. It snapshots
`git status --porcelain` at SubagentStart and diffs at SubagentStop.

The property that matters most is the 2026-08-24 no-baseline rule, and it is
worth stating why. The hook used to fall back to an empty baseline when no
SubagentStart record existed, which made `current - baseline` the ENTIRE dirty
working tree and recorded it as the subagent's writes. Measured at the time:
5,249 of 9,641 records had no baseline and averaged 407 "new" files each,
against 0.8 for records that had one. Those records held 161.2 MB of the log's
162.8 MB and produced 18,967 of 18,981 apparent ownership violations, none of
them real. A regression here would not look like a bug; it would look like a
subagent misbehaving, which is far worse than silence.

These tests drive a real git repository through the SUBAGENT_SCOPE_ROOT seam
the hook already provides, so nothing touches the live vault.
"""
import json
import subprocess

import pytest
from _hooktest import read_jsonl, run_isolated


HOOK = "subagent-scope-check.py"


@pytest.fixture
def repo(tmp_path):
    """A real git repo with one committed file, so the tree starts clean."""
    root = tmp_path / "repo"
    root.mkdir()
    run = lambda *a: subprocess.run(list(a), cwd=str(root), capture_output=True,
                                    text=True, timeout=30)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    # Mirror production: the hook writes its own baseline state file INSIDE the
    # repo it is measuring, and the vault gitignores that path. Without this
    # line the hook's own bookkeeping shows up as an untracked file and is
    # attributed to the subagent, which cost five failing tests before the
    # fixture was made realistic. See the dedicated test at the end of this
    # file for why that is not merely a fixture detail.
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    (root / "committed.txt").write_text("base\n", encoding="utf-8")
    run("git", "add", "committed.txt", ".gitignore")
    run("git", "commit", "-q", "-m", "base")
    return root


def fire(tmp_path, repo, event, agent_id="agent-1", agent_type="prompt-engineer"):
    payload = {"hook_event_name": event, "agent_id": agent_id,
               "agent_type": agent_type}
    proc, _ = run_isolated(HOOK, payload, tmp_path,
                           extra_env={"SUBAGENT_SCOPE_ROOT": str(repo)})
    assert proc.returncode == 0, f"hook must never block: {proc.stderr}"
    return proc


def log_entries(repo):
    return read_jsonl(repo / ".claude" / "hooks" / "subagent-scope-log.jsonl")


# --- the measurement ----------------------------------------------------------

def test_start_records_a_baseline(tmp_path, repo):
    fire(tmp_path, repo, "SubagentStart")
    state = json.loads((repo / ".claude" / "hooks" / "_state"
                        / "subagent-scope-baselines.json").read_text(encoding="utf-8"))
    assert "agent-1" in state
    assert state["agent-1"]["agent_type"] == "prompt-engineer"


def test_a_file_created_between_start_and_stop_is_attributed(tmp_path, repo):
    fire(tmp_path, repo, "SubagentStart")
    (repo / "written-by-agent.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStop")
    entry = log_entries(repo)[-1]
    assert entry["had_baseline"] is True
    assert entry["new_changes_total"] == 1
    assert any("written-by-agent.md" in c for c in entry["new_changes"])


def test_a_file_dirty_before_start_is_not_attributed(tmp_path, repo):
    """The point of a baseline. Pre-existing mess belongs to the tree, not to
    the agent that happened to run next."""
    (repo / "already-dirty.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStart")
    fire(tmp_path, repo, "SubagentStop")
    entry = log_entries(repo)[-1]
    assert entry["new_changes_total"] == 0


def test_a_file_returned_to_clean_is_recorded_as_resolved(tmp_path, repo):
    (repo / "temp.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStart")
    (repo / "temp.md").unlink()
    fire(tmp_path, repo, "SubagentStop")
    entry = log_entries(repo)[-1]
    assert entry["resolved_changes_total"] == 1


def test_new_changes_warn_on_stderr(tmp_path, repo):
    """The main session only sees stderr, so a silent log entry would mean
    nobody notices during the dispatch that produced it."""
    fire(tmp_path, repo, "SubagentStart")
    (repo / "new.md").write_text("x", encoding="utf-8")
    proc = fire(tmp_path, repo, "SubagentStop")
    assert "[SCOPE-CHECK]" in proc.stderr
    assert "prompt-engineer" in proc.stderr


def test_a_clean_stop_does_not_warn(tmp_path, repo):
    fire(tmp_path, repo, "SubagentStart")
    proc = fire(tmp_path, repo, "SubagentStop")
    assert "[SCOPE-CHECK]" not in proc.stderr


# --- the 2026-08-24 no-baseline rule -----------------------------------------

def test_a_stop_without_a_baseline_records_nothing_as_new(tmp_path, repo):
    """Load-bearing. Without a baseline there is NO measurement, and the old
    empty-set fallback wrote the whole dirty tree out as the agent's writes."""
    for name in ("a.md", "b.md", "c.md"):
        (repo / name).write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStop", agent_id="never-started")
    entry = log_entries(repo)[-1]
    assert entry["had_baseline"] is False
    assert entry["new_changes"] == []
    assert entry["new_changes_total"] == 0
    assert "no_baseline_note" in entry


def test_the_no_baseline_note_explains_itself(tmp_path, repo):
    """Anyone reading the log later needs to know the zero means unmeasured,
    not clean."""
    fire(tmp_path, repo, "SubagentStop", agent_id="never-started")
    note = log_entries(repo)[-1]["no_baseline_note"].lower()
    assert "no delta" in note or "no sub" in note
    assert "repository" in note


def test_a_baseline_is_consumed_so_a_second_stop_is_unmeasured(tmp_path, repo):
    """Baselines are popped at stop. A replayed stop must not re-attribute."""
    fire(tmp_path, repo, "SubagentStart")
    (repo / "new.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStop")
    fire(tmp_path, repo, "SubagentStop")
    assert log_entries(repo)[-1]["had_baseline"] is False


# --- growth control -----------------------------------------------------------

def test_paths_are_capped_but_the_total_is_kept(tmp_path, repo):
    """The count is what anyone reads; the paths are for recognising shape.
    Keeping every path is how this log reached 162 MB."""
    fire(tmp_path, repo, "SubagentStart")
    for i in range(30):
        (repo / f"f{i:02d}.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStop")
    entry = log_entries(repo)[-1]
    assert entry["new_changes_total"] == 30
    assert len(entry["new_changes"]) == 20
    assert entry["new_changes_truncated"] is True


# --- degradation --------------------------------------------------------------

def test_an_unknown_event_is_a_silent_no_op(tmp_path, repo):
    proc = fire(tmp_path, repo, "SomethingElse")
    assert proc.stderr.strip() == ""
    assert log_entries(repo) == []


def test_agents_are_tracked_independently(tmp_path, repo):
    fire(tmp_path, repo, "SubagentStart", agent_id="a1")
    fire(tmp_path, repo, "SubagentStart", agent_id="a2")
    (repo / "from-a1.md").write_text("x", encoding="utf-8")
    fire(tmp_path, repo, "SubagentStop", agent_id="a1")
    entry = log_entries(repo)[-1]
    assert entry["agent_id"] == "a1"
    assert entry["new_changes_total"] == 1


@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_malformed_input_exits_clean(raw, tmp_path):
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_a_visible_state_file_would_be_attributed_to_the_subagent(tmp_path, repo):
    """Not a fixture detail: a live interaction worth knowing about.

    This hook measures the working tree, so ANY file written between start and
    stop is attributed to the subagent, including files written by other hooks.
    Its own baseline state file sits under .claude/hooks/_state/ and is only
    invisible because that path is gitignored.

    On 2026-09-10 the vault's blanket `_state/` ignore was narrowed so the
    trust-contract ledger and the cadence stamps are tracked. Those are not
    written during a normal dispatch, so no attribution noise is expected, but
    the coupling is now real: un-ignoring a file that some hook writes mid
    dispatch would make it show up as the subagent's work. This test documents
    the mechanism by reproducing it deliberately.
    """
    (repo / ".gitignore").write_text("# nothing ignored\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=str(repo),
                   capture_output=True, timeout=30)
    subprocess.run(["git", "commit", "-q", "-m", "unignore"], cwd=str(repo),
                   capture_output=True, timeout=30)
    fire(tmp_path, repo, "SubagentStart")
    fire(tmp_path, repo, "SubagentStop")
    entry = log_entries(repo)[-1]
    # The agent touched nothing, yet hook bookkeeping is now visible to git.
    assert entry["new_changes_total"] >= 1


def test_a_non_repository_root_does_not_crash(tmp_path):
    """git status fails outside a repo; the hook must degrade, not explode."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    proc, _ = run_isolated(HOOK, {"hook_event_name": "SubagentStart",
                                  "agent_id": "a1"}, tmp_path,
                           extra_env={"SUBAGENT_SCOPE_ROOT": str(plain)})
    assert proc.returncode == 0, proc.stderr
