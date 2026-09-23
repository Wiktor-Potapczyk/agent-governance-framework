#!/usr/bin/env python3
"""session-work-orientation.py: SessionStart work/-directory cleanliness nudge.

Part of the close-out metabolism feature (PRD 7.2 feature h, 2026-08-07): "one
SessionStart orientation line reporting work/ file count, files untouched over
30 days, and exhaust of closed tracks." This is that line's build. NOT
registered anywhere yet; registration is a separate, config-gated batch; this
file being on disk and unregistered is intentional and expected.

Active project resolution:
  1. `cwd` from the SessionStart payload, if it names a path inside a real
     `Projects/<name>/` directory: direct match, no scan needed.
  2. Otherwise, scan `Projects/*/` (one level, one `os.scandir` pass): among
     the candidates that have a `work/` subdirectory, pick the one whose
     `STATE.md` has the most recent mtime (falling back to the directory's
     own mtime when it has no `STATE.md`). This is the same "most recently
     touched project wins" heuristic other orientation hooks use, applied
     locally rather than via the shared depth-2 `_project_discovery` helper,
     since this hook only ever needs a top-level `Projects/<name>` match.
  If neither resolves a project with an existing `work/` directory, the hook
  exits silently: no stdout at all, per the fail-open contract below.

Work-directory counting (single `os.scandir` pass over `work/`, non-recursive
so nested folders like `work/backups/` are naturally excluded):
  N = count of top-level `.md` files
  M = of those, how many have not been modified in over 30 days
  K = how many of those N basenames are recorded closed in `task_plan.md`

Closed-track heuristic for K: a cheap, honest approximation, not a citation
system. A basename counts as "from a closed track" when it appears as a
substring within 300 characters after a markdown header line that contains
the literal string "CLOSED" (matches the vault's own track-header convention,
e.g. "## Track: Foo (2026-08-07): CLOSED RATIFIED"), AND that "CLOSED" is not
itself negated by an immediately preceding "NOT" / "NOT YET" (any spacing or
hyphenation, case insensitive) -- a header like "NOT YET CLOSED, still
active" is the vault's own recognized open-marker phrasing (see the sibling
state-reconcile hook's OPEN_MARKER) and must not count as closed. If
`task_plan.md` is missing or unreadable, K is reported as "n/a" rather than
0: a 0 would read as "no closed-track exhaust", which is not the same claim
as "could not check".

Fail-open: every exception anywhere in this hook exits 0 silently. Runtime
target is well under 200ms for a 100-file work/ dir: one `os.scandir` pass
over `work/`, one `os.scandir` pass over `Projects/`, and at most one read of
`task_plan.md`.

Output contract: stdout JSON per Anthropic SessionStart hook spec
(hookSpecificOutput), emitted only when a project resolves. Exit code: always 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PROJECTS_DIR = os.path.join(VAULT, "Projects")

WORK_DIR_NAME = "work"
STATE_FILE_NAME = "STATE.md"
TASK_PLAN_NAME = "task_plan.md"

STALE_SECONDS = 30 * 24 * 60 * 60  # 30 days
CLOSED_WINDOW_CHARS = 300
CLOSED_HEADER_RE = re.compile(r"^#{1,6}[ \t].*CLOSED.*$", re.MULTILINE)
# Python re lookbehinds are fixed-width, so negation is a post-match guard
# rather than a single regex: find every "CLOSED" word and every negated
# "NOT [YET] CLOSED" span, then a header only counts when some "CLOSED"
# occurrence falls outside all negated spans.
_CLOSED_WORD_RE = re.compile(r"\bCLOSED\b", re.IGNORECASE)
_NEGATED_CLOSED_RE = re.compile(r"\bNOT[\s\-]+(?:YET[\s\-]+)?CLOSED\b", re.IGNORECASE)

_SESSION: str | None = None  # set from the payload in main(); None when absent


def _log_fire(decision: str, detail: str | None = None) -> None:
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("session-work-orientation", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


def _project_name_from_cwd(cwd: str | None) -> str | None:
    """If `cwd` is inside `PROJECTS_DIR/<name>/...`, return `<name>`. Else None.

    Top-level only (`Projects/<name>`, not a nested identity): this hook's
    scope per spec is `Projects/*/`, one level. Case-insensitive compare,
    since Windows path casing is not meaningful here.
    """
    if not cwd:
        return None
    try:
        cwd_np = os.path.normpath(cwd)
        proj_np = os.path.normpath(PROJECTS_DIR)
        cwd_norm = os.path.normcase(cwd_np)
        proj_norm = os.path.normcase(proj_np)
    except Exception:
        return None
    if cwd_norm == proj_norm:
        return None  # cwd IS Projects/ itself, not inside a specific project
    prefix = proj_norm + os.sep
    if not cwd_norm.startswith(prefix):
        return None
    # Slice the normalized cwd (dot segments collapsed) by the normalized
    # prefix's length, not the raw cwd/PROJECTS_DIR strings: normpath can
    # change string length (e.g. a `.` segment), and normcase never changes
    # length on Windows (lowercasing, backslash-for-forward-slash), so
    # cwd_norm/proj_norm and cwd_np/proj_np stay length-aligned. cwd_np is
    # used (not cwd_norm) so the returned project name keeps its real case.
    remainder = cwd_np[len(proj_np):].lstrip("\\/")
    if not remainder:
        return None
    name = re.split(r"[\\/]", remainder, maxsplit=1)[0]
    return name or None


def _scan_for_active_project() -> str | None:
    """Single `os.scandir` pass over `Projects/*/`.

    Returns the directory name of the candidate (must have a `work/`
    subdirectory) whose `STATE.md` has the most recent mtime, falling back to
    the directory's own mtime when it has no `STATE.md`. None if nothing
    qualifies or `Projects/` itself is unreadable.
    """
    best_name = None
    best_mtime = None
    try:
        with os.scandir(PROJECTS_DIR) as it:
            for entry in it:
                try:
                    if not entry.is_dir():
                        continue
                    if entry.name.startswith("."):
                        continue
                    work_path = os.path.join(entry.path, WORK_DIR_NAME)
                    if not os.path.isdir(work_path):
                        continue
                    state_path = os.path.join(entry.path, STATE_FILE_NAME)
                    try:
                        if os.path.isfile(state_path):
                            mtime = os.path.getmtime(state_path)
                        else:
                            mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if best_mtime is None or mtime > best_mtime:
                        best_mtime = mtime
                        best_name = entry.name
                except OSError:
                    continue
    except (OSError, ValueError):
        return None
    return best_name


def resolve_project(payload: dict) -> str | None:
    """Resolve the active project name, or None. See module docstring."""
    cwd = None
    if isinstance(payload, dict):
        c = payload.get("cwd")
        if isinstance(c, str) and c.strip():
            cwd = c.strip()

    name = _project_name_from_cwd(cwd)
    if name and os.path.isdir(os.path.join(PROJECTS_DIR, name, WORK_DIR_NAME)):
        return name

    return _scan_for_active_project()


def scan_work_dir(work_dir: str):
    """Single `os.scandir` pass over `work_dir` (non-recursive).

    Returns (n, m, basenames):
      n         = count of top-level `.md` files
      m         = of those, how many have mtime older than STALE_SECONDS
      basenames = file stems (name without `.md`) for the closed-track check
    """
    now = time.time()
    cutoff = now - STALE_SECONDS
    n = 0
    m = 0
    basenames: list[str] = []
    try:
        with os.scandir(work_dir) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                    name = entry.name
                    if not name.lower().endswith(".md"):
                        continue
                    n += 1
                    basenames.append(name[:-3])
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if mtime < cutoff:
                        m += 1
                except OSError:
                    continue
    except (OSError, ValueError):
        return 0, 0, []
    return n, m, basenames


def _header_has_unnegated_closed(header_text: str) -> bool:
    """True when `header_text` contains a "CLOSED" that is not negated.

    A "CLOSED" counts unless it falls inside a "NOT CLOSED" / "NOT YET
    CLOSED" / "NOT-YET-CLOSED" span (arbitrary whitespace or hyphens between
    the words, case insensitive).
    """
    negated_spans = [m.span() for m in _NEGATED_CLOSED_RE.finditer(header_text)]
    for m in _CLOSED_WORD_RE.finditer(header_text):
        start, end = m.span()
        if any(neg_start <= start and end <= neg_end for neg_start, neg_end in negated_spans):
            continue
        return True
    return False


def count_closed_track_files(task_plan_path: str, basenames: list[str]):
    """K per the module docstring's closed-track heuristic.

    Returns an int, or the string "n/a" when `task_plan.md` is missing or
    unreadable (an honest "could not check", never conflated with 0).
    """
    if not task_plan_path or not os.path.isfile(task_plan_path):
        return "n/a"
    try:
        with open(task_plan_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return "n/a"

    if not basenames:
        return 0

    windows = []
    for m in CLOSED_HEADER_RE.finditer(text):
        if not _header_has_unnegated_closed(m.group(0)):
            continue
        windows.append(text[m.end():m.end() + CLOSED_WINDOW_CHARS])
    if not windows:
        return 0

    combined = "\n".join(windows)
    return sum(1 for stem in basenames if stem and stem in combined)


def main() -> int:
    global _SESSION
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    payload: dict = {}
    try:
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(raw)
    except Exception:
        _SESSION = None

    try:
        project = resolve_project(payload)
        if not project:
            _log_fire("skip", "no-project-resolved")
            return 0

        work_dir = os.path.join(PROJECTS_DIR, project, WORK_DIR_NAME)
        if not os.path.isdir(work_dir):
            _log_fire("skip", "no-work-dir")
            return 0

        n, m, basenames = scan_work_dir(work_dir)
        task_plan_path = os.path.join(PROJECTS_DIR, project, TASK_PLAN_NAME)
        k = count_closed_track_files(task_plan_path, basenames)

        context = (
            "[WORK-DIR ORIENTATION] %s: %d work files, %d untouched over 30 days, "
            "%s from closed tracks" % (project, n, m, k)
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
        _log_fire("emit", "project=%s n=%d m=%d k=%s" % (project, n, m, k))
        return 0
    except Exception:
        # Fail-open per contract: exit silently, no stdout at all.
        _log_fire("error")
        return 0


if __name__ == "__main__":
    sys.exit(main())
