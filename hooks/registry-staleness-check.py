#!/usr/bin/env python3
"""SessionStart registry staleness check (GEN-CADENCE, 2026-06-01).

Reads registry.json's `generated_at` field (falls back to file mtime when
the field is absent).  If the registry is older than THRESHOLD_DAYS, emits
a NON-BLOCKING additionalContext advisory telling the user to regenerate it.
When the registry is fresh the hook emits nothing (zero noise). When the
registry is MISSING it emits a one-line gentle note to generate it (useful on
first run), never an alarm. All failure paths swallow errors and exit 0.

Output contract: stdout JSON per SessionStart hook spec.  Never blocks :
errors silently swallowed, clean exit 0 on every failure path.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT = Path(os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
))
REGISTRY_PATH = VAULT / ".claude" / "registry.json"

THRESHOLD_DAYS = 7


def _registry_age_days() -> float | None:
    """Return how many days old registry.json is, or None if it cannot be determined."""
    if not REGISTRY_PATH.exists():
        return None

    # Prefer the `generated_at` field written by the generator
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts_str = data.get("generated_at") or data.get("generated")
        if ts_str:
            # Handle both naive ISO strings and offset-aware ones
            ts_str = ts_str.replace("Z", "+00:00")
            try:
                generated_at = datetime.fromisoformat(ts_str)
            except ValueError:
                # Truncated format without timezone (e.g. "2026-05-01T14:30:00")
                generated_at = datetime.fromisoformat(ts_str[:19]).replace(tzinfo=timezone.utc)
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - generated_at
            return age.total_seconds() / 86400
    except Exception:
        pass  # Fall through to mtime

    # Fallback: file modification time
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)
        return age.total_seconds() / 86400
    except Exception:
        return None


def build_warning() -> str:
    """Return an advisory string when the registry is stale, or '' when fresh/missing."""
    age_days = _registry_age_days()

    if age_days is None:
        # Registry does not exist at all: gentle note, not an alarm
        return (
            "[REGISTRY] registry.json not found. "
            "Run `python .claude/scripts/generate_registry.py` to build the asset inventory."
        )

    if age_days <= THRESHOLD_DAYS:
        return ""  # Fresh: silent

    age_int = int(age_days)
    return (
        f"[REGISTRY] registry.json is {age_int} day{'s' if age_int != 1 else ''} old "
        f"(threshold: {THRESHOLD_DAYS} days). "
        "Run `python .claude/scripts/generate_registry.py` to refresh the asset inventory."
    )


_SESSION = None  # set from the payload in main(); None when identity is absent


def _log_fire(decision, detail=None):
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("registry-staleness-check", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


def main() -> None:
    global _SESSION
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

    try:
        warning = build_warning()
    except Exception:
        warning = ""

    if not warning:
        _log_fire("fresh")
        return  # Fresh registry: emit nothing, zero noise

    _log_fire("stale", warning[:120])

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": warning,
        }
    }
    try:
        print(json.dumps(output))
    except Exception:
        pass


if __name__ == "__main__":
    main()
