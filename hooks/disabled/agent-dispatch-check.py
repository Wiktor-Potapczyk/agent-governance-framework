"""
Agent Dispatch Check - PreToolUse Hook (matcher: Agent)
Validates that the agent being dispatched is in the MUST DISPATCH list.
If MUST DISPATCH is "none" or absent, allows any dispatch.
If MUST DISPATCH lists specific agents, only those are allowed.
Non-specialist dispatches (general-purpose, Explore) are always allowed.
"""

import sys
import json
import os
import re


# Agent types that are always allowed (infrastructure, not specialist routing)
ALWAYS_ALLOWED = {"general-purpose", "explore", "plan", "bash"}


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Get the agent being dispatched
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    agent_type = (tool_input.get("subagent_type") or "").lower()
    if not agent_type:
        return  # No type specified = general-purpose, allow

    # Always allow infrastructure agents
    if agent_type in ALWAYS_ALLOWED:
        return

    # Read transcript for last MUST DISPATCH
    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return  # Can't verify, allow

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(81920, file_size)

    with open(transcript_path, "r", encoding="utf-8") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Find the last MUST DISPATCH in a valid classification block
    must_dispatch = []
    valid_types = re.compile(
        r'TASK TYPE:\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)',
        re.IGNORECASE
    )

    for line in tail.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue

        message = entry.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                if valid_types.search(text):
                    # New classification resets
                    must_dispatch = []
                    m = re.search(r'MUST DISPATCH:\s*(.+)', text)
                    if m:
                        raw = m.group(1).strip().strip('`')
                        if raw.lower().startswith("none") or raw.lower().startswith("n/a") or raw == "":
                            must_dispatch = []
                        else:
                            must_dispatch = [x.strip().lower() for x in raw.split(",")]

    # If no MUST DISPATCH or it's empty/none, allow any agent
    if not must_dispatch:
        return

    # Check if this agent is in the MUST DISPATCH list
    if agent_type not in must_dispatch:
        reason = (
            f"AGENT DISPATCH: '{agent_type}' is not in MUST DISPATCH list "
            f"[{', '.join(must_dispatch)}]. Only dispatch declared agents."
        )
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(result))
        # Log deny event
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0][:12] if transcript_path else "unknown"
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "deny", "hook": "agent-dispatch-check", "session": session_id, "agent_type": agent_type, "must_dispatch": must_dispatch})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        return

    # Agent is in the list — allow
    return


if __name__ == "__main__":
    main()
