"""Shared resolver for out-of-chat QA and PM report artifacts.

Owner ruling 2026-09-11, verbatim: "yeah i mean the QA and PM notes, I dont want
to see them". The QA SCOPE / QA REPORT / PM CHECKPOINT REPORT blocks were
mandatory UNFENCED text in the visible reply, because four Stop hooks matched
those literal strings in the assistant's own message. That made roughly fifteen
lines of enforcement scaffolding visible on every non-Quick turn.

The blocks are not deleted. They move to a file, and the reply carries ONE
reference line instead. This module is the single place that knows the
reference format, so the four consumers cannot drift apart:

  process-step-check.py   hard gate: SCOPE + QA REPORT + PM CHECKPOINT REPORT
  work-verification-check.py  hard gate: a report with zero tool calls
  task-plan-auto-sync.py  reads the QA verdict to stamp task_plan.md
  dark-zone-check.py      counts a report as work evidence

Why a reference rather than "just look for today's file": the gate must bind to
THIS turn. A file sitting on disk from last week would pass a presence check
forever, which is the "checks that cannot fail" trap this vault has already been
bitten by twice (see finding_an_audit_instrument_needs_its_own_audit). So a
referenced artifact must ALSO be fresh, and must ALSO physically contain the
block it claims. Presence of the reference line alone proves nothing.
"""
import os
import re
import time
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT")
             or Path(__file__).resolve().parent.parent.parent)

# One line, at start of line, naming a kind, a verdict, and a vault-relative .md
# path after a bare '>'. Deliberately strict: a loose pattern would let ordinary
# prose that happens to mention a path satisfy a hard gate.
REFERENCE_RE = re.compile(
    r'^[ \t]*(?P<kind>QA|PM)\b[^\n>]{0,160}?>[ \t]*(?P<path>[^\s>][^\n]*?\.md)[ \t]*$',
    re.MULTILINE,
)

# A referenced artifact must have been written recently enough to belong to the
# turn that cites it. Generous by design: a long QA run plus the write can span
# many minutes, and this is an anti-staleness bound, not a stopwatch.
MAX_AGE_SECONDS = int(os.environ.get("REPORT_ARTIFACT_MAX_AGE", "1800"))

# What each kind must physically contain to count.
REQUIRED_STRINGS = {
    "QA": ("QA REPORT",),
    "PM": ("PM CHECKPOINT REPORT",),
}


def find_references(text, kind=None):
    """Return [(kind, Path)] for every reference line in text.

    Paths are resolved against the vault root. An absolute path is accepted as
    written, so a hook running against a temp fixture still resolves.
    """
    out = []
    for m in REFERENCE_RE.finditer(text or ""):
        found_kind = m.group("kind").upper()
        if kind and found_kind != kind.upper():
            continue
        raw = m.group("path").strip().strip('`')
        p = Path(raw)
        out.append((found_kind, p if p.is_absolute() else VAULT / raw))
    return out


def artifact_text(path, max_bytes=200_000):
    """Return the artifact's text, or '' if unreadable. Never raises.

    Fails CLOSED for the gates: an unreadable artifact yields no content, so a
    caller checking for a required string will not find it and the gate holds.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(max_bytes)
    except Exception:
        return ""


def is_fresh(path, now=None):
    """True when the artifact was modified within MAX_AGE_SECONDS."""
    try:
        age = (now or time.time()) - Path(path).stat().st_mtime
    except Exception:
        return False
    # A negative age means the mtime sits in the future (clock skew or a
    # filesystem with coarse timestamps). Treat that as fresh rather than
    # failing a real artifact over a clock detail.
    return age <= MAX_AGE_SECONDS


def satisfied_by_artifact(text, kind, required=None, verdict_re=None):
    """True when text cites a fresh artifact that really contains the block.

    required: extra literal strings the artifact must carry (defaults to the
    kind's entry in REQUIRED_STRINGS).
    verdict_re: optional compiled regex the artifact must also match, so a file
    containing the header but no PASS/FAIL verdict does not satisfy the gate.
    """
    needles = tuple(required) if required else REQUIRED_STRINGS.get(kind.upper(), ())
    for _, path in find_references(text, kind=kind):
        if not is_fresh(path):
            continue
        body = artifact_text(path)
        if not body:
            continue
        if any(n not in body for n in needles):
            continue
        if verdict_re and not verdict_re.search(body):
            continue
        return True
    return False


def resolved_artifact_text(text, kind):
    """Return the text of the first fresh, readable artifact cited for kind.

    Used by task-plan-auto-sync, which needs the QA block's CONTENT (pass line,
    scope, task id), not merely a yes or no.
    """
    for _, path in find_references(text, kind=kind):
        if not is_fresh(path):
            continue
        body = artifact_text(path)
        if body:
            return body
    return ""
