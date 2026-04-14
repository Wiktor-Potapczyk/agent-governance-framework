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

# Known agent/skill names — same set as governance-log.py (P0 fix 2026-04-09)
# Used to filter must_dispatch raw text to valid names only, discarding
# trailing reasoning text that would otherwise cause false-positive blocks.
KNOWN_DISPATCH_NAMES = {
    # Agents
    "adversarial-reviewer", "api-designer", "api-security-audit",
    "architect-review",  # declared name (MUST DISPATCH). Runtime name = "architect-reviewer" (via SKILL_AGENT_ALIASES)
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect", "n8n-reviewer",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper", "workflow-orchestrator",
    # Skills
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
}

# Skill/short-name → agent-name aliases (2026-04-12, coherence fix)
# Must match agent-dispatch-check.py SKILL_AGENT_ALIASES exactly.
# When a declared item in MUST DISPATCH is a skill name but the actual dispatch
# uses the agent's runtime name (e.g., "architect-review" declared but
# "architect-reviewer" dispatched), alias resolution prevents false blocks.
SKILL_AGENT_ALIASES = {
    # Atomic skill/name aliases
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    # process-research: B1 fix (2026-04-13) — added research-synthesizer, report-generator
    "process-research": {
        "research-orchestrator", "technical-researcher", "research-analyst",
        "research-synthesizer", "report-generator",
    },
    # process-analysis: S3 fix (2026-04-13) — expanded from 2 to 10 per SKILL.md
    "process-analysis": {
        "architect-reviewer", "adversarial-reviewer",
        "prompt-engineer", "debugger", "api-designer",
        "data-engineer", "workflow-orchestrator", "api-security-audit",
        "research-synthesizer", "report-generator",
    },
    # process-planning: S3 fix (2026-04-13) — expanded from 2 to 9 per SKILL.md
    "process-planning": {
        "implementation-plan", "adversarial-reviewer", "architect-reviewer",
        "technical-researcher", "research-analyst", "api-designer",
        "llm-architect", "data-engineer", "prompt-engineer",
    },
    # process-build: S3 fix (2026-04-13) — added prompt-engineer, debugger
    "process-build": {
        "blueprint-mode", "architect-reviewer", "implementation-plan",
        "prompt-engineer", "debugger",
    },
    "process-qa": {"debugger"},
    "process-pentest": {"debugger"},
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},
}


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from MUST DISPATCH raw text.
    Filters trailing reasoning text (P0 fix 2026-04-09)."""
    if not raw_text:
        return []
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return []

    found = []
    for segment in raw_text.split(","):
        segment = segment.strip()
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break
    return found


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
                # Bug fix (2026-04-10): strip_fences was removing the actual
                # classification block when output inside markdown fences.
                # Safe to skip: extract_dispatch_names (P0 fix) filters garbage,
                # and the code resets on each new classification block.
                clean = text
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
                        # P0 fix (2026-04-09): use extract_dispatch_names to filter
                        # trailing reasoning text. Previously split on commas naively,
                        # which included garbage tokens and caused false-positive blocks.
                        must_dispatch = extract_dispatch_names(raw)
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

    # Alias-aware missing check (2026-04-12 coherence fix):
    # A declared item is satisfied if either the item itself OR any of its
    # aliases are in the dispatched set. E.g., "architect-review" declared,
    # "architect-reviewer" dispatched → satisfied via alias.
    missing = []
    for item in must_dispatch:
        aliases = SKILL_AGENT_ALIASES.get(item, set())
        if item not in dispatched and not (aliases & dispatched):
            missing.append(item)

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
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"  # Full UUID (P1-D fix 2026-04-09)
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "block", "hook": "dispatch-compliance", "session": session_id, "declared": must_dispatch, "missing": missing, "schema": 2})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
    else:
        # P2-B (2026-04-09): Log pass event when all declared items are dispatched.
        # Required for DAR computation without relying on absence-of-block heuristic.
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
            entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "pass",
                "hook": "dispatch-compliance",
                "session": session_id,
                "declared": must_dispatch,
                "matched": sorted(dispatched & set(must_dispatch)),  # sorted for deterministic order
                "declared_count": len(must_dispatch),
                "matched_count": len([x for x in must_dispatch if x in dispatched]),
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
