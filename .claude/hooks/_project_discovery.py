"""
_project_discovery.py - the single shared project-discovery helper.

Before this module, seven call sites across four hooks and one script each
carried their own flat `os.listdir(Projects)` scan, with three mutually
divergent override/fallback behaviours between them. All seven now import from
here, so the vault has exactly one definition of "what is a project".

THE INVARIANT
    A directory IS a project if and only if it DIRECTLY contains `STATE.md`.

    No marker file, no registry, no naming convention. `STATE.md` is already the
    thing every project has and nothing else has, so it is the identity. A
    directory holding only `task_plan.md` is not a project.

IDENTITY IS THE FULL RELATIVE PATH, NEVER THE BARE LEAF
    A project is named by its path relative to `projects_dir`, with forward
    slashes on every OS: `Personal/Finance`, not `Finance`. Leaf names are not
    unique (`Module-8B`, `Production`, `Company-Research` are all plausible
    twice) and a silent wrong match inside a SessionStart hook is expensive to
    notice. Callers that need to rebuild a path from an identity should split on
    "/" and `os.path.join` the parts.

THE SCAN IS BOUNDED AT DEPTH 2, BY CONSTRUCTION
    Children of `projects_dir` are tested, then the immediate children of those.
    Nothing deeper. This is a deliberate ceiling, not an optimisation: on
    2026-08-06 the vault held 11 `STATE.md` files at depth 3, all of them inside
    `tickets/` and `archive/` subtrees that are sub-artifacts of a project rather
    than projects in their own right. An unbounded walk would sweep them into
    every orientation hook and every recovery snapshot. The bound is expressed
    as two explicit loops rather than a glob so that it cannot drift.

THE SKIP SET IS A JUDGMENT CALL, AND ONLY ABOUT COST
    `_SKIP_DIRS` and the leading-dot rule exist to avoid a pointless stat storm
    inside vendored trees. `Projects/Personal/Career/node_modules` alone holds several
    hundred directories, none of which will ever hold a `STATE.md`. The skip set
    cannot hide a real project, because a real project directory is never named
    `work`, `archive` or `node_modules`. If that ever stops being true, delete
    the entry rather than working around it.

Stdlib only. Every filesystem call is guarded individually: this module is
imported by SessionStart and UserPromptSubmit hooks, where one unreadable
directory must never take down the session.
"""

import os

__all__ = ["discover_projects", "detect_active_project", "STATE_FILE", "PLAN_FILE"]

STATE_FILE = "STATE.md"
PLAN_FILE = "task_plan.md"

# Directory names never descended into and never treated as project candidates
# below depth 1. Cost control only. See the module docstring.
_SKIP_DIRS = frozenset({
    "work", "archive", "archives", "source-data", "specs",
    "node_modules", "__pycache__", "backups", "output", "data",
})


def _subdirs(path):
    """Immediate subdirectory names of `path`, sorted. Never raises."""
    try:
        with os.scandir(path) as it:
            names = []
            for entry in it:
                try:
                    if entry.is_dir():
                        names.append(entry.name)
                except OSError:
                    continue
        return sorted(names)
    except (OSError, ValueError):
        return []


def _is_file(path):
    try:
        return os.path.isfile(path)
    except (OSError, ValueError):
        return False


def _project_row(projects_dir, parts):
    """Return (identity, state_path, plan_path_or_None) if parts is a project."""
    state_path = os.path.join(projects_dir, *parts, STATE_FILE)
    if not _is_file(state_path):
        return None
    plan_path = os.path.join(projects_dir, *parts, PLAN_FILE)
    return ("/".join(parts), state_path, plan_path if _is_file(plan_path) else None)


def discover_projects(projects_dir):
    """Every project under `projects_dir`, bounded at depth 2.

    Returns a list of `(relative_identity, state_path, plan_path)` tuples sorted
    by identity. `relative_identity` always uses forward slashes; `state_path`
    and `plan_path` are OS-native absolute-or-relative paths built from whatever
    `projects_dir` was passed in. `plan_path` is None when the project has no
    `task_plan.md`.

    A missing, unreadable or non-directory `projects_dir` returns [].
    """
    projects_dir = os.fspath(projects_dir)
    rows = []

    for child in _subdirs(projects_dir):
        if child.startswith("."):
            continue

        row = _project_row(projects_dir, (child,))
        if row is not None:
            rows.append(row)

        if child in _SKIP_DIRS:
            continue

        child_path = os.path.join(projects_dir, child)
        for grandchild in _subdirs(child_path):
            if grandchild.startswith(".") or grandchild in _SKIP_DIRS:
                continue
            row = _project_row(projects_dir, (child, grandchild))
            if row is not None:
                rows.append(row)

    rows.sort(key=lambda r: r[0])
    return rows


def _read_override(override_file):
    """The relative identity written in the override file, or ''. Never raises."""
    if not override_file or not _is_file(override_file):
        return ""
    try:
        with open(override_file, "r", encoding="utf-8") as f:
            raw = f.read(4096)
    except (OSError, UnicodeDecodeError):
        return ""
    return raw.strip().replace("\\", "/").strip("/")


def _resolve(projects_dir, identity):
    """(identity, state_or_None, plan_or_None) for an identity that may not exist."""
    parts = [p for p in identity.split("/") if p]
    state_path = os.path.join(projects_dir, *parts, STATE_FILE)
    plan_path = os.path.join(projects_dir, *parts, PLAN_FILE)
    return (identity,
            state_path if _is_file(state_path) else None,
            plan_path if _is_file(plan_path) else None)


def detect_active_project(projects_dir, override_file=None, fallback=None):
    """Resolve the active project in three tiers.

    1. `override_file` - a single line holding the exact relative identity, e.g.
       `Personal/Finance`. Honoured only if that project's `STATE.md` exists;
       a stale or empty override falls through silently rather than failing.
    2. The most-recently-modified `STATE.md` among all discovered projects.
    3. `fallback` - a relative identity used verbatim when nothing was
       discovered. Its paths are returned only if they exist on disk.

    Returns `(identity, state_path, plan_path)`; any element may be None. This
    exists so call sites 1, 2 and 5 stop carrying three divergent copies of the
    same algorithm.
    """
    projects_dir = os.fspath(projects_dir)

    identity = _read_override(override_file)
    if identity:
        resolved = _resolve(projects_dir, identity)
        if resolved[1] is not None:
            return resolved

    best = None
    best_mtime = None
    for row in discover_projects(projects_dir):
        try:
            mtime = os.path.getmtime(row[1])
        except OSError:
            continue
        if best_mtime is None or mtime > best_mtime:
            best_mtime = mtime
            best = row
    if best is not None:
        return best

    if fallback:
        return _resolve(projects_dir, fallback)

    return (None, None, None)
