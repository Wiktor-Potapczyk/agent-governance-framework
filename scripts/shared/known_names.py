"""
Canonical KNOWN_DISPATCH_NAMES set — single source of truth.

All agent/skill names that can appear in MUST DISPATCH fields. Used by:
- governance-log.py (extract_dispatch_names for classification entries)
- dispatch-compliance-check.py (extract_dispatch_names for compliance checks)
- agent-dispatch-check.py (extract_dispatch_names for PreToolUse agent validation)
- Iteration 2 analytics scripts (unused resource detection, session-summary.py)

The 3 hook files maintain their own copies for self-containment (CC hooks must
be standalone). The drift guard test (test_known_dispatch_names_drift.py) verifies
all copies match this canonical set.

When adding new agents or skills:
1. Add to this file first
2. Add to all 3 hook files
3. Run test_known_dispatch_names_drift.py to confirm consistency
"""

# Canonical set — 44 entries (30 agents + 14 skills)
KNOWN_DISPATCH_NAMES = {
    # Agents
    "adversarial-reviewer", "api-designer", "api-security-audit", "architect-review",
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
