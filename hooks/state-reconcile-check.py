#!/usr/bin/env python
"""state-reconcile-check.py: PostToolUse(Write|Edit) advisory on self-contradicting state files.

WHY THIS EXISTS
---------------
The recurring defect: a new, accurate status block is written at the top of STATE.md or
task_plan.md, and the older entries below it are left describing the previous state. The
file then says two things, and which one a reader believes depends on where they stop
reading. A PM checkpoint reading only the top reports the work done; one reading further
down reports it pending. Both are reading the same file on the same day.

Measured 2026-08-06: pm-orchestrator caught this THREE separate times in one day, in the
same two files. A memo describing it already existed on disk before occurrences two and
three and changed nothing, which is the ~25% soft-instruction compliance figure this
vault's own working philosophy names. Hence a hook.

WHAT IT DOES NOT DO
-------------------
It never blocks. The save is what preserves the work, so refusing one would be worse than
the defect it prevents. It emits line numbers so reconciliation is one edit rather than a
search.

It also never flags dated history. "On 2026-08-06 we shipped 9c7574d" inside a completed
`- [x]` entry stays true forever, and rewriting those destroys the audit trail the file
exists for. Only CURRENT-STATE claims and SECTION HEADERS go stale, because only those
are read as present tense. This exemption is load-bearing: a hook that flags history gets
disabled within a day, and then it protects nothing.

Override: STATE_RECONCILE_CHECK_DISABLED=1

TELEMETRY (2026-08-07): self-logs to hook-activity.jsonl via the shared
_governance_logger helper (same convention as git-credential-scope-check.py /
skill-routing-check.py). One record per evaluated file: decision="advisory" when
find_contradictions() returned findings, decision="silent" when it did not. Logging
is fail-open by construction (_log_fire never raises) and never alters the matching
logic above.
"""
from __future__ import annotations

import json
import os
import re
import sys

DISABLED = os.environ.get("STATE_RECONCILE_CHECK_DISABLED") == "1"

TARGET = re.compile(r"(?:^|[/\\])(STATE\.md|task_plan\.md)$", re.IGNORECASE)

# A closed entry: "- [x] ..." possibly indented.
CLOSED = re.compile(r"^\s*[-*]\s*\[[xX]\]")
OPEN = re.compile(r"^\s*[-*]\s*\[ \]")
HEADER = re.compile(r"^#{1,6}\s")

# "task 219", "tasks 218, 219 and 220", "(task 211)"
TASK_REF = re.compile(r"\btasks?\s+((?:\d{1,4})(?:\s*(?:,|and|/|\+)\s*\d{1,4})*)", re.IGNORECASE)

# STATE.md does not use checkboxes. It states the same facts in prose, so the checkbox
# rules below were blind to it -- measured 2026-08-06 against the real file. These
# recover the prose forms: "(219)", "(219, 218, 220, 211)". They are LOOSE and are only
# consulted on a line that already declares itself closed or open, because the finding
# still requires the SAME number to appear on both sides.
LOOSE_REF = re.compile(r"\(\s*(\d{1,4}(?:\s*,\s*\d{1,4})*)\s*\)")

CLOSE_MARKER = re.compile(
    r"\b(SHIPPED|COMPLETE|COMPLETED|CLOSED|DONE|LANDED|SUPERSEDED|FOLDED)\b", re.IGNORECASE
)
# A line that OPENS with its verdict: "SUPERSEDED (shipped 2026-08-06): <old text>".
# The verdict governs; the prose after it describes the state being superseded and will
# usually still contain open-sounding words. Without this, reconciling a stale section
# in the documented way ("mark it SUPERSEDED") leaves the hook firing on the fix.
LEADING_CLOSE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*|__)?\s*"
    r"(SUPERSEDED|CLOSED|DONE|SHIPPED|COMPLETED?|LANDED|RESOLVED)\b",
    re.IGNORECASE,
)
OPEN_MARKER = re.compile(
    r"\b(NOT STARTED|IN FLIGHT|AWAITING|PENDING|UNBUILT|NOT YET|OWNER[- ]GATED|"
    r"HELD|STILL OPEN|OUTSTANDING|UNRESOLVED|BLOCKED|HAS NOT BEEN|HAVE NOT BEEN)\b",
    re.IGNORECASE,
)
# A heading that declares everything under it to be open work.
OPEN_SECTION = re.compile(
    r"^(#{1,6})\s.*\b(still open|open items?|remaining|outstanding|not done|to ?do)\b",
    re.IGNORECASE,
)
# A heading whose body is a RECORD of what happened. A "NEXT: ..." inside one of these
# quotes a plan from that date; it is not a live claim, and rewriting it would destroy
# the audit trail. Measured 2026-08-06: without this, two dated 2026-07-09 bullets under
# "## Built This Epoch" produced two false findings.
HISTORY_SECTION = re.compile(
    r"^(#{1,6})\s.*\b(built|recent decisions?|history|log|epoch|changelog|shipped)\b",
    re.IGNORECASE,
)

_SESSION: str | None = None  # set from the payload in main(); None when absent


