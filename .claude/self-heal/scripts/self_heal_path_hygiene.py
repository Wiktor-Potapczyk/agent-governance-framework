"""self_heal_path_hygiene.py: the loop's one path hygiene check.

Three scripts used to carry their own copy of this check, and the copies
had drifted. The staging guard knew nothing about whitespace, control
characters, absolute paths or '.' segments. The accept step let an
absolute path, a '.' segment and an empty segment through. The apply
step's ASCII rule covered ".claude/" but not look-alike siblings such as
".claude-x/". One rule set now serves all three:

  self_heal_apply.py    validates the improver's change set
  self_heal_stage.py    re-checks the staged paths before the commit
  self_heal_accept.py   checks every path of a pull request

The rules come in two tiers, because the steps fail differently. A
violation in apply or stage ends the round with no branch and no pull
request, and a red run. A violation in accept opens the pull request for
the owner with a note. So:

  hard_reasons     rules with no honest exception: absolute or empty
                   path, NFKC-unstable path, backslash, '..', '.' and
                   empty segments, whitespace at a segment edge, control
                   characters, and anything but printable ASCII under
                   .claude. All three steps apply these.
  review_reasons   the mixed character script heuristic. It catches a
                   homoglyph, and it also fires on an honest name such as
                   "latency_" + Greek mu + "s.md". Under .claude the
                   ASCII rule already refuses both. Elsewhere only the
                   accept step applies it, so that a person decides.

`hygiene_reasons` is both tiers together, in that order.

Each function takes the path exactly as the caller holds it. A caller
that wants to refuse a path whose NFKC form differs passes the raw path
(apply, stage). A caller that normalises first and reports against the
raw path passes the normalised form (accept); the NFKC rule is then
satisfied by construction and every other rule still applies.

Python 3.14, standard library only.
"""
from __future__ import annotations

import unicodedata

BACKSLASH = chr(92)

# ".claude" without the slash on purpose: it also covers the directory
# itself and look-alike siblings such as ".claude-x/", which have no
# business carrying non-ASCII names either.
ASCII_ONLY_PREFIX = ".claude"


def is_control_char(ch: str) -> bool:
    return unicodedata.category(ch).startswith("C")


def char_script_bucket(ch: str) -> str | None:
    """A crude per-character script bucket (LATIN, CYRILLIC, GREEK, ...)
    read off the first word of the Unicode character name. Enough to catch
    one Cyrillic letter dropped into a Latin file name. It is not a full
    script-property table, which the standard library does not carry."""
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    return name.split(" ", 1)[0]


def segment_has_mixed_scripts(segment: str) -> bool:
    buckets = {b for b in (char_script_bucket(ch) for ch in segment) if b}
    return len(buckets) > 1


def hard_reasons(path: str) -> list[str]:
    """Every hard violation of `path`, in a fixed order; empty means none.
    Paths are repo-relative with forward slashes."""
    reasons: list[str] = []
    if not path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        reasons.append("absolute or empty path")
    if unicodedata.normalize("NFKC", path) != path:
        reasons.append("NFKC normalisation changes the path")
    if BACKSLASH in path:
        reasons.append("contains a backslash")
    segments = path.split("/")
    if ".." in segments:
        reasons.append("contains a '..' segment")
    if "." in segments:
        reasons.append("contains a '.' segment")
    if "" in segments[:-1]:
        reasons.append("contains an empty segment")
    for seg in segments:
        if seg != seg.strip():
            reasons.append(f"segment {seg!r} has leading or trailing whitespace")
        if any(is_control_char(ch) for ch in seg):
            reasons.append(f"segment {seg!r} contains a control character")
    if path.startswith(ASCII_ONLY_PREFIX) and not (path.isascii() and path.isprintable()):
        reasons.append("path under .claude is not printable ASCII")
    return reasons


def review_reasons(path: str) -> list[str]:
    """Violations that a person should judge rather than a script."""
    return [f"segment {seg!r} mixes character scripts"
            for seg in path.split("/") if segment_has_mixed_scripts(seg)]


def hygiene_reasons(path: str) -> list[str]:
    """Both tiers: what the accept step reports on a pull request."""
    return hard_reasons(path) + review_reasons(path)
