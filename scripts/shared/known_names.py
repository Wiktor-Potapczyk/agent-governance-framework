"""
Canonical KNOWN_DISPATCH_NAMES and SKILL_AGENT_ALIASES — single source of truth.

KNOWN_DISPATCH_NAMES: All agent/skill names that can appear in MUST DISPATCH fields.
SKILL_AGENT_ALIASES: Maps skill/short names to the set of agent runtime names they
may dispatch. Used by agent-dispatch-check.py (PreToolUse) and dispatch-compliance-check.py
(Stop) to allow alias-based dispatch matching.

Used by:
- governance-log.py (extract_dispatch_names for classification entries)
- dispatch-compliance-check.py (extract_dispatch_names + alias resolution)
- agent-dispatch-check.py (extract_dispatch_names + alias resolution)
- Iteration 2 analytics scripts (unused resource detection, session-summary.py)

The 3 hook files maintain their own copies for self-containment (CC hooks must
be standalone). The drift guard test (test_known_dispatch_names_drift.py) verifies
all copies match this canonical set.

When adding new agents, skills, or aliases:
1. Add to this file first
2. Add to all 3 hook files (or 2 for SKILL_AGENT_ALIASES — governance-log.py does not use it)
3. Run test_known_dispatch_names_drift.py to confirm consistency
"""

# Canonical set — 44 entries (30 agents + 14 skills)
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

# Canonical SKILL_AGENT_ALIASES — maps skill/short names to allowed agent runtime names.
# Used by agent-dispatch-check.py and dispatch-compliance-check.py.
# governance-log.py does NOT use this (logging only, no alias resolution needed).
SKILL_AGENT_ALIASES = {
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    "process-research": {
        "research-orchestrator", "technical-researcher", "research-analyst",
        "research-synthesizer", "report-generator",
    },
    "process-analysis": {
        "architect-reviewer", "adversarial-reviewer",
        "prompt-engineer", "debugger", "api-designer",
        "data-engineer", "workflow-orchestrator", "api-security-audit",
        "research-synthesizer", "report-generator",
    },
    "process-planning": {
        "implementation-plan", "adversarial-reviewer", "architect-reviewer",
        "technical-researcher", "research-analyst", "api-designer",
        "llm-architect", "data-engineer", "prompt-engineer",
    },
    "process-build": {
        "blueprint-mode", "architect-reviewer", "implementation-plan",
        "prompt-engineer", "debugger",
    },
    "process-qa": {"debugger"},
    "process-pentest": {"debugger"},
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},
}
