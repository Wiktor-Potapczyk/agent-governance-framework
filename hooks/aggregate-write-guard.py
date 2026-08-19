#!/usr/bin/env python3
"""
aggregate-write-guard.py: PreToolUse guard (matcher: Write|Edit|MultiEdit)
protecting the memory-layer aggregates from a wholesale-loss write.

Ticket: task_plan.md, "cross-session singleton write guard" (2026-08-07 23:20),
consolidated v2 direction ruled 2026-08-08 ("i accept, build the revised guard").
Design v1 (superseded on two points, see below): Projects/Agent-Governance-
Research/work/2026-08-08-singleton-write-guard-design.md.

Protected surface (exact path match, not any file with a matching basename):
  1. MEMORY.md            the head index at MEMORY_PATH below.
  2. governance-log.jsonl  append-only aggregate log at GOVERNANCE_LOG_PATH.
  3. hook-activity.jsonl   append-only aggregate log at HOOK_ACTIVITY_LOG_PATH.
The two jsonl paths are DERIVED, not guessed: they use the exact same
os.path.join(dirname(__file__), "<name>.jsonl") computation that
_event_emit.py and _governance_logger.py themselves use to find their own
live log files (this hook lives in the same .claude/hooks/ directory).

If memory/INDEX-TAIL.md is ever created as the two-tier index's second file,
it joins this scope (architect-review note from the design's build ticket).
It does not exist today and this hook does not create it or protect it yet.

Deviations from the v1 design doc (recorded here, not in the doc, per the
build instruction not to touch it):
  - v1 keyed detection on TOOL IDENTITY (Edit is structurally incapable of a
    wholesale replace, so only Write was checked). Both reviews of the v1
    design established this premise is false: an Edit whose old_string spans
    the entire current file IS a wholesale replace. This hook computes the
    EFFECTIVE POST-WRITE CONTENT for Write, Edit, and MultiEdit alike and
    evaluates that, never the tool name.
  - v1 gated on an AND of byte-shrink-ratio and citation-COUNT-delta
    thresholds. The adversarial review showed both parts are gameable (a
    count-preserving swap passes; the threshold denies the doctrine's own
    sanctioned periodic re-split). This hook replaces both thresholds with a
    SIBLING-COVERAGE check: a dropped citation only denies when its target
    file still exists on disk AND no other file in the memory folder cites
    it (via the same markdown-link syntax this file already parses, not a
    bare substring test: see the Finding 2 note below). This makes "write
    the detail into a topic file, then shrink the head" the enforced safe
    order, and it has no magnitude threshold to game or to false-deny
    against.
  - v1 scoped MEMORY.md only. This hook generalizes to the two jsonl
    aggregates as well (the "brief's premise that the jsonl logs are guarded
    did not survive grep" finding from the same review pass).
  - v1 was deny-only. This hook logs BOTH allow and deny verdicts on a
    protected path via _governance_logger.log_fire, since deny-only logging
    starves the governance miner of allow-side data (adversarial review).

Post-review fixes (architect review on the first build, 2026-08-08; the wave
QA that ran alongside it passed 6/6 on this file's own CHECK cases, so these
are review-only findings, not QA failures):
  - FINDING 1 (BLOCKER): the aggregate-log rule used to branch on tool name,
    with the Edit branch doing a line-multiset comparison instead of the
    Write branch's order-preserving prefix check. That let an Edit reorder
    existing lines and splice a forged record in between them while an
    identical Write, producing the exact same resulting bytes, would have
    been denied. Fixed by deleting the branch: aggregate_log_is_append_shaped
    applies ONE rule, the prefix check, to the effective content regardless
    of which tool produced it. jsonl_edit_loses_lines and the Counter import
    it needed are removed (dead code this same fix orphaned).
  - FINDING 2 (MAJOR): _has_sibling_coverage used to test a bare substring
    (`filename in text`), so a sibling that only mentioned
    'governance-log.md' counted as covering a dropped 'log.md' citation. It
    now extracts the sibling's own citations with CITATION_RE and tests set
    membership, the same structured parse this file already uses for every
    other citation question it asks.
  - FINDING 3 (MAJOR): the registered matcher was 'Write|Edit', missing
    'MultiEdit' (sibling hooks on this same event, e.g.
    reviewer-scope-violation-check.py, register all three). Matcher widened
    to 'Write|Edit|MultiEdit' in settings.local.json, AND effective_content
    gained a real MultiEdit branch (tool_input["edits"], applied in order via
    the same single-edit logic Edit uses) so the widened matcher is not
    cosmetic: without it, a MultiEdit against a protected path fell through
    to the "cannot compute effective content" branch and silently allowed.
  - FINDING 4 (MINOR): _read_current already failed toward allow (bootstrap)
    on an OSError; _has_sibling_coverage's own listdir call used to fail
    toward deny (returned False, meaning "not covered", pushing the verdict
    toward denying a citation drop this hook could not actually evaluate).
    Realigned to the file's one stated direction: a listdir failure now
    returns True (treated as covered, exempting that citation) and logs the
    anomaly via the shared logger with decision="anomaly" so it is visible
    in hook-activity.jsonl without being mistaken for a real allow/deny
    verdict. Tradeoff, stated plainly: on the same call where listdir fails,
    a genuinely uncovered citation could pass through undetected. This
    hook's Design already accepts a comparable residual for TOCTOU; a
    listdir failure is logged, not silently absorbed, but it is not
    escalated into a deny either, since GUD-002's fail-open direction
    applies to I/O errors exactly as much as it does to parse errors. A
    per-sibling-file read failure (as opposed to the listdir call itself)
    is unchanged: that one file is skipped and the scan continues, since a
    single unreadable sibling is a much narrower failure than the whole
    folder being unlistable.

TOCTOU (accepted, documented, not mitigated): this hook reads the target
file's current on-disk bytes at PreToolUse time and reasons against them; a
concurrent session's own write can land between that read and the tool call
this hook is evaluating. Per feedback_multi_session_concurrency_is_the_norm
("any design that assumes exclusive access to shared state is invalid by
construction"), this hook makes no such assumption, but it also cannot
close the race with a lock file without violating the same doctrine (a lock
held by one session over shared state IS an exclusivity assumption). The
residual is accepted: a race can still let two "safe" writes land back to
back and jointly lose a citation that neither write dropped on its own. Nothing
here silently swallows that risk; it is named, not solved.

Mechanism: hookSpecificOutput.permissionDecision = "deny" plus
permissionDecisionReason, matching qmd-rerank-default-guard.py's _emit_deny
shape (the only enforcement lever this hook suite has ever confirmed: no
tool_input-mutation mechanism exists).

Exit codes: 0 always. Any unexpected exception fails toward allow, never
toward a crash or a false deny (a broken guard must not block ordinary work).
"""

