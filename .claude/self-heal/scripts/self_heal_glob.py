"""self_heal_glob.py - one shared glob-match helper for the self-heal loop.

Both `self_heal_target_select.py` (class-straddle checks, this file's own
`classify_candidate`) and, if the accept-script builder chooses to reuse it,
`self_heal_accept.py` (class/forbidden-path checks) need the SAME answer to
"does this path match this targets.json glob entry", so the two scripts'
notion of an allowed class or a forbidden path never silently diverges
(phase (b) plan, TASK-008 risk note; TASK-012 RISK section).

Convention (deliberately distinct from plain `fnmatch`, and from
`pathlib.Path.glob`, since a candidate path here is often just a string,
never touching the filesystem):

  - `**` matches any sequence of characters, INCLUDING `/` (any depth).
  - a single `*` matches any sequence of characters EXCEPT `/` (one path
    segment only).
  - `?` matches exactly one character that is not `/`.
  - every other character is matched literally.

This mirrors the everyday reading of a glob like
`.claude/scripts/*.py` (files directly inside `.claude/scripts/`, not in a
subdirectory) versus `.claude/self-heal/**` (anything at any depth under
that directory), which plain `fnmatch.fnmatch` cannot express: fnmatch
treats every `*` (and every `**`) as "match anything including `/`", so it
cannot tell those two patterns apart.

No filesystem access anywhere in this module. Pure string/regex functions
only, importable from a pure-function context (REQ-003/REQ-004 in the phase
(b) plan).

EXCLUDES CONVENTION (phase (b) fix pass, adversarial/architect review,
"scripts" class's own `"excludes": ["*_logic.py"]` finding). A class's
`paths` entries are always matched against the WHOLE candidate path (the
convention above). A class's `excludes` entries follow a DIFFERENT rule: a
pattern with no `/` in it matches the candidate's BASENAME only (so
`*_logic.py` excludes `.claude/scripts/generic_logic.py` by matching
`generic_logic.py`, regardless of directory depth); a pattern that DOES
contain a `/` is matched against the whole path, same as `paths`. This
mirrors the everyday reading of an exclude list (a bare-filename pattern
means "any file with this name/shape, wherever it lives") and is
implemented by `path_matches_exclude`/`path_matches_exclude_any` below.
"""
from __future__ import annotations

import re

__all__ = [
    "glob_to_regex", "path_matches", "path_matches_any",
    "path_matches_exclude", "path_matches_exclude_any",
]


def glob_to_regex(pattern: str) -> re.Pattern:
    """Compiles one glob pattern (using this module's own `**`/`*`/`?`
    convention, described in the module docstring) into an anchored regex.

    The pattern is always matched against a POSIX-style, forward-slash path
    (the caller normalizes backslashes before calling `path_matches`)."""
    i, n = 0, len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path: str, pattern: str) -> bool:
    """True if `path` (forward-slash or backslash, either is accepted and
    normalized here) matches `pattern` under this module's glob convention."""
    normalized = path.replace("\\", "/")
    return glob_to_regex(pattern).match(normalized) is not None


def path_matches_any(path: str, patterns: list) -> bool:
    """True if `path` matches at least one entry in `patterns`."""
    return any(path_matches(path, p) for p in patterns)


def path_matches_exclude(path: str, pattern: str) -> bool:
    """True if `path` matches `pattern` under the EXCLUDES convention (see
    module docstring): a pattern with no `/` matches the path's basename
    only; a pattern containing `/` matches the whole path, same as
    `path_matches`."""
    if "/" in pattern:
        return path_matches(path, pattern)
    normalized = path.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    return glob_to_regex(pattern).match(basename) is not None


def path_matches_exclude_any(path: str, patterns: list) -> bool:
    """True if `path` matches at least one entry in `patterns` under the
    excludes (basename-for-slash-less-patterns) convention."""
    return any(path_matches_exclude(path, p) for p in patterns)
