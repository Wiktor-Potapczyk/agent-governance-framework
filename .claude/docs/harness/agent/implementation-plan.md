---
component: "implementation-plan"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: implementation-plan

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/implementation-plan.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-002` (.claude/skills/process-planning/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound dispatches process-planning
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Generate an implementation plan for new features or refactoring existing code.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch as a planning-mode agent; MUST DISPATCH rows bind it into the process-build and process-planning skills (this page's Reachability line). It generates implementation plans executable by other AI systems or humans, and it must not make any code edits: plans only (`.claude/agents/implementation-plan.md:12`, `.claude/agents/implementation-plan.md:24`).

Tool surface: Read, Write, Edit, Grep, Glob, Bash (`.claude/agents/implementation-plan.md:4`); Write exists to save the plan file, named [purpose]-[component]-[version].md under a /plan/ directory (`.claude/agents/implementation-plan.md:49-54`).

Contract: plans must strictly follow the mandatory template (front matter with goal and status, phased GOAL/TASK tables, alternatives, dependencies, files, testing, risks), and the definition instructs agents to validate template compliance before execution (`.claude/agents/implementation-plan.md:57-59`). No external hook checks the output; the template is the contract.
<!-- PROSE:END -->