from __future__ import annotations

import json
import os
import re
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_MEMORY_PATH = (
    r"C:\Users\exampleuser\.claude\projects\C--Users-exampleuser-Desktop-Vault"
    r"\memory\MEMORY.md"
)
_DEFAULT_GOVERNANCE_LOG_PATH = os.path.join(_HOOKS_DIR, "governance-log.jsonl")
_DEFAULT_HOOK_ACTIVITY_LOG_PATH = os.path.join(_HOOKS_DIR, "hook-activity.jsonl")

# Injectable for tests (and, if the memory folder ever moves, for ops): an
# env var override wins, otherwise the derived/default path is used. Tests in
# this suite monkeypatch these module attributes directly after import,
# which every function below reads at call time, not at import time.
MEMORY_PATH = (
    os.environ.get("AGGREGATE_WRITE_GUARD_MEMORY_PATH", "").strip()
    or _DEFAULT_MEMORY_PATH
)
GOVERNANCE_LOG_PATH = (
    os.environ.get("AGGREGATE_WRITE_GUARD_GOVLOG_PATH", "").strip()
    or _DEFAULT_GOVERNANCE_LOG_PATH
)
HOOK_ACTIVITY_LOG_PATH = (
    os.environ.get("AGGREGATE_WRITE_GUARD_HOOKLOG_PATH", "").strip()
    or _DEFAULT_HOOK_ACTIVITY_LOG_PATH
)

# Same capture group the 2026-08-07 compaction audit used to extract
# citation targets from MEMORY.md: markdown link syntax only, [text](file.md).
CITATION_RE = re.compile(r"\]\(([A-Za-z0-9_\-]+\.md)\)")

MAX_LISTED_CITATIONS = 10


