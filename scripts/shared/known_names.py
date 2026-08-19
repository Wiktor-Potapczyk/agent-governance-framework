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

# Canonical set: 93 entries
KNOWN_DISPATCH_NAMES = {
    # Agents (from .claude/agents/)
    "adversarial-reviewer", "api-designer", "api-security-audit", "architect-review", "architect-reviewer",
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect",
    "n8n-reviewer", "n8n-workflow-architect", "n8n-workflow-builder",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper",
    # Skills (from .claude/skills/): only process/governance skills likely in MUST DISPATCH
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
    # Plugin agents (defect 5, 2026-08-07): enumerated from registry.json's
    # `agents` dict, every entry whose `source` starts with "plugin:" (54
    # names: academic-research-skills 36 + claude-plugins-official 18).
    # Without these, MUST DISPATCH text naming a plugin agent (e.g.
    # "pr-review-toolkit:silent-failure-hunter") was invisible to this
    # parser's compliance extraction: the vocabulary only knew vault-local
    # agents/skills. registry.json is READ-ONLY input here, never edited.
    # Prune follow-up (post-review, 2026-08-07): 7 of the 54 were bare or
    # near-bare common-English compounds ("analyzer", "compliance_agent")
    # that extract_dispatch_names could match inside ordinary prose,
    # producing a phantom DECLARED item unrelated to any real dispatch
    # intent. Dropped rather than kept namespace-qualified: the suffix
    # check below reuses this SAME set for both the bare-candidate test and
    # the post-colon suffix test, so a namespace-only bucket needs a second
    # set (out of scope for this fix) or a hardcoded "plugin:name" literal
    # whose namespace slug can't be verified from registry.json's
    # marketplace-level "source" field (compare "claude-plugins-official"
    # above with the real dispatch namespace "pr-review-toolkit" in the
    # silent-failure-hunter example). Dropped: analyzer, comparator,
    # compliance_agent, formatter_agent, grader, intake_agent,
    # monitoring_agent.
    "abstract_bilingual_agent", "agent-creator", "agent-sdk-verifier-py",
    "agent-sdk-verifier-ts", "argument_builder_agent",
    "atomic-explorer", "atomic-reviewer", "bibliography_agent",
    "citation_compliance_agent", "code-architect", "code-explorer",
    "code-reviewer", "collaboration_depth_agent", "comment-analyzer",
    "conversation-analyzer",
    "devils_advocate_agent", "devils_advocate_reviewer_agent", "domain_reviewer_agent",
    "draft_writer_agent", "editor_in_chief_agent", "editorial_synthesizer_agent",
    "eic_agent", "ethics_review_agent", "field_analyst_agent",
    "integrity_verification_agent", "literature_strategist_agent", "meta_analysis_agent",
    "methodology_reviewer_agent", "peer_reviewer_agent",
    "perspective_reviewer_agent", "pipeline_orchestrator_agent", "plugin-validator",
    "pr-test-analyzer", "report_compiler_agent", "research_architect_agent",
    "research_question_agent", "revision_coach_agent", "risk_of_bias_agent",
    "silent-failure-hunter", "skill-reviewer", "socratic_mentor_agent",
    "source_verification_agent", "state_tracker_agent", "structure_architect_agent",
    "synthesis_agent", "type-design-analyzer", "visualization_agent",
}

# Canonical SKILL_AGENT_ALIASES: maps skill/short names to allowed agent runtime names.
# Used by agent-dispatch-check.py and dispatch-compliance-check.py.
# governance-log.py does NOT use this (logging only, no alias resolution needed).
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
    # NOTE: process-research does NOT alias research-synthesizer/report-generator :
    # those are dispatched by research-orchestrator internally, not by the main session.
    # Direct dispatch of downstream agents without process-research is a process violation.
}
# NOTE: SKILL_AGENT_ALIASES values may include "architect-reviewer" which is
# also now in KNOWN_DISPATCH_NAMES. The alias model stays coherent: canonical
# lists architect-reviewer as a runtime name alongside the declared name.
