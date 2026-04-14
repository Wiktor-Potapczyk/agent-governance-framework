"""
Agent Dispatch Check - PreToolUse Hook (matcher: Agent)
Validates that the agent being dispatched is in the MUST DISPATCH list.
If MUST DISPATCH is "none" or absent, allows any dispatch.
If MUST DISPATCH lists specific agents, only those are allowed.
Non-specialist dispatches (general-purpose, Explore) are always allowed.

P0 fix (2026-04-09): Use extract_dispatch_names to filter trailing reasoning
text from MUST DISPATCH. Previously used naive comma split which caused
false-positive DENIES on valid dispatches.
Window bump (2026-04-09): 80KB → 200KB to match other hardened hooks.
"""

import sys
import json
import os
import re


# 200KB window — matches other hardened hooks (agent-dispatch bump 2026-04-09)
READ_BYTES = 204800

# Agent types that are always allowed (infrastructure, not specialist routing)
ALWAYS_ALLOWED = {"general-purpose", "explore", "plan", "bash"}

# Skill/short-name → agent-name aliases (bug fix 2026-04-10)
# When a skill or short name appears in MUST DISPATCH, dispatching its
# underlying agent(s) should also be allowed. Previously the hook did an
# exact string match, which blocked legit dispatches like:
#   MUST DISPATCH: [pm] → dispatch pm-orchestrator → BLOCKED (false positive)
#   MUST DISPATCH: [architect-review] → dispatch architect-reviewer → BLOCKED
SKILL_AGENT_ALIASES = {
    # Atomic skill/name aliases
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    # process-research: Steps 3B (direct) dispatch these agents.
    # B1 fix (2026-04-13): research-synthesizer and report-generator added because
    # Step 3B runs without research-orchestrator. They are NOT dispatched by
    # the main session on the 3A (Ralph Loop) path.
    "process-research": {
        "research-orchestrator", "technical-researcher", "research-analyst",
        "research-synthesizer", "report-generator",
    },
    # process-analysis: routes to any specialist based on domain (Step 2 table)
    # S3 fix (2026-04-13): expanded from 2 to 10 agents per SKILL.md audit
    "process-analysis": {
        "architect-reviewer", "adversarial-reviewer",
        "prompt-engineer", "debugger", "api-designer",
        "data-engineer", "workflow-orchestrator", "api-security-audit",
        "research-synthesizer", "report-generator",
    },
    # process-planning: Step 2 (research), Step 3 (design), Step 4 (review)
    # S3 fix (2026-04-13): expanded from 2 to 9 agents per SKILL.md audit
    "process-planning": {
        "implementation-plan", "adversarial-reviewer", "architect-reviewer",
        "technical-researcher", "research-analyst", "api-designer",
        "llm-architect", "data-engineer", "prompt-engineer",
    },
    # process-build: Steps 2-5 per SKILL.md
    # S3 fix (2026-04-13): added prompt-engineer and debugger
    "process-build": {
        "blueprint-mode", "architect-reviewer", "implementation-plan",
        "prompt-engineer", "debugger",
    },
    # process-qa and process-pentest: debugger on failure
    "process-qa": {"debugger"},
    "process-pentest": {"debugger"},
    # architect-loop: Ralph Loop dispatches reviewers
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},
}

# Known agent/skill names — same set as governance-log.py and dispatch-compliance-check.py
# (P0 fix 2026-04-09). Filters must_dispatch raw text to valid names only,
# discarding trailing reasoning text that would otherwise cause false DENIES.
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


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from MUST DISPATCH raw text.
    Same logic as governance-log.py and dispatch-compliance-check.py.
    Returns list of valid names (empty list for none/n/a/empty)."""
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
    read_bytes = min(READ_BYTES, file_size)  # 200KB (bumped 2026-04-09)

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

        # Multiline MUST DISPATCH delimiter (B4 fix 2026-04-13)
        FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'

        message = entry.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                if valid_types.search(text):
                    # New classification resets
                    must_dispatch = []
                    # B4 fix (2026-04-13): multiline-aware capture using DOTALL
                    m = re.search(
                        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
                        text,
                        re.DOTALL | re.IGNORECASE
                    )
                    if m:
                        raw = re.sub(r'\s+', ' ', m.group(1).strip().strip('`'))
                        # P0 fix (2026-04-09): extract only known names,
                        # filter trailing reasoning text to prevent false DENIES
                        must_dispatch = extract_dispatch_names(raw)

    # If no MUST DISPATCH or it's empty/none, allow any agent
    if not must_dispatch:
        return

    # Expand must_dispatch with skill→agent aliases (bug fix 2026-04-10).
    # If user declared [pm, architect-review], the allowed set should also
    # include [pm-orchestrator, architect-reviewer] which are the agents
    # those skills/short-names actually dispatch.
    allowed = set(must_dispatch)
    for declared in list(must_dispatch):
        if declared in SKILL_AGENT_ALIASES:
            allowed.update(SKILL_AGENT_ALIASES[declared])

    # Check if this agent is in the MUST DISPATCH list (or aliased from it)
    if agent_type not in allowed:
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
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"  # Full UUID (P1-D fix 2026-04-09)
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "deny", "hook": "agent-dispatch-check", "session": session_id, "agent_type": agent_type, "must_dispatch": must_dispatch, "schema": 2})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        return

    # Agent is in the list — allow
    return


if __name__ == "__main__":
    main()
