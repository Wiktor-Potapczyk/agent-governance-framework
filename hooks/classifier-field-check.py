"""
Classifier Field Check - Stop Hook
Verifies that all mandatory classifier fields are present in the response.
Block: JSON { "decision": "block" } on stdout if fields are missing.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
- Case-insensitive field detection
"""

import sys
import json
import os
import re

# 200KB window — covers even 10+ agent outputs per turn
READ_BYTES = 204800


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

    # Read last 200KB
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Find the last assistant text block that contains TASK TYPE
    lines = tail.split("\n")
    last_classifier_text = None

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
                btext = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(btext)
                # Only match real classifications with valid type names (case-insensitive)
                if re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)', clean, re.IGNORECASE):
                    last_classifier_text = clean

    if not last_classifier_text:
        return

    # Check if it's Quick (case-insensitive)
    is_quick = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*Quick', last_classifier_text, re.IGNORECASE))

    # Check required fields (case-insensitive)
    has_implies = bool(re.search(r'IMPLIES:', last_classifier_text, re.IGNORECASE))
    has_type = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):', last_classifier_text, re.IGNORECASE))
    has_approach = bool(re.search(r'APPROACH:', last_classifier_text, re.IGNORECASE))
    has_missed = bool(re.search(r'MISSED:', last_classifier_text, re.IGNORECASE))
    has_must_dispatch = bool(re.search(r'MUST DISPATCH:', last_classifier_text, re.IGNORECASE))

    missing = []
    if not has_implies:
        missing.append("IMPLIES")
    if not has_type:
        missing.append("TASK TYPE")

    if not is_quick:
        if not has_approach:
            missing.append("APPROACH")
        if not has_missed:
            missing.append("MISSED")
        if not has_must_dispatch:
            missing.append("MUST DISPATCH")

    if missing:
        reason = f"INCOMPLETE CLASSIFICATION: Missing fields: {', '.join(missing)}. All classifier fields are mandatory. Re-classify with all fields before proceeding."
        block_json = json.dumps({"decision": "block", "reason": reason})
        print(block_json)
        # Log block event
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0][:12] if transcript_path else "unknown"
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "block", "hook": "classifier-field-check", "session": session_id, "missing": missing})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
