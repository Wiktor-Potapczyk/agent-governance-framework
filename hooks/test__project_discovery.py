"""C1: unit tests for the shared bounded-depth-2 project-discovery helper.

Written BEFORE `_project_discovery.py` exists (declarative-first): the failing
import IS the spec. Every case runs against a synthetic `tmp_path` tree, never
against the live vault, so the suite stays hermetic.

Invariant under test: a directory IS a project iff it DIRECTLY contains
`STATE.md`. Discovery is bounded at depth 2 below `projects_dir` by
construction: a `STATE.md` at depth 3 must NOT be found.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _project_discovery as pd  # noqa: E402


def _mk(root, rel, text="x"):
    """Create a file at root/rel, making parents. Returns the path."""
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# --------------------------------------------------------------------------
# discover_projects: shape and invariant
# --------------------------------------------------------------------------

def test_flat_only_tree(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Beta/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha", "Beta"]


def test_nested_only_tree(tmp_path):
    root = str(tmp_path)
    _mk(root, "Container/Child-A/STATE.md")
    _mk(root, "Container/Child-B/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Container/Child-A", "Container/Child-B"]


def test_mixed_flat_and_nested(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Container/Child/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha", "Container/Child"]


def test_parent_with_state_and_children_both_are_projects(tmp_path):
    """F2: the invariant makes the container AND its children projects."""
    root = str(tmp_path)
    _mk(root, "Umbrella/STATE.md")
    _mk(root, "Umbrella/Module-8B/STATE.md")
    _mk(root, "Umbrella/Production/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Umbrella", "Umbrella/Module-8B", "Umbrella/Production"]


def test_task_plan_without_state_is_not_a_project(tmp_path):
    """A directory with only task_plan.md fails the invariant."""
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "NotAProject/task_plan.md")
    _mk(root, "Container/NotAProject/task_plan.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha"]


def test_depth_three_state_is_not_found(tmp_path):
    """Proves the bound. rglob would find this; bounded depth-2 must not."""
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Alpha/tickets/TICKET-1/STATE.md")
    _mk(root, "Container/Child/Grandchild/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha"]
    assert not any("Grandchild" in i or "TICKET-1" in i for i in ids)


@pytest.mark.parametrize(
    "skipped",
    ["work", "archive", "archives", "source-data", "specs",
     "node_modules", "__pycache__", "backups", "output", "data"],
)
def test_skip_set_children_are_not_projects(tmp_path, skipped):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Alpha/%s/STATE.md" % skipped)
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha"]


def test_dotfile_dirs_are_skipped(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Alpha/.github/STATE.md")
    _mk(root, ".hidden/STATE.md")
    ids = [r[0] for r in pd.discover_projects(root)]
    assert ids == ["Alpha"]


def test_identity_uses_forward_slash_on_every_os(tmp_path):
    root = str(tmp_path)
    _mk(root, "Personal/Finance/STATE.md")
    ident = pd.discover_projects(root)[0][0]
    assert ident == "Personal/Finance"
    assert "\\" not in ident


def test_state_and_plan_paths_are_os_native_and_exist(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    _mk(root, "Alpha/task_plan.md")
    ident, state_path, plan_path = pd.discover_projects(root)[0]
    assert ident == "Alpha"
    assert os.path.isfile(state_path)
    assert os.path.isfile(plan_path)
    assert state_path == os.path.join(root, "Alpha", "STATE.md")
    assert plan_path == os.path.join(root, "Alpha", "task_plan.md")


def test_plan_path_is_none_when_absent(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    assert pd.discover_projects(root)[0][2] is None


def test_ordering_is_deterministic_and_sorted(tmp_path):
    root = str(tmp_path)
    for rel in ["Zulu/STATE.md", "alpha/STATE.md", "Mike/Nested/STATE.md",
                "Mike/STATE.md", "Bravo/STATE.md"]:
        _mk(root, rel)
    first = [r[0] for r in pd.discover_projects(root)]
    second = [r[0] for r in pd.discover_projects(root)]
    assert first == second
    assert first == sorted(first)


def test_missing_projects_dir_returns_empty_not_raise(tmp_path):
    assert pd.discover_projects(os.path.join(str(tmp_path), "nope")) == []


def test_projects_dir_that_is_a_file_returns_empty(tmp_path):
    f = _mk(str(tmp_path), "afile.txt")
    assert pd.discover_projects(f) == []


def test_state_md_that_is_a_directory_is_not_a_project(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "Weird", "STATE.md"))
    _mk(root, "Alpha/STATE.md")
    assert [r[0] for r in pd.discover_projects(root)] == ["Alpha"]


def test_accepts_pathlib_input(tmp_path):
    _mk(str(tmp_path), "Alpha/STATE.md")
    assert [r[0] for r in pd.discover_projects(tmp_path)] == ["Alpha"]


def test_no_unbounded_glob_in_source():
    """Guard against a future edit reintroducing rglob."""
    src = open(pd.__file__, "r", encoding="utf-8").read()
    assert "rglob" not in src
    assert "**" not in src


# --------------------------------------------------------------------------
# detect_active_project: the three-tier resolver
# --------------------------------------------------------------------------

def test_detect_picks_most_recently_modified_state(tmp_path):
    root = str(tmp_path)
    old = _mk(root, "Old/STATE.md")
    new = _mk(root, "Container/New/STATE.md")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    os.utime(new, (1_700_000_000, 1_700_000_000))
    ident, state_path, plan_path = pd.detect_active_project(root)
    assert ident == "Container/New"
    assert state_path == new
    assert plan_path is None


def test_detect_override_wins_and_uses_relative_identity(tmp_path):
    """D3: override file holds the exact relative identity, slash-separated."""
    root = str(tmp_path)
    _mk(root, "Old/STATE.md")
    _mk(root, "Personal/Finance/STATE.md")
    _mk(root, "Personal/Finance/task_plan.md")
    override = _mk(str(tmp_path), "override.txt", "Personal/Finance\n")
    ident, state_path, plan_path = pd.detect_active_project(root, override_file=override)
    assert ident == "Personal/Finance"
    assert state_path.endswith(os.path.join("Personal", "Finance", "STATE.md"))
    assert plan_path is not None


def test_detect_override_pointing_at_nonexistent_falls_through(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    override = _mk(str(tmp_path), "override.txt", "Ghost/Project\n")
    assert pd.detect_active_project(root, override_file=override)[0] == "Alpha"


def test_detect_empty_override_file_falls_through(tmp_path):
    root = str(tmp_path)
    _mk(root, "Alpha/STATE.md")
    override = _mk(str(tmp_path), "override.txt", "   \n")
    assert pd.detect_active_project(root, override_file=override)[0] == "Alpha"


def test_detect_fallback_used_when_no_projects(tmp_path):
    root = os.path.join(str(tmp_path), "Projects")
    os.makedirs(root)
    ident, state_path, plan_path = pd.detect_active_project(root, fallback="your-project")
    assert ident == "your-project"
    assert state_path is None
    assert plan_path is None


def test_detect_fallback_resolves_paths_when_they_exist(tmp_path):
    root = str(tmp_path)
    # fallback target exists on disk but has no STATE.md anywhere discovered
    _mk(root, "Fallback-Proj/STATE.md")
    _mk(root, "Fallback-Proj/task_plan.md")
    # point discovery at an empty dir so tier 2 yields nothing
    empty = os.path.join(str(tmp_path), "Empty")
    os.makedirs(empty)
    ident, state_path, plan_path = pd.detect_active_project(empty, fallback="Fallback-Proj")
    assert ident == "Fallback-Proj"
    assert state_path is None  # fallback resolves against `empty`, not `root`


def test_detect_no_projects_no_fallback_returns_none_triple(tmp_path):
    empty = os.path.join(str(tmp_path), "Empty")
    os.makedirs(empty)
    assert pd.detect_active_project(empty) == (None, None, None)


def test_detect_missing_dir_returns_none_triple(tmp_path):
    assert pd.detect_active_project(os.path.join(str(tmp_path), "nope")) == (None, None, None)
