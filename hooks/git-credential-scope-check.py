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

Output contract: stdout JSON per Anthropic SessionStart hook spec (hookSpecificOutput).
Exit code: always 0.
"""

from __future__ import annotations

import json
import subprocess
import sys

_TIMEOUT = 5  # seconds; short: git config reads ~/.gitconfig locally, never network


_SESSION: str | None = None  # set from the payload in main(); None when absent


def _log_fire(decision: str, detail: str | None = None) -> None:
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("git-credential-scope-check", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


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
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(raw)
    except Exception:
        _SESSION = None

    try:
        proc = subprocess.run(
            ["git", "config", "--get", "credential.usehttppath"],
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
        _log_fire("warn", "key-absent")
        _emit_warning()
        return 0

    value = proc.stdout.strip()
    if value == "true":
        # Silent: everything is correct.
        _log_fire("ok")
        return 0

    # Value is present but not "true" (e.g. "false", "1", empty after strip).
    _log_fire("warn", "value=%s" % (value or "<empty>"))
    _emit_warning()
    return 0


if __name__ == "__main__":
    sys.exit(main())
