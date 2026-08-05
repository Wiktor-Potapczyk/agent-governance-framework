"""
Canonical KNOWN_DISPATCH_NAMES and SKILL_AGENT_ALIASES: single source of truth.

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
2. Add to all 3 hook files (or 2 for SKILL_AGENT_ALIASES: governance-log.py does not use it)
3. Run test_known_dispatch_names_drift.py to confirm consistency
"""

# Canonical set: 46 entries (40 agents + 6 skills)
KNOWN_DISPATCH_NAMES = {
    "adversarial-reviewer",
    "api-designer",
    "api-security-audit",
    "architect-loop",
    "architect-review",
    "architect-reviewer",
    "blueprint-mode",
    "competitive-analyst",
    "content-marketer",
    "data-engineer",
    "debugger",
    "ensemble",
    "git-flow-manager",
    "implementation-plan",
    "index",
    "llm-architect",
    "maintain",
    "mcp-developer",
    "mcp-registry-navigator",
    "mcp-server-architect",
    "n8n-reviewer",
    "n8n-workflow-architect",
    "n8n-workflow-builder",
    "nosql-specialist",
    "pm",
    "pm-orchestrator",
    "postgres-pro",
    "powershell-7-expert",
    "process-analysis",
    "process-build",
    "process-pentest",
    "process-planning",
    "process-qa",
    "process-research",
    "prompt-engineer",
    "query-clarifier",
    "report-generator",
    "research-analyst",
    "research-coordinator",
    "research-orchestrator",
    "research-synthesizer",
    "save",
    "task-classifier",
    "technical-researcher",
    "vault-keeper",
    "verify",
}

# Canonical SKILL_AGENT_ALIASES: maps skill/short names to allowed agent runtime names.
# Used by agent-dispatch-check.py and dispatch-compliance-check.py.
# governance-log.py does NOT use this (logging only, no alias resolution needed).
SKILL_AGENT_ALIASES = {
    "architect-loop": {"adversarial-reviewer", "architect-reviewer"},
    "architect-review": {"architect-reviewer"},
    "pm": {"pm-orchestrator"},
    "process-analysis": {"adversarial-reviewer", "architect-reviewer"},
    "process-build": {"architect-reviewer", "blueprint-mode", "implementation-plan"},
    "process-pentest": {"debugger"},
    "process-planning": {"adversarial-reviewer", "implementation-plan"},
    "process-qa": {"debugger"},
    "process-research": {"research-analyst", "research-orchestrator", "technical-researcher"},
}
# NOTE: SKILL_AGENT_ALIASES values may include "architect-reviewer" which is
# also now in KNOWN_DISPATCH_NAMES. The alias model stays coherent: canonical
# lists architect-reviewer as a runtime name alongside the declared name.
