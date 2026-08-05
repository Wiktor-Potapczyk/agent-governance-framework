"""
Shared event-emit helper for observability v2 (2026-04-19).

Usage (in any hook):
    from _event_emit import emit_event, is_test_session

    emit_event(
        event="classification_emitted",
        hook="classifier-field-check",
        session=session_id,
        extra={"type": "Research", "domain": "analytics"},
    )

All emits MUST carry schema=2 and environment field. Failures are silent
(logging must never break the parent flow).

Test-session filter: synthetic session IDs from fixtures/pentests are
excluded from aggregations by downstream aggregators — NOT at write time,
since the write itself is cheap and filtering is a read concern.
"""

import json
import os
import re
from datetime import datetime


LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "governance-log.jsonl",
)


def _log_path():
    """Resolve the destination at call time, not import time.

    GOVERNANCE_LOG_PATH overrides the module constant. This exists so a writer
    migrating onto this helper keeps its test isolation: several direct writers
    redirect their own writes during tests via a per-hook env var, and without
    an equivalent here that redirection would silently vanish and the test would
    append to the real governance log. Resolving here rather than at import also
    keeps `_event_emit.LOG_PATH` monkeypatchable, which is the other way tests
    target this module.
    """
    override = os.environ.get("GOVERNANCE_LOG_PATH", "")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return LOG_PATH


_TEST_SESSION_RE = re.compile(
    r"^(?:fixture-|pentest-|h5-|h3-|fake-|test$|test[-_]|unknown$)",
    re.IGNORECASE,
)


def is_test_session(session_id):
    """True if session_id matches known synthetic test/fixture patterns."""
    if not session_id:
        return True
    return bool(_TEST_SESSION_RE.match(session_id))


def detect_environment():
    """Return 'test' if caller appears to be under test harness, else 'prod'.

    Detection: env var OBSERVABILITY_ENV overrides; otherwise default 'prod'.
    Hook authors under a harness should set OBSERVABILITY_ENV=test.
    """
    env = os.environ.get("OBSERVABILITY_ENV", "").strip().lower()
    if env == "test":
        return "test"
    return "prod"


def emit_event(event, hook, session, extra=None, environment=None):
    """Append one JSON-line event to governance-log.jsonl.

    Never raises; never blocks parent flow. Schema v2 mandatory fields:
    ts, schema, event, hook, session, environment.
    """
    try:
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": event,
            "hook": hook,
            "session": session or "unknown",
            "environment": environment or detect_environment(),
        }
        if extra and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in entry:
                    entry[k] = v
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Silent — telemetry must not break parent hooks.
        pass
