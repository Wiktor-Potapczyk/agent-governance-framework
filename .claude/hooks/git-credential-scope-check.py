#!/usr/bin/env python3
"""git-credential-scope-check.py: SessionStart safeguard for Git Credential Manager scoping.

Background: this machine holds a host-level GitHub credential (work account) AND a
repo-scoped personal credential. ~/.gitconfig `credential.usehttppath = true` is the ONLY
config that makes GCM pick the repo-scoped credential instead of the host-level fallback.
If that line is lost, every github.com push silently authenticates as the wrong account
(NDA-relevant: the work account would be used for personal repo pushes).

Behaviour:
  - value exactly `true`  -> silent exit 0 (normal case)
  - value missing / other -> emit LOUD additionalContext warning + exit 0
  - any subprocess/OS error -> fail-open: print nothing, exit 0 (never block session start)

Scope: the check reads `credential.usehttppath` with `--global`, matching the scope the
remediation text tells the user to set (`git config --global credential.usehttppath true`).
Reading the effective (unscoped) value would silently disagree with the remediation if a
repo-local override happened to shadow a missing global value.

Cache: a fresh "ok" verification is cached in `_state/git-credential-scope.json` for 24h,
so this SessionStart hook does not shell out to `git` on every session. A prior "warn"
result, or a missing/unreadable state file, always re-runs the live check; the cache
only ever skips work when the last known state was good. Any state-file read/write error
fails open straight to the live check.

Output contract: stdout JSON per Anthropic SessionStart hook spec (hookSpecificOutput).
Exit code: always 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

_TIMEOUT = 5  # seconds; short: git config reads ~/.gitconfig locally, never network

_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_state")
_STATE_FILE = os.path.join(_STATE_DIR, "git-credential-scope.json")
_CACHE_TTL = timedelta(hours=24)


_SESSION: str | None = None  # set from the payload in main(); None when absent


def _log_fire(decision: str, detail: str | None = None) -> None:
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("git-credential-scope-check", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


def _read_cache() -> tuple[datetime | None, str | None]:
    """Best-effort read of the cache state file. Never raises.

    Returns (last_verified, result) on a well-formed cache, or (None, None) on
    any problem: missing file, unreadable JSON, missing/malformed fields.
    A (None, None) return always falls through to a live check (fail-open).
    """
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_iso = data.get("last_verified")
        result = data.get("result")
        if not isinstance(last_iso, str) or not isinstance(result, str):
            return None, None
        last_dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return last_dt, result
    except Exception:
        return None, None


def _write_cache(result: str) -> None:
    """Best-effort write of the cache state file. Never raises."""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_verified": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "result": result,
                },
                f,
            )
    except Exception:
        pass


def _cache_is_fresh_ok() -> bool:
    """True only when the cache holds a "ok" result verified under 24h ago.

    A prior "warn" result, a missing state file, or a state-file read error
    all return False here, which routes main() straight to the live check;
    per spec, only a fresh "ok" is ever allowed to skip the subprocess call.
    """
    last_dt, result = _read_cache()
    if last_dt is None or result != "ok":
        return False
    try:
        now = datetime.now(timezone.utc)
        if last_dt > now:
            # Future-dated timestamp (clock rollback, NTP correction, corrupted
            # ISO string) would otherwise satisfy (now - last_dt) < TTL forever.
            # Treat it as stale so the live check always runs.
            return False
        return (now - last_dt) < _CACHE_TTL
    except Exception:
        return False


def _emit_warning() -> None:
    context = (
        "[GIT CREDENTIAL SCOPE: WARNING] `credential.usehttppath` is NOT set to `true` "
        "in the global git config. The host-level work-account GitHub credential is now "
        "the GCM fallback for ALL github.com pushes on this machine. Personal-repo pushes "
        "will silently authenticate as the wrong account (NDA risk). "
        "Fix: run `git config --global credential.usehttppath true` before any git push."
    )
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    except Exception:
        pass


def main() -> int:
    global _SESSION
    # Consume stdin: SessionStart hooks receive a JSON payload on stdin.
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(raw)
    except Exception:
        _SESSION = None

    if _cache_is_fresh_ok():
        # Last live check was "ok" under 24h ago; skip the subprocess call,
        # but still record the fire so telemetry keeps seeing this hook run.
        _log_fire("cached-ok")
        return 0

    try:
        proc = subprocess.run(
            ["git", "config", "--global", "--get", "credential.usehttppath"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_TIMEOUT,
        )
    except Exception:
        # Fail-open: subprocess unavailable, PATH issue, timeout, etc.
        _log_fire("skip", "git-unavailable")
        return 0

    if proc.returncode != 0:
        # Key absent (git config --get exits non-zero when key is missing).
        _write_cache("warn")
        _log_fire("warn", "key-absent")
        _emit_warning()
        return 0

    value = proc.stdout.strip()
    if value == "true":
        # Silent: everything is correct.
        _write_cache("ok")
        _log_fire("ok")
        return 0

    # Value is present but not "true" (e.g. "false", "1", empty after strip).
    _write_cache("warn")
    _log_fire("warn", "value=%s" % (value or "<empty>"))
    _emit_warning()
    return 0


if __name__ == "__main__":
    sys.exit(main())
