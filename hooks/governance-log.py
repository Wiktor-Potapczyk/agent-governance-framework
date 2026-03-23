"""
Governance Log - Stop Hook
Captures classification, dispatch, and agent activity per response.
Appends one JSON line to governance-log.jsonl per response.
Does NOT block -- logging only.

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
from datetime import datetime


LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "governance-log.jsonl"
)

# 200KB window -- covers even 10+ agent outputs per turn
READ_BYTES = 204800

VALID_TYPES = re.compile(
    r'(?:TASK TYPE|CLASSIFICATION):\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)',
    re.IGNORECASE
)

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

    # Don't log during stop-hook-active retries
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

    # Extract data from the last assistant turn
    last_type = None
    last_domain = None
    last_must_dispatch = None
    last_implies = None
    agents_dispatched = []
    skills_invoked = []

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
            if block.get("type") == "text":
                text = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(text)

                # Classification fields
                m = VALID_TYPES.search(clean)
                if m:
                    last_type = m.group(1)
                    # Reset ALL state per new classification
                    last_domain = None
                    last_must_dispatch = None
                    last_implies = None
                    agents_dispatched = []
                    skills_invoked = []

                    # IMPLIES (case-insensitive)
                    im = re.search(r'IMPLIES:\s*(.+)', clean, re.IGNORECASE)
                    if im:
                        last_implies = im.group(1).strip()[:200]  # Cap at 200 chars

                    # Domain (case-insensitive)
                    dm = re.search(r'DOMAIN:\s*(.+)', clean, re.IGNORECASE)
                    if dm:
                        last_domain = dm.group(1).strip()

                    # Must dispatch (multiline-aware, case-insensitive)
                    md = re.search(
                        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
                        clean,
                        re.DOTALL | re.IGNORECASE
                    )
                    if md:
                        raw = md.group(1).strip().strip('`')
                        raw = re.sub(r'\s+', ' ', raw)
                        if raw.lower().startswith("none") or raw.lower().startswith("n/a"):
                            last_must_dispatch = "none"
                        else:
                            last_must_dispatch = raw

            # Track dispatches after classification
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}

                if name == "Agent":
                    agent_type = inp.get("subagent_type") or inp.get("description") or "unknown"
                    agents_dispatched.append(agent_type)
                elif name == "Skill":
                    skill = inp.get("skill") or "unknown"
                    skills_invoked.append(skill)

    # Only log if we found a classification this turn
    if not last_type:
        return

    # Extract session ID from transcript filename
    session_id = os.path.splitext(os.path.basename(transcript_path))[0]

    log_entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": session_id[:12],
        "type": last_type,
        "implies": last_implies,
        "domain": last_domain,
        "must_dispatch": last_must_dispatch,
        "agents": agents_dispatched,
        "skills": skills_invoked,
        "agent_count": len(agents_dispatched),
        "skill_count": len(skills_invoked),
    }

    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        pass  # Don't crash on write failure


if __name__ == "__main__":
    main()
