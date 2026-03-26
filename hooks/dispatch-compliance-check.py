"""
Dispatch Compliance Check - Stop Hook
Verifies that skills/agents declared in MUST DISPATCH were actually invoked.
Reads transcript tail, finds last MUST DISPATCH field, checks Skill and Agent
tool_use blocks for matching dispatches. Blocks if any declared item is missing.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
- Case-insensitive field detection
- Multiline MUST DISPATCH: captures across line breaks until next field label
"""

import sys
import json
import os
import re

# 200KB window — covers even 10+ agent outputs per turn
READ_BYTES = 204800

# Field labels used as delimiters for multiline capture
FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'


def strip_fences(text):
    """Remove markdown fenced code blocks to prevent false matches on examples/docs."""
    return re.sub(r'```[\s\S]*?```', '', text)


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if payload.get("stop_hook_active"):
        return

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    # Read last 200KB of transcript
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    lines = tail.split("\n")

    must_dispatch = []
    dispatched = set()
    found_contract = False

    for line in lines:
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
            # Look for classification blocks containing MUST DISPATCH
            if block.get("type") == "text":
                text = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(text)
                # Only process MUST DISPATCH inside a REAL classification block
                valid_types = r'(?:Quick|Research|Analysis|Content|Build|Planning|Compound)'
                tt_match = re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*' + valid_types, clean, re.IGNORECASE)
                if tt_match:
                    # New classification resets everything
                    must_dispatch = []
                    dispatched = set()
                    found_contract = False
                    # Multiline MUST DISPATCH: capture until next field label, fence, or end
                    m = re.search(
                        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
                        clean,
                        re.DOTALL | re.IGNORECASE
                    )
                    if m:
                        raw = m.group(1).strip()
                        raw = raw.strip('`')
                        # Collapse whitespace/newlines into single space
                        raw = re.sub(r'\s+', ' ', raw)
                        if raw.lower().startswith("none") or raw.lower().startswith("n/a") or raw == "":
                            must_dispatch = []
                        else:
                            must_dispatch = [x.strip().lower() for x in raw.split(",") if x.strip()]
                        found_contract = True
                        dispatched = set()

            # Track Skill and Agent dispatches after the contract
            if found_contract and block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}

                if name == "Skill":
                    skill = (inp.get("skill") or "").lower()
                    if skill:
                        dispatched.add(skill)
                elif name == "Agent":
                    agent_type = (inp.get("subagent_type") or "").lower()
                    if agent_type:
                        dispatched.add(agent_type)

    if not found_contract or not must_dispatch:
        return

    missing = [item for item in must_dispatch if item not in dispatched]

    if missing:
        reason = (
            f"DISPATCH COMPLIANCE: MUST DISPATCH declared "
            f"[{', '.join(must_dispatch)}] but missing: "
            f"[{', '.join(missing)}]. Invoke them before completing."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        # Log block event
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0][:12] if transcript_path else "unknown"
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "block", "hook": "dispatch-compliance", "session": session_id, "declared": must_dispatch, "missing": missing})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
