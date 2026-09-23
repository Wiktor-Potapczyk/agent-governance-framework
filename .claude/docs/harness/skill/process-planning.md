---
component: "process-planning"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-planning

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-planning`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-planning.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound invokes process-planning
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound dispatches adversarial-reviewer
  - outbound dispatches architect-reviewer
  - outbound mentions_in_prose checkpoint [unresolved: prose mention only]
  - outbound dispatches data-engineer
  - outbound dispatches implementation-plan
  - outbound dispatches llm-architect
  - outbound mentions_in_prose mcp-developer [unresolved: prose mention only]
  - outbound dispatches mcp-server-architect
  - outbound mentions_in_prose pm [unresolved: prose mention only]
  - outbound mentions_in_prose pm-orchestrator [unresolved: prose mention only]
  - outbound mentions_in_prose process-build [unresolved: prose mention only]
  - outbound dispatches process-research
  - outbound mentions_in_prose process-research [unresolved: prose mention only]
  - outbound dispatches prompt-engineer
  - outbound mentions_in_prose report-generator [unresolved: prose mention only]
  - outbound mentions_in_prose research-analyst [unresolved: prose mention only]
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose technical-researcher [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Planning process template. Follow this procedure for all Planning-type tasks after task-classifier routes here. Covers architecture design, spec writing, and work sequencing.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Skill invocation after task-classifier returns TASK TYPE Planning (`.claude/skills/process-planning/SKILL.md:14`). Non-Quick execution goes through the Workflow tool with `.claude/workflows/process-planning.js`, whose script sequence is scope, optional research, implementation-plan, mandatory parallel review by architect-reviewer and adversarial-reviewer, a capped revise loop, and a quality gate (line 10); the prose remains the spec of record and the fallback path (line 12).

The tool surface is mostly dispatch: Read for STATE.md and PROJECT.md context (`.claude/skills/process-planning/SKILL.md:18`), the Skill tool to route any needed research through `process-research` (line 46), and Agent dispatches to implementation-plan (line 60), mcp-server-architect on MCP-domain plans (line 70), architect-reviewer (line 74), prompt-engineer when the plan contains LLM prompts (line 83), and adversarial-reviewer unconditionally since the 2026-06-11 workflow adoption (line 85).

Contractually it must emit a PLANNING SCOPE block (`.claude/skills/process-planning/SKILL.md:26-32`) and save a plan to `Projects/[Name]/work/` that passes the Step 6 checklist (lines 97-102). Skipping the mandatory review is a process violation caught by the Stop hook (line 74); STATE.md is owned by pm-orchestrator and is never written from this skill (line 112); `DISPATCHES.json` stays the read-only H11 verification source (line 12).
<!-- PROSE:END -->
