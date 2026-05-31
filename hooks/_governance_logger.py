"""
Shared hook self-logging helper (E1 — silent-zero instrumentation fix, 2026-05-30).

Purpose: governance-log.py (Stop hook) only records Agent/Skill tool_use + the
turn classification. It is BLIND to hook firings — so registered, actively-firing
hooks (e.g. prose-codes-check) show 0 events in any utilization audit. This is the
empirically-confirmed "silent-zero" finding
(finding_governance_log_under_logs_silent_zero.md): "0 events" != unused.

This module gives any hook a one-line way to record its own firing to
hook-activity.jsonl, so future utilization audits can triangulate hook usage
instead of reading a false zero.

When it fires: only when a host hook explicitly calls log_fire(...). This module
does nothing on its own.

Failure-tolerance: log_fire NEVER raises. A logging failure must never crash the
host hook (crashing a hook crashes the turn — per CLAUDE.md / code-simplifier
Python-hook conventions). Every path is wrapped; on any error it silently no-ops.

Adoption snippet for a host hook (place after imports, before main logic):

    try:
        import os, sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("this-hook-name")           # decision=/detail=/session= optional
    except Exception:
        pass
"""

import os
import json
from datetime import datetime

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "hook-activity.jsonl",
)


def log_fire(hook, decision=None, detail=None, session=None):
    """Append one hook-firing record to hook-activity.jsonl. Never raises.

    hook:     str  — the host hook's name (e.g. "prose-codes-check")
    decision: str  — optional outcome ("block", "allow", "warn", None)
    detail:   any  — optional short context (truncated to 200 chars)
    session:  str  — optional session id if the host hook has it
    """
    try:
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": "hook_fire",
            "hook": str(hook),
            "decision": decision,
            "detail": (str(detail)[:200] if detail is not None else None),
            "session": session,
        }
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        # Instrumentation must never crash the host hook.
        pass
