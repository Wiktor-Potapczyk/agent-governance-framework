---
name: project_agent_refactor
description: Active refactor plan for all 13 Claude agents — routing, model assignments, prompt rewrites, review pipeline
type: project
---

## Agent Refactor Project

**Plan file:** `.claude/AGENT_REFACTOR_PLAN.md`
**Status:** Step 1 complete (plan written). Steps 2-6 pending.

**Pipeline:**
1. planner — DONE (this file)
2. workflow-orchestrator — design routing topology → `.claude/agent-refactor/routing-topology.md`
3. llm-architect — assign model per agent → `.claude/agent-refactor/model-assignments.md`
4. prompt-engineer — rewrite all 13 files to: trigger-based description, NOT-for exclusion, numbered steps, least-privilege tools, under 60 lines
5. reviewer — validate each file, reject back to prompt-engineer if any criterion fails
6. vault-keeper — write approved files to `.claude/agents/`, rewrite CLAUDE.md to under 200 lines

**Key decisions:**
- reviewer stays Opus (quality gate)
- prompt-engineer downgraded Opus → Sonnet
- vault-keeper downgraded Sonnet → Haiku
- builder/planner: inherit → sonnet
- Intermediate artifacts go to `.claude/agent-refactor/` staging area

**Identified overlaps to resolve in Step 2:**
- builder / api-expert / data-engineer
- researcher / competitive-analyst (WebSearch scope)
- llm-architect / prompt-engineer (prompt engineering section duplication)