def _norm(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def classify_target(file_path: str):
    """Return 'memory_index', 'aggregate_log', or None (not protected).

    Exact normalized-path match only, per the v2 scope decision: a file
    that merely happens to be named MEMORY.md somewhere else in the
    filesystem is not in scope (superseding v1's basename-only heuristic).
    """
    if not file_path:
        return None
    norm = _norm(file_path)
    if norm == _norm(MEMORY_PATH):
        return "memory_index"
    if norm in (_norm(GOVERNANCE_LOG_PATH), _norm(HOOK_ACTIVITY_LOG_PATH)):
        return "aggregate_log"
    return None


def _read_current(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _apply_single_edit(content: str, edit: dict):
    """Apply one {old_string, new_string, replace_all?} edit to `content`.

    Returns the resulting string, or None when the edit cannot be applied
    (old_string absent or not found: the real Edit/MultiEdit tool will fail
    on that mismatch itself, so this hook does not double-guard it).
    """
    if not isinstance(edit, dict):
        return None
    old_string = edit.get("old_string", "")
    new_string = edit.get("new_string", "")
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return None
    if old_string == "" or old_string not in content:
        return None
    replace_all = bool(edit.get("replace_all", False))
    if replace_all:
        return content.replace(old_string, new_string)
    return content.replace(old_string, new_string, 1)


def effective_content(tool_name: str, tool_input: dict, current_content: str):
    """The proposed post-write content, or None when it cannot be computed
    (an Edit/MultiEdit step whose old_string is not present in the content
    at that point: the real tool will fail on that mismatch on its own, so
    this hook does not double-guard it and allows).
    """
    if tool_name == "Write":
        content = tool_input.get("content", "")
        return content if isinstance(content, str) else ""

    if tool_name == "Edit":
        return _apply_single_edit(current_content, tool_input)

    if tool_name == "MultiEdit":
        # tool_input shape: {file_path, edits: [{old_string, new_string,
        # replace_all?}, ...]}, no top-level content (confirmed against
        # routing-table-validation.py's identical MultiEdit handling and
        # test_transition_gate_check.py's fixture, the established
        # convention in this hook suite). Edits apply sequentially, each
        # against the previous edit's result, matching the real tool's own
        # semantics; any edit that cannot be applied aborts the whole
        # computation to None (allow, not a partial/best-effort verdict).
        edits = tool_input.get("edits")
        if not isinstance(edits, list) or not edits:
            return None
        content = current_content
        for edit in edits:
            content = _apply_single_edit(content, edit)
            if content is None:
                return None
        return content

    return None


def _citations(text: str) -> set:
    return set(CITATION_RE.findall(text))


def _memory_dir() -> str:
    return os.path.dirname(MEMORY_PATH)


def _target_file_exists(filename: str) -> bool:
    return os.path.isfile(os.path.join(_memory_dir(), filename))


def _log_anomaly(detail: str) -> None:
    """Records an internal I/O anomaly (not a Write/Edit verdict) via the
    same shared logger, decision="anomaly" so it is distinguishable in
    hook-activity.jsonl from a real allow/deny row. No payload/session is
    available at the call sites that use this (they run inside a coverage
    scan, not the top-level main() dispatch). Never raises.
    """
    try:
        sys.path.insert(0, _HOOKS_DIR)
        from _governance_logger import log_fire
        log_fire("aggregate-write-guard", decision="anomaly", detail=detail)
    except Exception:
        pass


def _has_sibling_coverage(filename: str) -> bool:
    """True when some OTHER .md file in the memory folder (not MEMORY.md,
    not the dropped file itself) CITES the dropped filename via the same
    markdown-link syntax CITATION_RE parses everywhere else in this file.
    Set-membership against the sibling's own parsed citations, not a bare
    substring test: a substring test would let a sibling that only mentions
    'governance-log.md' count as coverage for a dropped 'log.md' (post-
    review Finding 2). This is what makes "write the topic file first, then
    shrink the head" the enforced safe order: a real citation has to already
    exist somewhere else before the head is allowed to stop citing it.

    Fails toward allow on a listdir I/O error (post-review Finding 4,
    aligning with _read_current's own fail-open direction): treated as
    covered, logged as an anomaly, not escalated into a deny. Tradeoff
    stated plainly: on the exact call where listdir fails, a genuinely
    uncovered citation could pass through undetected. A failure to open one
    individual sibling file (as opposed to the listdir call itself) is
    narrower and is simply skipped; the scan continues over the rest.
    """
    mem_dir = _memory_dir()
    try:
        entries = os.listdir(mem_dir)
    except OSError:
        _log_anomaly(f"listdir failed for {mem_dir}")
        return True
    target_lower = filename.lower()
    for entry in entries:
        low = entry.lower()
        if not low.endswith(".md"):
            continue
        if low == "memory.md" or low == target_lower:
            continue
        try:
            with open(os.path.join(mem_dir, entry), "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if filename in _citations(text):
            return True
    return False


def uncovered_dropped_citations(current_content: str, effective: str) -> list:
    """Citations present now and absent from the effective content, EXCEPT
    when the target file is already gone (deleting a dead memory plus its
    index line stays legal) or another sibling already covers it (the
    sanctioned periodic re-split, and the 2026-08-08 restoration's own
    banked topic files, stay legal). Sorted for a deterministic deny message.
    """
    dropped = _citations(current_content) - _citations(effective)
    uncovered = []
    for filename in sorted(dropped):
        if not _target_file_exists(filename):
            continue
        if _has_sibling_coverage(filename):
            continue
        uncovered.append(filename)
    return uncovered


def aggregate_log_is_append_shaped(current_content: str, effective: str) -> bool:
    """True when `effective` is `current_content` followed by new material
    only, order preserved: an exact-prefix, tail-only-growth check.

    Post-review Finding 1 (BLOCKER): this used to be Write-only, with a
    separate Edit rule (a line-multiset comparison) that allowed an Edit to
    reorder existing lines and splice a forged record in between them,
    while an identical Write producing the exact same resulting bytes was
    denied. There is now ONE rule, applied to the effective content
    regardless of which tool produced it: append-only means tail-only
    growth with order preserved, full stop.
    """
    return effective.startswith(current_content)


def _emit_deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _emit_deny_memory(file_path: str, uncovered: list) -> None:
    basename = os.path.basename(file_path)
    shown = uncovered[:MAX_LISTED_CITATIONS]
    remainder = len(uncovered) - len(shown)
    listing = ", ".join(shown)
    if remainder > 0:
        listing += f", and {remainder} more"
    reason = (
        f"AGGREGATE WRITE GUARD: blocked write to '{basename}'. It would drop "
        f"{len(uncovered)} citation(s) with no coverage anywhere else in the memory "
        f"folder: {listing}. Each listed target file still exists on disk, but no "
        "sibling memory file mentions it, so the index would stop pointing to "
        "knowledge that is still there. This is the shape of the 2026-08-07 incident "
        "that dropped 311 of 409 memory citations in one write. Safe order: write the "
        "detail into its topic file (or another sibling) first, confirm it is "
        "reachable there, then shrink the head index and drop the citation. Deleting "
        "a memory file together with its own index line stays legal, since its "
        "target no longer exists and this check exempts it."
    )
    _emit_deny(reason)


def _emit_deny_jsonl(file_path: str) -> None:
    basename = os.path.basename(file_path)
    reason = (
        f"AGGREGATE WRITE GUARD: blocked write to '{basename}'. The proposed content "
        "is not the current on-disk content followed by new material only: order "
        "must be preserved and no existing line may move, be dropped, or have "
        f"another line spliced in ahead of it. '{basename}' is an append-only "
        "aggregate log; every write or edit must keep the existing content exactly "
        "as a prefix and add new lines only after it. If a deliberate rotation or "
        "prune is genuinely intended, do it as a separate, owner-authorized step "
        "outside this tool call, not through an agent Write, Edit, or MultiEdit."
    )
    _emit_deny(reason)


def _log(payload: dict, decision: str, detail: str = None) -> None:
    """Record this verdict to hook-activity.jsonl via the shared helper.
    Fires on both allow and deny for a protected path (never for a
    non-protected path, matching memory-dedup-check.py's placement
    convention: a record per unrelated write measures nothing). Never
    raises: logging must not be able to break the parent tool call.
    """
    try:
        sys.path.insert(0, _HOOKS_DIR)
        from _governance_logger import log_fire, session_from
        log_fire("aggregate-write-guard", decision=decision, detail=detail,
                  session=session_from(payload))
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return 0

    try:
        tool_name = payload.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            return 0  # matcher-scope leak guard: no-op on every other tool

        tool_input = payload.get("tool_input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
        if not isinstance(tool_input, dict):
            return 0

        file_path = tool_input.get("file_path", "")
        target = classify_target(file_path)
        if target is None:
            return 0  # not one of the three protected paths: stay silent

        current_content = _read_current(file_path)
        if not current_content:
            # Missing or empty on disk: bootstrap, always allow.
            _log(payload, "allow", f"bootstrap:{os.path.basename(file_path)}")
            return 0

        effective = effective_content(tool_name, tool_input, current_content)
        if effective is None:
            # Edit/MultiEdit's old_string was not found (or MultiEdit had no
            # usable edits list); the real tool fails on that mismatch on
            # its own. Do not double-guard.
            return 0

        if target == "memory_index":
            uncovered = uncovered_dropped_citations(current_content, effective)
            if uncovered:
                _emit_deny_memory(file_path, uncovered)
                _log(payload, "deny", f"memory:{','.join(uncovered[:MAX_LISTED_CITATIONS])}")
                return 0
            _log(payload, "allow", f"memory:{os.path.basename(file_path)}")
            return 0

        # target == "aggregate_log": one order-preserving rule, regardless
        # of tool (post-review Finding 1: no more tool_name branch here).
        if not aggregate_log_is_append_shaped(current_content, effective):
            _emit_deny_jsonl(file_path)
            _log(payload, "deny", f"jsonl:non-append:{os.path.basename(file_path)}")
            return 0

        _log(payload, "allow", f"jsonl:{os.path.basename(file_path)}")
        return 0
    except Exception:
        # Fail open: a broken guard must never block ordinary work.
        return 0


if __name__ == "__main__":
    sys.exit(main())