def _log_fire(decision: str, detail: str | None = None) -> None:
    """Record this firing to hook-activity.jsonl. Never raises (fail-open).

    A logging failure must never affect this hook's advisory output -- the whole
    body is one try/except, matching the git-credential-scope-check.py /
    skill-routing-check.py convention.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("state-reconcile-check", decision=decision, detail=detail,
                  session=_SESSION)
    except Exception:
        pass


SHA = re.compile(r"\b[0-9a-f]{7,40}\b")

# Lines that assert the PRESENT state rather than recording history.
CURRENT_CUE = re.compile(
    r"(?:^\s*(?:milestone|last_action|status)\s*:)"
    r"|(?:\b(?:are|is)\s+current\b)"
    r"|(?:\btip\s+is\b)"
    r"|(?:\bcurrently\s+at\b)"
    r"|(?:\bnow\s+(?:at|reads)\b)",
    re.IGNORECASE,
)

# Staleness markers that should not survive next to a shipped claim.
STALE_MARKER = re.compile(
    r"\b(NOT STARTED|IN FLIGHT|AWAITING|PENDING|UNBUILT|NOT YET)\b", re.IGNORECASE
)
SHIPPED_MARKER = re.compile(
    r"\b(SHIPPED|COMPLETE|COMPLETED|CLOSED|DONE|LANDED)\b", re.IGNORECASE
)

# A dated historical entry: carries a YYYY-MM-DD and lives in a closed item.
DATED = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _is_history(line: str) -> bool:
    """History is exempt: a closed item, or any line carrying an explicit date."""
    return bool(CLOSED.match(line)) or bool(DATED.search(line))


def _task_numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in TASK_REF.finditer(text):
        out.update(re.findall(r"\d{1,4}", m.group(1)))
    return out


def _task_numbers_loose(text: str, known: set[str]) -> set[str]:
    """Prose task references, e.g. "the deny fix (219)".

    A bare parenthesised number is admitted ONLY if the file elsewhere calls that exact
    number a task. Measured against the real files 2026-08-06: without that guard this
    reads enumerations like "(1) success metric ..." as tasks 1 through 5 and reports
    eight findings of which five are noise.
    """
    out = _task_numbers(text)
    for m in LOOSE_REF.finditer(text):
        for n in re.findall(r"\d{1,4}", m.group(1)):
            if int(n) < 10 or 1900 <= int(n) <= 2100:
                continue                     # list markers and years are not tasks
            if n in known:
                out.add(n)
    return out


CLAUSE_BOUNDARY = re.compile(r"(?<=[.;])\s+")


def _clause_split(line: str) -> list[str]:
    """Split one file line into clause-sized chunks for the textual-marker checks.

    Deliberately coarse (period-or-semicolon then whitespace): a false split after a
    numbered-list prefix like "1." only costs locality within the SAME sentence, since
    the marker word and the task number it modifies still land in the piece that
    follows. What it buys back is the thing that matters -- an OPEN_MARKER word in one
    clause of a long paragraph no longer binds to a task number cited in an EARLIER or
    LATER, unrelated clause of that same physical line.
    """
    return CLAUSE_BOUNDARY.split(line)


def _section_flags(lines: list[str]) -> tuple[list[bool], list[bool]]:
    """Per line: (under an open-work heading, under a history heading).

    An open-work heading nested inside a history heading wins: "### Still open" under
    "## Built This Epoch" is a live list, not a record.
    """
    open_flags = [False] * len(lines)
    hist_flags = [False] * len(lines)
    open_depth = 0
    hist_depth = 0
    for i, line in enumerate(lines):
        if HEADER.match(line):
            level = len(line) - len(line.lstrip("#"))
            if open_depth and level <= open_depth:
                open_depth = 0
            if hist_depth and level <= hist_depth:
                hist_depth = 0
            if OPEN_SECTION.match(line):
                open_depth = level
            elif HISTORY_SECTION.match(line):
                hist_depth = level
            continue
        open_flags[i] = bool(open_depth)
        hist_flags[i] = bool(hist_depth) and not open_depth
    return open_flags, hist_flags


def find_contradictions(lines: list[str]) -> list[str]:
    """Return human-readable findings. Conservative by construction."""
    findings: list[str] = []

    # RULE A: a task number claimed closed AND still described as open elsewhere.
    # Both sides accept the checkbox form (task_plan.md) and the prose form (STATE.md).
    #
    # Calibration defect 5 (2026-08-07, measured live 4+ times): a full LINE in these
    # files is often one long paragraph carrying several unrelated clauses ("CLOSED
    # with QA PASS ... tasks 222 to 227 all done. ... it is owner-gated but not
    # externally blocked."). The old code ran OPEN_MARKER / CLOSE_MARKER as a whole-
    # line word search, so a marker describing a DIFFERENT clause 300 characters away
    # flipped the verdict for a task number it never modifies. A structural verdict
    # (a checkbox, a line that LEADS with a verdict word, or an open-work heading)
    # still governs its whole line/bullet -- that is the correct scope for those,
    # since the bullet's own textual body is genuinely one entry. A bare textual
    # marker with no structural anchor is scoped to its own CLAUSE instead.
    in_open_section, in_history_section = _section_flags(lines)
    known: set[str] = set()
    for line in lines:
        known |= _task_numbers(line)
    closed_tasks: dict[str, int] = {}
    open_tasks: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        if in_history_section[i - 1]:
            continue
        leads_with_verdict = bool(LEADING_CLOSE.match(line))
        line_closed_checkbox = bool(CLOSED.match(line))
        line_open_checkbox = bool(OPEN.match(line))
        line_open_section = in_open_section[i - 1] and not line_closed_checkbox

        if leads_with_verdict or line_closed_checkbox:
            # Structural close: a checkbox-done line, or a line that leads with a
            # verdict word ("SHIPPED ..."), wins outright over any OPEN_MARKER text
            # quoted anywhere in its own body -- a closed entry citing an unrelated
            # decision as "owner-gated" does not reopen the task the entry closes.
            for n in _task_numbers_loose(line, known):
                closed_tasks.setdefault(n, i)
            continue
        # No (or only a partial) structural verdict left: an open checkbox / open-
        # section bullet's OWN subject is open by construction (the marker is the
        # checkbox itself, not a word to search for), but its body can still cite an
        # unrelated, already-resolved task in passing ("found in Task 226 review,
        # ... already shipped as `2e49df3`") -- unlike a closed entry (Rule above),
        # an open item's citations do not get to inherit its open status wholesale.
        # So only the FIRST clause (the one carrying the checkbox / the heading-
        # scoped bullet marker itself) is forced open; every later clause is scored
        # like ordinary prose, on its own textual marker, same as a line with no
        # structural verdict at all. Open still wins a tie WITHIN one clause:
        # "shipped, but 219 is still owner-gated" is an open claim for 219.
        clauses = _clause_split(line)
        if line_open_checkbox or line_open_section:
            for n in _task_numbers_loose(clauses[0], known):
                open_tasks.setdefault(n, i)
            clauses = clauses[1:]

        for clause in clauses:
            clause_open = bool(OPEN_MARKER.search(clause))
            clause_closed = not clause_open and bool(CLOSE_MARKER.search(clause))
            if not (clause_open or clause_closed):
                continue
            for n in _task_numbers_loose(clause, known):
                if clause_open:
                    open_tasks.setdefault(n, i)
                else:
                    closed_tasks.setdefault(n, i)
    for n in sorted(set(closed_tasks) & set(open_tasks), key=int):
        findings.append(
            f"task {n}: recorded as done on line {closed_tasks[n]} but still described "
            f"as open on line {open_tasks[n]}"
        )

    # RULE B: two different SHAs both asserted as the CURRENT state.
    current_shas: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        if _is_history(line):
            continue
        if not (CURRENT_CUE.search(line) or HEADER.match(line)):
            continue
        # "9c7574d to b5b602c" is a transition, not a contradiction: take the last.
        found = SHA.findall(line)
        if not found:
            continue
        for s in found[:-1] if len(found) > 1 else found:
            current_shas.setdefault(s[:7], i)
    if len(current_shas) > 1:
        where = ", ".join(f"{s} (line {ln})" for s, ln in sorted(current_shas.items(), key=lambda kv: kv[1]))
        findings.append(
            f"{len(current_shas)} different commits are each presented as the current "
            f"state: {where}"
        )

    # RULE C: a staleness marker in a header, when the same file elsewhere ships it.
    ships = any(
        SHIPPED_MARKER.search(l) and not STALE_MARKER.search(l)
        for l in lines
        if CLOSED.match(l) or CURRENT_CUE.search(l)
    )
    if ships:
        for i, line in enumerate(lines, 1):
            if _is_history(line):
                continue
            if HEADER.match(line) and STALE_MARKER.search(line):
                marker = STALE_MARKER.search(line).group(1)
                findings.append(
                    f"line {i}: a section header still says '{marker}' while the file "
                    f"records the work as shipped elsewhere"
                )

    return findings


def main() -> int:
    global _SESSION
    if DISABLED:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(payload)
    except Exception:
        _SESSION = None

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path or not TARGET.search(path):
        return 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except Exception:
        return 0

    findings = find_contradictions(lines)
    _log_fire("advisory" if findings else "silent")
    if not findings:
        return 0

    body = "\n".join(f"  - {f}" for f in findings[:8])
    more = f"\n  ...and {len(findings) - 8} more" if len(findings) > 8 else ""
    msg = (
        f"[STATE-RECONCILE - ADVISORY] {os.path.basename(path)} now contradicts itself:\n"
        f"{body}{more}\n"
        "A new summary at the top does not reconcile the entries below it. Close or mark "
        "the old ones SUPERSEDED. Grep for the IDENTIFIERS (ticket numbers, SHAs), not "
        "for the phrasing you remember writing. Dated '- [x]' history is correct as-is "
        "and must not be rewritten.\n"
        "Memo: feedback_prepending_a_summary_does_not_reconcile_the_file"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)          # fail-open: never break a state save
