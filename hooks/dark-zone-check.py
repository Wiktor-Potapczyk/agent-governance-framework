"""
Dark Zone Check - Stop Hook
Detects when agent output may have been ignored by the main session.
Logs warnings when agents were dispatched but their findings aren't referenced
in the final response. Does NOT block -- monitoring only.

The Dark Zone: agent output dispatched but not utilized. FM-2.5 in MAST taxonomy.
Every framework solves data AVAILABILITY. None solve UTILIZATION.
This hook makes non-utilization DETECTABLE.

Checks:
- If Agent tool was used, does the final response text reference agent output?
- Looks for citation patterns: "Per [agent-name]:", "agent found", "review identified"
- Counts agent dispatches vs references -- ratio logged for analysis

This is a MONITORING hook. It logs to governance-log.jsonl but does not block.
Blocking would be too aggressive -- not every agent dispatch needs explicit citation
(e.g., architect-review findings might be applied silently).
"""

import sys
import json
import os
import re

READ_BYTES = 204800


def strip_fences(text):
    """Remove markdown fenced code blocks to prevent false matches."""
    return re.sub(r'```[\s\S]*?```', '', text)


# Patterns that indicate agent output was utilized in the response
CITATION_PATTERNS = [
    r'Per\s+\[?[\w-]+\]?\s*:',           # Per [agent-name]: or Per agent-name:
    r'(?:agent|review|analysis)\s+(?:found|identified|reported|flagged|noted|confirmed)',
    r'(?:architect|prompt|research|technical|adversarial)[\w-]*\s+(?:review|analysis|findings)',
    r'(?:findings|results|output)\s+(?:from|of)\s+(?:the\s+)?[\w-]+\s+agent',
    r'(?:synthesiz|synthes)',              # synthesis/synthesized/synthesizer
    r'QA REPORT',                          # QA output reference
]


def count_citations(text):
    """Count how many citation-like patterns appear in text."""
    count = 0
    for pattern in CITATION_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        count += len(matches)
    return count


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

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    lines = tail.split("\n")

    # Track agents dispatched, text blocks, and file writes in this turn
    agents_dispatched = []
    response_texts = []
    files_written = 0
    found_classification = False

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
                clean = strip_fences(text)
                # Detect classification (resets per turn)
                if re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)', clean, re.IGNORECASE):
                    agents_dispatched = []
                    response_texts = []
                    found_classification = True
                response_texts.append(clean)

            elif block.get("type") == "tool_use":
                name = block.get("name", "")
                if name == "Agent":
                    inp = block.get("input", {})
                    if isinstance(inp, str):
                        try:
                            inp = json.loads(inp)
                        except (json.JSONDecodeError, TypeError):
                            inp = {}
                    agent_type = inp.get("subagent_type") or inp.get("description") or "unknown"
                    agents_dispatched.append(agent_type)
                elif name in ("Write", "Edit"):
                    files_written += 1

    # Only check if agents were actually dispatched
    if not agents_dispatched:
        return

    # Count citations in response text AFTER agent dispatches
    # Get text blocks that came after the last agent dispatch
    all_text = "\n".join(response_texts)
    citation_count = count_citations(all_text)

    # Calculate utilization
    agent_count = len(agents_dispatched)

    # Determine severity
    # File writes count as utilization -- agents that produce files are being used
    effective_citations = citation_count + files_written
    effective_ratio = effective_citations / agent_count if agent_count > 0 else 0

    if effective_citations == 0 and agent_count >= 1:
        severity = "high"  # Agents dispatched, zero references AND zero file writes
    elif effective_ratio < 0.5:
        severity = "medium"  # Some utilization but less than agent count
    else:
        severity = "low"  # Adequate utilization (citations + file writes)

    # Log to governance log (monitoring only)
    try:
        from datetime import datetime
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
        session_id = os.path.splitext(os.path.basename(transcript_path))[0][:12]
        log_entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": "dark-zone",
            "hook": "dark-zone-check",
            "session": session_id,
            "agents": agents_dispatched,
            "agent_count": agent_count,
            "citation_count": citation_count,
            "files_written": files_written,
            "ratio": round(effective_ratio, 2),
            "severity": severity,
        })
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass

    # No blocking -- monitoring only
    # Future: could inject additionalContext warning when severity=high


if __name__ == "__main__":
    main()
