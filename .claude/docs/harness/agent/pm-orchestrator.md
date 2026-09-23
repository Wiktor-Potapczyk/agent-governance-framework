---
component: "pm-orchestrator"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: pm-orchestrator

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/pm-orchestrator.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/pm/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches pm
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Project management orchestrator.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The mandatory PM agent: CLAUDE.md requires a pm-orchestrator dispatch for every non-Quick task, and the /pm skill's dispatch table routes checkpoints to it (page Reachability). Its frontmatter tells the orchestrator to invoke it at session start, between increments, at checkpoints, and for strategic project decisions (.claude/agents/pm-orchestrator.md:3). It owns PROJECT.md, STATE.md, and task_plan.md (.claude/agents/pm-orchestrator.md:12) and delegates work rather than executing it (.claude/agents/pm-orchestrator.md:17).

Tool surface: Read, Write, Edit, Grep, Glob, Bash (.claude/agents/pm-orchestrator.md:5). Every invocation must Read the three project files as source of truth (.claude/agents/pm-orchestrator.md:22) and report phase, active tasks, blockers, next action, and the Q7 parallel-runnability fields (.claude/agents/pm-orchestrator.md:25). Checkpoints must answer the five questions and produce the re-ranked next-3-tickets block from the live task_plan.md, not conversation memory (.claude/agents/pm-orchestrator.md:54, .claude/agents/pm-orchestrator.md:82).

Two in-file gates check its output: a checkpoint missing the re-rank block is incomplete and must be re-run (.claude/agents/pm-orchestrator.md:69), and the FORMAT contract states that a prose-only response with no headers, bullets, tables, or fences is rejected by the subagent quality gate (.claude/agents/pm-orchestrator.md:154). Outside the file, the dispatch-compliance Stop hook rejects an inline PM report that has no matching agent dispatch (CLAUDE.md rule F-2).
<!-- PROSE:END -->
