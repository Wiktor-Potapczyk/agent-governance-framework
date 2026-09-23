#!/usr/bin/env python3
"""pretooluse-payload-probe.py: TEMPORARY PreToolUse probe (matcher: Write|Edit|MultiEdit).

Hermes P2 build Step 2 (2026-08-18): closes the UNVERIFIED item from
[[2026-08-17-hermes-p2-context-discrimination-research]]: whether `agent_type`
reaches PreToolUse payloads for non-reviewer agent types (only the
reviewer-agent subset is empirically confirmed, 29,445 firings via
reviewer-scope-violation-check.py).

Appends ONE metadata-only JSONL record per matched call to
.claude/hooks/_state/pretooluse-payload-probe.jsonl:
  - payload key list (names only)
  - agent_type value, or the explicit marker "<ABSENT>"
  - tool name
  - transcript_path presence (bool), never its content

No file bodies, no prompts, no content (the subagent-payload-probe.jsonl
precedent). Deregistered after the probe window; this file is retained as
evidence alongside its log. Fail-open: any exception exits 0 silently.
"""

import json
import os
import sys
from datetime import datetime, timezone

_LOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_state", "pretooluse-payload-probe.jsonl"
)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    try:
        if not isinstance(payload, dict):
            return 0
        agent_type = payload.get("agent_type")
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload_keys": sorted(payload.keys()),
            "agent_type": agent_type if agent_type not in (None, "") else "<ABSENT>",
            "tool_name": payload.get("tool_name", ""),
            "transcript_path_present": bool(payload.get("transcript_path")),
        }
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
