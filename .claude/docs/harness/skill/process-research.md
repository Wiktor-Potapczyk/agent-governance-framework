---
component: "process-research"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-research

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-research`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-planning/DISPATCHES.json), `EVD-003` (.claude/workflows/process-research.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound dispatches process-planning
  - inbound invokes process-research
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - inbound mentioned_in_prose verification-gated-research [unresolved: prose mention only]
  - outbound mentions_in_prose architect-loop [unresolved: prose mention only]
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound mentions_in_prose process-analysis [unresolved: prose mention only]
  - outbound mentions_in_prose process-planning [unresolved: prose mention only]
  - outbound dispatches report-generator
  - outbound dispatches research-analyst
  - outbound dispatches research-orchestrator
  - outbound dispatches research-synthesizer
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
  - outbound dispatches technical-researcher
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Research process template. Follow this procedure for all Research-type tasks after task-classifier routes here. Covers direct delegation and Ralph Loop paths. Use-when: Task-classifier returned `TASK TYPE: Research` or named a Research compound

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool after task-classifier returns TASK TYPE Research or names a Research compound (`.claude/skills/process-research/SKILL.md:16`, line 20). Non-Quick execution calls the Workflow tool with `.claude/workflows/process-research.js`: scope, path classification, research agents, synthesis, report-generator, quality gate (line 10). When the scope agent sets `ralph_loop_indicated`, the workflow HALTs and hands back so the main session can run `architect-loop`, then re-invoke the workflow with the loop findings (line 12); the prose is the fallback path (line 14).

The skill's surface is agent dispatch: research-analyst for web and market sources, technical-researcher for repos and technical docs, research-orchestrator for complex work with 4+ sub-questions (`.claude/skills/process-research/SKILL.md:80-85`); research-synthesizer is mandatory when two or more gatherers ran (line 96); report-generator writes the final deliverable to disk (lines 107-114). Downstream researchers are never dispatched directly from the main session (line 34).

Contractually it emits a RESEARCH SCOPE block up front (`.claude/skills/process-research/SKILL.md:42-48`) and produces a deliverable at the scope's output path that passes the Step 6 checklist (lines 118-123). Skipping mandatory synthesis is a process violation caught by the Stop hook (line 96); `DISPATCHES.json` remains the read-only H11 verification source (line 14).
<!-- PROSE:END -->
