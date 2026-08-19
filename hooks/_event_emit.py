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
excluded from aggregations by downstream aggregators, NOT at write time,
since the write itself is cheap and filtering is a read concern.
"""

import inspect
import json
import os
import re
import tempfile
from datetime import datetime


LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "governance-log.jsonl",
)
# Immutable snapshot of the true live path, taken once at import before any test
# can monkeypatch LOG_PATH. The belt-and-suspenders guard below only ever acts
# when LOG_PATH still equals this (i.e. no existing isolation mechanism, env
# var, or a test monkeypatching LOG_PATH directly) is already in effect.
_LIVE_LOG_PATH = LOG_PATH

_TEST_FRAME_RE = re.compile(r"^test_.*\.py$")
_TEST_FALLBACK_DIR = None  # lazily created per-process tempdir; guard fallback only


def _in_test_context() -> bool:
    """Best-effort detection of a call that bypasses conftest.py's pytest-only
    redirect fixture (see finding_unittest_bypasses_conftest_log_redirect.md:
    a bare `python -m unittest` run never loads conftest.py and never sets
    GOVERNANCE_LOG_PATH).

    Requires BOTH a test_*.py frame AND a unittest.TestCase-derived `self`
    bound in that frame (RISK-002 mitigation from the repair plan: filename
    alone would false-positive on a production hook merely imported from a
    file that happens to match that pattern). Never raises; any error returns
    False, failing toward the live path rather than toward misrouting a real
    record.
    """
    try:
        for frame_info in inspect.stack(0):
            if not _TEST_FRAME_RE.match(os.path.basename(frame_info.filename)):
                continue
            frame_self = frame_info.frame.f_locals.get("self")
            if frame_self is None:
                continue
            mro_names = {
                f"{cls.__module__}.{cls.__qualname__}" for cls in type(frame_self).__mro__
            }
            if "unittest.case.TestCase" in mro_names:
                return True
    except Exception:
        pass
    return False


def _test_fallback_path() -> str:
    """Per-process tempdir, created once on first use, mirroring conftest.py's
    own tempdir naming (tempfile.mkdtemp(prefix="hooks-suite-logs-"))."""
    global _TEST_FALLBACK_DIR
    if _TEST_FALLBACK_DIR is None:
        _TEST_FALLBACK_DIR = tempfile.mkdtemp(prefix="hooks-suite-logs-")
    return os.path.join(_TEST_FALLBACK_DIR, "governance-log.jsonl")


def _log_path():
    """Resolve the destination at call time, not import time.

    GOVERNANCE_LOG_PATH overrides the module constant. This exists so a writer
    migrating onto this helper (contract C7) keeps the test isolation it has
    today: several direct writers redirect their own writes during tests via a
    per-hook env var, and without an equivalent here that redirection would
    silently vanish and the test would append to the real governance log.
    Resolving here rather than at import also keeps `_event_emit.LOG_PATH`
    monkeypatchable, which is the other way tests target this module.

    Belt-and-suspenders (2026-08-07): when NEITHER the env var NOR a test's own
    monkeypatch of LOG_PATH is already redirecting the write (i.e. LOG_PATH
    still equals the untouched live default), fall back to a per-process
    tempfile if the call stack shows we are inside a unittest.TestCase. This
    closes the one bypass class the env-var/conftest mechanism cannot reach:
    `python -m unittest` on a hook test file whose test code never touches
    this module at all, so the real hook script under test writes straight to
    the live file. A test that already monkeypatches LOG_PATH itself is left
    alone: LOG_PATH != _LIVE_LOG_PATH there, so this branch never fires and
    the test's own isolation choice wins.
    """
    override = os.environ.get("GOVERNANCE_LOG_PATH", "")
    if isinstance(override, str) and override.strip():
        return override.strip()
    if LOG_PATH == _LIVE_LOG_PATH and _in_test_context():
        return _test_fallback_path()
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
        # Silent: telemetry must not break parent hooks.
        pass
