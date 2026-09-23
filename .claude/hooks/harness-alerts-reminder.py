#!/usr/bin/env python3
"""harness-alerts-reminder.py - SessionStart reader for scheduler_watchdog.py's
Resources/Observability/harness-alerts.md (2026-09-15, Phase B TASK-011).

Silent when there is nothing to say: the "## Current alerts" section reads
"None." AND the last_run line is under 3h old. Otherwise surfaces one of:
  - a bounded (<= 15 lines) block starting "HARNESS ALERTS (scheduler
    watchdog):" when alerts are present
  - a one-line staleness notice when alerts are clean but last_run is
    older than 3h (the watchdog runs hourly, so 3h means at least two
    missed cycles; the watchdog itself is silent about its own staleness,
    this hook is the one thing that notices)
  - a one-line missing-file notice when harness-alerts.md does not exist

Fail-open, matching every SessionStart hook in this vault: any error falls
back to an empty additionalContext rather than raising.

Output contract: stdout JSON, hookSpecificOutput.additionalContext, same
shape as lint-cadence-trigger.py.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ALERTS_MD_PATH = os.path.join(VAULT, "Resources", "Observability", "harness-alerts.md")

STALENESS_THRESHOLD_HOURS = 3
MAX_CONTEXT_LINES = 15

_LAST_RUN_RE = re.compile(r"^last_run:\s*(.+)$", re.MULTILINE)
_CURRENT_ALERTS_RE = re.compile(
    r"## Current alerts\s*\n\n(.*?)\n\n## Fleet", re.DOTALL
)


def parse_alerts_file(text: str):
    """Return (alert_lines: list[str], last_run: str | None, section_parseable: bool).

    section_parseable is False when the '## Current alerts' section does not
    match the exact-byte-sequence regex at all (e.g. a human edit broke the
    required blank line): distinct from a section that matched and is
    genuinely empty/"None.", which is a parse failure, not "no alerts."
    """
    last_run = None
    m = _LAST_RUN_RE.search(text)
    if m:
        last_run = m.group(1).strip()

    alerts = []
    section = _CURRENT_ALERTS_RE.search(text)
    section_parseable = section is not None
    if section:
        body = section.group(1).strip()
        if body and body != "None.":
            alerts = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- ")]
    return alerts, last_run, section_parseable


def _parse_iso(value: str):
    try:
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _bound_alert_block(alerts: list) -> str:
    header = "HARNESS ALERTS (scheduler watchdog):"
    lines = [header]
    budget = MAX_CONTEXT_LINES - 1
    shown = alerts[:budget]
    lines.extend(shown)
    remaining = len(alerts) - len(shown)
    if remaining > 0:
        lines = lines[: MAX_CONTEXT_LINES - 1]
        lines.append(
            f"(+{len(alerts) - len(lines) + 1} more; see "
            "Resources/Observability/harness-alerts.md)"
        )
    return "\n".join(lines[:MAX_CONTEXT_LINES])


def build_context(text: str, now: datetime, path: str = None) -> str:
    """additionalContext for an alerts file whose content is already read."""
    display_path = path if path is not None else ALERTS_MD_PATH
    alerts, last_run, section_parseable = parse_alerts_file(text)

    if not section_parseable:
        return f"HARNESS ALERTS (scheduler watchdog): alerts file unparseable at {display_path}"

    if alerts:
        return _bound_alert_block(alerts)

    if not last_run:
        return "[HARNESS ALERTS] last_run line missing or unparseable in harness-alerts.md."

    last_dt = _parse_iso(last_run)
    if last_dt is None:
        return "[HARNESS ALERTS] last_run line missing or unparseable in harness-alerts.md."

    age = now - last_dt
    if age <= timedelta(hours=STALENESS_THRESHOLD_HOURS):
        return ""

    age_hours = age.total_seconds() / 3600
    return (
        f"[HARNESS ALERTS] watchdog last ran {age_hours:.1f}h ago (stale; "
        f"expected hourly, threshold {STALENESS_THRESHOLD_HOURS}h). "
        "No open alerts as of that run."
    )


def main():
    session_id = None
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        session_id = session_from(payload)
    except Exception:
        pass

    context = ""
    try:
        now = datetime.now(timezone.utc)
        if not os.path.isfile(ALERTS_MD_PATH):
            context = (
                "[HARNESS ALERTS] Resources/Observability/harness-alerts.md not found; "
                "the scheduler watchdog has not run yet."
            )
        else:
            with open(ALERTS_MD_PATH, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            context = build_context(text, now, path=ALERTS_MD_PATH)
    except Exception:
        context = ""

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire(
            "harness-alerts-reminder",
            decision=("surfaced" if context else "quiet"),
            detail=(context[:200] if context else None),
            session=session_id,
        )
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    try:
        print(json.dumps(output))
    except Exception:
        pass


if __name__ == "__main__":
    main()
