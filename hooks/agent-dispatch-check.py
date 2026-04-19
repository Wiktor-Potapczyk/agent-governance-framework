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

# Process skills that legitimately route to multiple specialists not pre-enumerated
# in classifier MUST DISPATCH. When ANY of these appears in MUST DISPATCH, the main
# session is delegating routing to the skill; any agent in registry.json should be
# allowed through (2026-04-18 fix — architectural bug where allowlist was exclusive).
PROCESS_ROUTING_SKILLS = {
    "process-research", "process-analysis", "process-build",
    "process-planning", "process-qa", "process-pentest",
}

# Registry path — loaded lazily to list all valid agents (local + plugin)
REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "registry.json"
)


def load_registry_agents():
    """Return set of valid agent names from .claude/registry.json (lowercase).
    Registry schema: agents is a dict keyed by agent name.
    """
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        agents = data.get("agents", {})
        if isinstance(agents, dict):
            return {name.lower() for name in agents.keys() if name}
        # Fallback: list-of-dicts schema (legacy)
        if isinstance(agents, list):
            return {
                (a.get("name") or "").lower()
                for a in agents
                if isinstance(a, dict) and a.get("name")
            }
        return set()
    except Exception:
        return set()

# Skill/short-name → agent-name aliases (bug fix 2026-04-10)
# When a skill or short name appears in MUST DISPATCH, dispatching its
# underlying agent(s) should also be allowed. Previously the hook did an
# exact string match, which blocked legit dispatches like:
#   MUST DISPATCH: [pm] → dispatch pm-orchestrator → BLOCKED (false positive)
#   MUST DISPATCH: [architect-review] → dispatch architect-reviewer → BLOCKED
SKILL_AGENT_ALIASES = {
    # Skills that dispatch agents with different names
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    # Process skills dispatch their primary agents
    "process-planning": {"implementation-plan", "adversarial-reviewer"},
    "process-build": {"blueprint-mode", "architect-reviewer", "implementation-plan"},
    "process-research": {"research-orchestrator", "technical-researcher", "research-analyst"},
    "process-analysis": {"architect-reviewer", "adversarial-reviewer"},
    # PRE-I2-A (2026-04-12): 3 additional aliases from plan v2 audit
    "process-qa": {"debugger"},  # dispatched conditionally on QA failure
    "process-pentest": {"debugger"},  # pentest dispatches debugger on findings, not architect-reviewer (skill says "execute yourself")
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},  # Ralph Loop dispatches reviewers
    # NOTE: process-research does NOT alias research-synthesizer/report-generator —
    # those are dispatched by research-orchestrator internally, not by the main session.
    # Direct dispatch of downstream agents without process-research is a process violation.
}

# Known agent/skill names — same set as governance-log.py and dispatch-compliance-check.py
# (P0 fix 2026-04-09). Filters must_dispatch raw text to valid names only,
# discarding trailing reasoning text that would otherwise cause false DENIES.
KNOWN_DISPATCH_NAMES = {
    # Agents
    "adversarial-reviewer", "api-designer", "api-security-audit", "architect-review", "architect-reviewer",
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
        # B: conditional exemption — if MUST DISPATCH contains any process-* routing
        # skill, the session is legitimately delegating routing to the skill. Any
        # agent listed in registry.json is valid in that context.
        has_process_skill = any(d in PROCESS_ROUTING_SKILLS for d in must_dispatch)
        registry_agents = load_registry_agents() if has_process_skill else set()
        if has_process_skill and agent_type in registry_agents:
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "allow_process_skill_exemption",
                    "hook": "agent-dispatch-check",
                    "session": session_id,
                    "agent_type": agent_type,
                    "must_dispatch": must_dispatch,
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return  # Allowed via process-skill routing exemption

        # A: warn-downgrade — not blocked, but logged and surfaced to stderr.
        # Preserves observability of off-contract dispatches without breaking flow.
        # Original deny mode was too strict (2026-04-18 fix).
        reason = (
            f"AGENT DISPATCH (advisory): '{agent_type}' is not in MUST DISPATCH list "
            f"[{', '.join(must_dispatch)}] and no process-* skill is present to "
            f"authorize specialist routing. Logged for review."
        )
        print(reason, file=sys.stderr)
        # Log warn event (schema: event=warn, not deny)
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
            entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "warn",
                "hook": "agent-dispatch-check",
                "session": session_id,
                "agent_type": agent_type,
                "must_dispatch": must_dispatch,
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        return  # No deny — advisory only

    # Agent is in the list — allow
    return


if __name__ == "__main__":
    main()
