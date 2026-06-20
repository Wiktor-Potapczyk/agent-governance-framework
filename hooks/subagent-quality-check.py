#!/usr/bin/env python3
"""SubagentStop Hook - L2 exit gate: structural quality check on agent output."""
import json
import sys
import os
import re
from datetime import datetime

# Pure detection logic lives in the sibling module (extracted 2026-06-02 for
# boundary-testability: see _subagent_quality_logic.py). Make it importable.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)
from _subagent_quality_logic import classify_subagent_output  # noqa: E402


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return

    if not raw:
        return

    try:
        payload = json.loads(raw)
    except Exception:
        return

    # Prevent infinite loops
    if payload.get("stop_hook_active") is True:
        return

    agent_type = payload.get("agent_type", "unknown")
    agent_id = payload.get("agent_id", "unknown")
    message = payload.get("last_assistant_message", "")
    message_len = len(message)

    # P1-D fix (2026-04-09): Extract full session UUID from transcript_path
    # (fallback to "unknown" if not in payload). Needed for cross-source joins.
    transcript_path = payload.get("transcript_path")
    if transcript_path:
        session_id = os.path.splitext(os.path.basename(transcript_path))[0]
    else:
        session_id = "unknown"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subagent-quality.log")

    def log_and_block(result, check_failed, reason):
        # 2026-05-10: capture violation excerpt so log entries are auditable
        # (per finding_must_dispatch_compliance_53pct.md: 11 unauditable blocks/week pre-fix)
        violation_excerpt = (message[:200] + "...") if message_len > 200 else message
        violation_excerpt = violation_excerpt.replace("\n", " ").replace("\r", " ").strip()

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result={result} | failed={check_failed} | excerpt={violation_excerpt[:120]}\n")
        except Exception:
            pass
        # Also log to governance-log.jsonl
        # P1-D + P1-E fix (2026-04-09): added session + schema fields for analytics joins
        # 2026-05-10: added violation_excerpt + reason for actionable diagnostics
        try:
            gov_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            entry = json.dumps({
                "ts": timestamp,
                "schema": 2,
                "event": "block",
                "hook": "subagent-quality-check",
                "session": session_id,
                "agent_type": agent_type,
                "agent_id": agent_id,
                "message_len": message_len,
                "check_failed": check_failed,
                "violation_excerpt": violation_excerpt,
                "block_reason": reason,
            })
            with open(gov_log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        response = {"decision": "block", "reason": reason}
        print(json.dumps(response))
        sys.exit(0)

    # Structural quality checks (CHECK 1/2/3): extracted to
    # _subagent_quality_logic.classify_subagent_output 2026-06-02 for
    # boundary-testability; behavior preserved exactly.
    blocked, check_failed, reason = classify_subagent_output(message)
    if blocked:
        log_and_block("BLOCK", check_failed, reason)

    # All checks passed
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result=PASS\n")
    except Exception:
        pass

if __name__ == "__main__":
    main()
