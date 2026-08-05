#!/usr/bin/env python3
"""PostCompact hook: record compaction completion + staleness marker (Phase D dim1-C5).

Fires AFTER context compaction completes. PreCompact already writes the recovery
file (pre-compact.py); this hook closes the loop on the OTHER side:

  1. Instrumentation: records the compaction event so compaction frequency is
     visible in the silent-zero instrument (hook-activity.jsonl) and governance log.
  2. Staleness marker: writes _state/last-compact.json so SessionStart / process-lint
     can detect "context was compacted; qmd index + STATE.md may be stale" and prompt
     a refresh. (qmd is not re-indexed here: that is a heavier op; this only flags it.)

Constraint: PostCompact (like PreCompact) REJECTS hookSpecificOutput.additionalContext
(reference_compact_hooks_no_additionalcontext). So this hook does NOT inject context :
it only records + flags. Orientation after compaction stays the job of the
SessionStart(compact) recovery-file mechanism.

Exit codes: 0 always. Fail-open: never crashes the session.
"""
import json
import os
import sys
from datetime import datetime

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HOOKS_DIR, "_state")
MARKER = os.path.join(STATE_DIR, "last-compact.json")
GOV_LOG = os.path.join(HOOKS_DIR, "governance-log.jsonl")


def main() -> int:
    reason = ""
    session = "unknown"
    try:
        raw = sys.stdin.read()
        if raw:
            payload = json.loads(raw)
            reason = payload.get("reason") or payload.get("trigger") or ""
            session = payload.get("session_id") or "unknown"
    except Exception:
        pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Liveness + outcome into the silent-zero instrument.
    try:
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import log_fire
        log_fire("post-compact", decision="compacted", detail=reason, session=session)
    except Exception:
        pass

    # 2. Governance-log event (schema v2), so compaction frequency is queryable.
    try:
        from _event_emit import emit_event
        emit_event(
            event="compaction",
            hook="post-compact",
            session=session,
            environment="prod",
            extra={"reason": reason},
        )
    except Exception:
        pass

    # 3. Staleness marker for SessionStart / process-lint to read.
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(MARKER, "w", encoding="utf-8") as fh:
            json.dump({
                "last_compact": now, "reason": reason, "session": session,
                "note": "Context compacted. qmd index + STATE.md may be stale; "
                        "re-read STATE.md from disk before relying on memory.",
            }, fh, indent=2)
    except Exception:
        pass

    # PostCompact rejects additionalContext: stdout empty JSON only.
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
