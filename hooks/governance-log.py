"""
Governance Log - Stop Hook
Captures classification, dispatch, and agent activity per response.
Appends one JSON line to governance-log.jsonl per response.
Does NOT block — logging only.

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

# 200KB window — covers even 10+ agent outputs per turn
READ_BYTES = 204800

VALID_TYPES = re.compile(
    r'(?:TASK TYPE|CLASSIFICATION):\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)',
    re.IGNORECASE
)

# Field labels used as delimiters for multiline capture
FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'

# Known agent and skill names for must_dispatch extraction (P0 fix 2026-04-09)
# Must_dispatch raw text often contains trailing reasoning after the comma-separated
# names. This set filters to only valid names, discarding garbage tokens.
KNOWN_DISPATCH_NAMES = {
    # Agents (from .claude/agents/)
    "adversarial-reviewer", "api-designer", "api-security-audit",
    "architect-review",  # declared name (MUST DISPATCH). Runtime name = "architect-reviewer" (via SKILL_AGENT_ALIASES)
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect", "n8n-reviewer",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper", "workflow-orchestrator",
    # Skills (from .claude/skills/) — only process/governance skills likely in MUST DISPATCH
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
}


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from a must_dispatch raw string.

    The classifier often appends reasoning text after the comma-separated names:
      'process-qa, pm Let me break down...'
    This function splits on commas and whitespace, matches each token against
    KNOWN_DISPATCH_NAMES, and returns only the valid names as a clean comma-separated string.
    """
    if not raw_text:
        return None
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return "none"

    # Split on commas first, then check each segment
    found = []
    for segment in raw_text.split(","):
        segment = segment.strip()
        # The name might be followed by reasoning text — try matching the first word(s)
        # that form a known name (handles multi-word like "architect-review")
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break

    return ", ".join(found) if found else None


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

    # M6 fix (2026-04-13): Log blocked turns with blocked_turn=true instead of skipping.
    # Previously returned early, causing blocked turns to have no rich governance-log entry.
    is_blocked_turn = bool(payload.get("stop_hook_active"))

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
                        last_must_dispatch = extract_dispatch_names(raw)

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
        "schema": 2,  # P1-E: schema version field (2026-04-09)
        "session": session_id,  # Full UUID (P1-D fix 2026-04-09)
        "type": last_type,
        "implies": last_implies,
        "domain": last_domain,
        "must_dispatch": last_must_dispatch,
        "agents": agents_dispatched,
        "skills": skills_invoked,
        "agent_count": len(agents_dispatched),
        "skill_count": len(skills_invoked),
        "blocked_turn": is_blocked_turn,  # M6 fix (2026-04-13)
    }

    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        pass  # Don't crash on write failure


if __name__ == "__main__":
    main()
