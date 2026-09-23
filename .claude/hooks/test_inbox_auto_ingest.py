"""Tests for inbox-auto-ingest.py.

Written 2026-09-10; this hook had no suite, and finding out why produced a
defect. Its vault root was a hardcoded absolute path to one machine, so (a) no
test could exercise the trigger branch without appending to the live aggregate,
which is why nobody wrote one, and (b) in any clone or worktree
`resolve().relative_to(VAULT)` raises and the hook silently returns 0, doing
nothing while looking healthy. A VAULT_ROOT override was added, following the
HOOK_ACTIVITY_LOG_PATH / GOVERNANCE_LOG_PATH convention already used here, and
these tests use it.

The hook is the auto-trigger for the wiki ingest pipeline: a Write or Edit
under Inbox/ or Clippings/ emits context telling the next turn to run
process-ingest. The failure worth catching is it going quiet, since dropped
ingests look exactly like an empty inbox.
"""
import json

import pytest
from _hooktest import read_jsonl, run_isolated

HOOK = "inbox-auto-ingest.py"


def run(tmp_path, rel_path, tool="Write", vault=None):
    """Fire the hook against a path inside a temp vault root."""
    vault_root = (vault or (tmp_path / "vault")).resolve()
    (vault_root / "Inbox").mkdir(parents=True, exist_ok=True)
    (vault_root / "Clippings").mkdir(parents=True, exist_ok=True)
    target = vault_root / rel_path if rel_path else vault_root / "x.md"
    payload = {"tool_name": tool, "tool_input": {"file_path": str(target)}}
    proc, hooks_dir = run_isolated(HOOK, payload, tmp_path,
                                   extra_env={"VAULT_ROOT": str(vault_root)})
    assert proc.returncode == 0, proc.stderr
    return proc, vault_root


def context_of(proc):
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("rel", ["Inbox/note.md", "Clippings/article.md"])
def test_a_write_into_an_ingest_directory_triggers(rel, tmp_path):
    proc, _ = run(tmp_path, rel)
    ctx = context_of(proc)
    assert "process-ingest" in ctx
    assert rel in ctx


def test_edit_triggers_as_well_as_write(tmp_path):
    """Editing a clipping changes what the wiki page would summarise, so an
    edit needs re-ingest just as a create does."""
    proc, _ = run(tmp_path, "Inbox/note.md", tool="Edit")
    assert "process-ingest" in context_of(proc)


@pytest.mark.parametrize("tool", ["Read", "Bash", "Grep", "NotebookEdit"])
def test_non_write_tools_are_ignored(tool, tmp_path):
    proc, _ = run(tmp_path, "Inbox/note.md", tool=tool)
    assert context_of(proc) == ""


def test_writes_elsewhere_in_the_vault_do_not_trigger(tmp_path):
    """Over-triggering would demand an ingest for every project file written,
    which would train the reader to ignore the message entirely."""
    proc, _ = run(tmp_path, "Projects/Something/work/note.md")
    assert context_of(proc) == ""


def test_a_path_outside_the_vault_does_not_trigger(tmp_path):
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": str(tmp_path / "elsewhere" / "x.md")}}
    vault_root = (tmp_path / "vault").resolve()
    vault_root.mkdir(parents=True, exist_ok=True)
    proc, _ = run_isolated(HOOK, payload, tmp_path,
                           extra_env={"VAULT_ROOT": str(vault_root)})
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize("name", [".gitkeep", "desktop.ini", "Thumbs.db", ".DS_Store"])
def test_housekeeping_files_are_excluded(name, tmp_path):
    """A .gitkeep landing in Inbox/ is not a document to summarise."""
    proc, _ = run(tmp_path, f"Inbox/{name}")
    assert context_of(proc) == ""


def test_the_trigger_is_logged(tmp_path):
    proc, vault_root = run(tmp_path, "Inbox/note.md")
    entries = read_jsonl(vault_root / ".claude" / "hooks" / "aggregates"
                         / "inbox-ingest-triggers.jsonl")
    assert len(entries) == 1
    assert entries[0]["file"] == "Inbox/note.md"
    assert entries[0]["tool"] == "Write"


def test_the_message_names_the_steps_not_just_the_skill(tmp_path):
    """The context is consumed by the next turn with no other briefing, so a
    bare 'run process-ingest' would leave the SHA and index steps to memory."""
    ctx = context_of(run(tmp_path, "Clippings/article.md")[0])
    assert "SHA" in ctx
    assert "index.md" in ctx


def test_a_payload_with_no_file_path_is_ignored(tmp_path):
    proc, _ = run_isolated(HOOK, {"tool_name": "Write", "tool_input": {}}, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize("raw", ["", "not json", "[]"])
def test_malformed_input_exits_clean(raw, tmp_path):
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_the_vault_root_override_is_what_makes_this_testable(tmp_path):
    """Regression pin for the fix itself. Without VAULT_ROOT the hook resolves
    against its own location, so a temp-copied hook would compute a vault root
    in the temp tree and never match the fixture paths below it."""
    proc, _ = run(tmp_path, "Inbox/note.md")
    assert "process-ingest" in context_of(proc)
