r"""
Plain-Language Guard - PostToolUse Write|Edit hook  [LIVE, warn-only, blocks OFF]

Thin wrapper over plain_language_check.py (the T1 checker module). Spec of
record: .claude/plain-language-rules.md. Plan of record:
Projects/your-project/work/2026-08-10-plain-language-standard-plan.md
(v2, owner-approved 2026-08-11). Payload-handling template: prose-slop-check.py.

SCOPE (the three enforced surfaces of the applicability matrix; slash-tolerant):
  Projects/*/work/**.md          minus any work/backups/ path
  Resources/KB/**.md
  framework-repo/README.md and framework-repo/docs/**.md

CONTENT: tool_input.content for Write; tool_input.new_string for Edit.
  Documented limitation: on Edit only the new text is scanned, so a violation
  assembled across several small Edits is invisible until the next full Write
  or corpus lint run.

PER-WRITE JSONL CONTRACT (B1 closure, non-negotiable): for EVERY in-scope
  write, findings or none, append exactly ONE record to
  .claude/hooks/aggregates/plain-language-warnings.jsonl:
    {ts, session, path, per_rule_finding_counts, total_findings}
  ts uses the shared activity-log format (%Y-%m-%d %H:%M:%S); session comes
  from _governance_logger.session_from(payload); per_rule_finding_counts
  carries all ten PL keys with zeros included. One record per invocation,
  never per finding: the calibration denominator is the line count.
  Concurrency note: multi-session concurrency is the norm (2026-08-08 ruling).
  This hook follows the same single-line append-mode idiom _governance_logger
  uses; the small risk of interleaved appends from concurrent sessions is
  accepted rather than building file locking.

ADVISORY: when total_findings > 0, ONE stderr message naming rule ids, the
  file basename, and up to three offending samples with plain remediation
  wording. Marker-hygiene advisories (unclosed <!-- MM1 -->) surface too.
  NEVER blocks in the shipped config; exit 0 always.

BLOCK-FLIP MACHINERY, SHIPPED OFF: BLOCK_ENABLED_RULES ships as an EMPTY set.
  The exit-2 path below consults it and can only fire for a rule someone
  deliberately adds in a future Stage 4 flip (per-rule, after calibration,
  owner sign-off). Corrected 2026-08-11 (post-review Finding 3): this hook
  runs PostToolUse, so the write it is scanning has already landed on disk
  by the time this code executes. Flipping a rule into BLOCK_ENABLED_RULES
  does NOT gain the ability to prevent or undo that write; it only changes
  this hook's own stderr framing and log record from WARN to a loud
  after-the-fact violation report. Genuine write-time prevention would need
  a separate PreToolUse companion hook, which is explicitly out of Stage 1
  scope. test_plain_language_guard.py asserts the shipped value is empty
  and that no input can produce exit 2 with it.

FAIL-OPEN: any internal exception is caught, exit 0, no advisory. The log
  append is separately wrapped so a locked or missing aggregates file cannot
  break a write.

OVERLAP: DISJOINT from prose-slop-check.py (2026-08-11 discovery gate verdict;
  zero shared wordlist entries, both warn-only, thresholds keep prose-slop
  mostly silent). Both hooks stand, cross-referenced.

EXIT CODES (this hook is PostToolUse: the write is already on disk before
  either code path below runs; neither exit code can stop or reverse it)
  0 = always in the shipped config (clean OR warn); the write already
      happened, this exit code just means no block-enabled rule fired
  2 = only reachable when a rule id is in BLOCK_ENABLED_RULES (Stage 4,
      shipped empty so unreachable in this build). NOT a deny and NOT a
      block in the PreToolUse sense: it is a loud after-the-fact violation
      report over a write that already succeeded. True prevention needs a
      PreToolUse companion hook, out of Stage 1 scope (corrected 2026-08-11,
      post-review Finding 3; no behavior changed, BLOCK_ENABLED_RULES stays
      empty).
"""

import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plain_language_check import scan  # noqa: E402

# Stage 4 machinery, shipped OFF. Add rule ids (e.g. "PL-5") only through the
# calibrated per-rule flip process; never flip all rules at once.
BLOCK_ENABLED_RULES: set = set()

AGG_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "aggregates",
    "plain-language-warnings.jsonl",
)

_TARGET_RE = re.compile(
    r"(?:resources[\\/]kb[\\/].*\.md$)"
    r"|(?:projects[\\/][^\\/]+[\\/]work[\\/].*\.md$)"
    r"|(?:framework-repo[\\/]readme\.md$)"
    r"|(?:framework-repo[\\/]docs[\\/].*\.md$)",
    re.IGNORECASE,
)
_BACKUPS_RE = re.compile(r"[\\/]work[\\/]backups[\\/]", re.IGNORECASE)


def in_scope(file_path):
    norm = (file_path or "").replace("\\", "/")
    return bool(_TARGET_RE.search(norm)) and not _BACKUPS_RE.search(norm)


def _append_record(record):
    """Append one JSONL record. Never raises: a locked or missing aggregates
    file must not break the write or swallow the advisory."""
    try:
        os.makedirs(os.path.dirname(AGG_LOG_PATH), exist_ok=True)
        with open(AGG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _log_fire(payload, decision, detail=None):
    """Standard shared-activity-logger pattern; hook-runtime behavior, not an
    agent write. Never raises."""
    try:
        from _governance_logger import log_fire, session_from
        log_fire("plain-language-guard", decision=decision, detail=detail,
                 session=session_from(payload))
    except Exception:
        pass


def _session(payload):
    try:
        from _governance_logger import session_from
        return session_from(payload)
    except Exception:
        return None


def _main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return 0
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not in_scope(file_path):
        return 0  # out of scope: no output, no log record

    content = tool_input.get("content")
    if content is None:
        content = tool_input.get("new_string") or ""

    result = scan(content)
    per_rule = result["per_rule_finding_counts"]
    total = result["total_findings"]

    _append_record({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": _session(payload),
        "path": file_path,
        "per_rule_finding_counts": per_rule,
        "total_findings": total,
    })

    hit_rules = ", ".join(f"{r} x{n}" for r, n in per_rule.items() if n)
    samples = "; ".join(
        f"[{f['rule']} line {f['line']}] {f['text']}" for f in result["findings"][:3]
    )
    hygiene = " ".join(result["marker_advisories"])

    blocked = sorted(r for r in BLOCK_ENABLED_RULES if per_rule.get(r, 0) > 0)
    if blocked:
        sys.stderr.write(
            f"[plain-language-guard BLOCK] {os.path.basename(file_path)}: "
            f"block-enabled rule(s) {', '.join(blocked)} found violations: {samples}. "
            f"Rewrite per .claude/plain-language-rules.md and retry the write.\n"
        )
        _log_fire(payload, "block", hit_rules)
        return 2

    if total > 0 or hygiene:
        message = f"[plain-language-guard WARN] {os.path.basename(file_path)}"
        if total > 0:
            message += (
                f" has plain-language findings ({hit_rules}): {samples}. "
                f"Prefer short sentences, active voice, everyday words, and "
                f"concrete values (rules: .claude/plain-language-rules.md)."
            )
        if hygiene:
            message += f" Marker hygiene: {hygiene}"
        sys.stderr.write(message + " (advisory - write was kept.)\n")
        _log_fire(payload, "warn", hit_rules or "marker-hygiene")
        return 0

    _log_fire(payload, "allow")
    return 0


def main():
    try:
        return _main()
    except Exception:
        return 0  # fail-open: an internal error must never wedge a write


if __name__ == "__main__":
    sys.exit(main())
