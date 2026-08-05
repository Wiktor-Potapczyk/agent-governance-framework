"""
Shared hook self-logging helper (E1: silent-zero instrumentation fix, 2026-05-30).

Purpose: governance-log.py (Stop hook) only records Agent/Skill tool_use + the
turn classification. It is BLIND to hook firings: so registered, actively-firing
hooks (e.g. prose-codes-check) show 0 events in any utilization audit. This is the
empirically-confirmed "silent-zero" finding
(finding_governance_log_under_logs_silent_zero.md): "0 events" != unused.

This module gives any hook a one-line way to record its own firing to
hook-activity.jsonl, so future utilization audits can triangulate hook usage
instead of reading a false zero.

When it fires: only when a host hook explicitly calls log_fire(...). This module
does nothing on its own.

Failure-tolerance: log_fire NEVER raises. A logging failure must never crash the
host hook (crashing a hook crashes the turn: per CLAUDE.md / code-simplifier
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


def _log_path():
    """Resolve the destination at call time, not import time.

    HOOK_ACTIVITY_LOG_PATH overrides the module constant. This is the twin of
    _event_emit's GOVERNANCE_LOG_PATH: without it the test suite writes into the
    live stream on every run (measured at 117 records per hooks-suite run), and
    those synthetic records are not merely analytics noise. hook_activity_report
    derives its fire counts and dark-hook list from this file, and the Step-11
    competence gate reads a bounded tail of the other one, so test writes evict
    real history. Resolving here rather than at import also keeps _LOG_PATH
    monkeypatchable, which is how the existing tests target this module.
    """
    override = os.environ.get("HOOK_ACTIVITY_LOG_PATH", "")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return _LOG_PATH


def session_from(payload):
    """Best-effort real session id from a hook payload. Never raises, never guesses.

    Accepts the payload dict a hook already parsed, or the raw stdin text before
    parsing. Returns the session id string, or None when the payload carries no
    identity (contract C3: a record that carries a session must carry a REAL one,
    and a record that cannot know its session carries null rather than a placeholder).

    Fallback order matches the established convention in session-start-log.py:
    session_id first, then the transcript filename stem.
    """
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            payload = json.loads(payload or "{}")
        if not isinstance(payload, dict):
            return None
        sid = payload.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        tpath = payload.get("transcript_path")
        if isinstance(tpath, str) and tpath.strip():
            stem = os.path.splitext(os.path.basename(tpath.strip()))[0]
            return stem or None
    except Exception:
        pass
    return None


def log_fire(hook, decision=None, detail=None, session=None):
    """Append one hook-firing record to hook-activity.jsonl. Never raises.

    hook:     str : the host hook's name (e.g. "prose-codes-check")
    decision: str : optional outcome ("block", "allow", "warn", None)
    detail:   any : optional short context (truncated to 200 chars)
    session:  str : optional session id if the host hook has it
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
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        # Instrumentation must never crash the host hook.
        pass
