---
component: "blueprint-mode"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: blueprint-mode

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/blueprint-mode.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Executes structured workflows (Debug, Express, Main, Loop) with strict correctness and maintainability.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch as a Build-domain executor; a MUST DISPATCH row binds it into the process-build skill (this page's Reachability line). Its mandatory first step is to select one of four workflows (Loop, Debug, Express, Main) and announce the choice without narration (`.claude/agents/blueprint-mode.md:14`, `.claude/agents/blueprint-mode.md:126-131`).

Tool surface: Read, Bash, Grep, Glob, Edit, Write (`.claude/agents/blueprint-mode.md:4`). Its tool policy requires parallelizing independent calls, waiting for results before the next step, and avoiding interactive commands (`.claude/agents/blueprint-mode.md:87-103`).

It must end with a Final Summary carrying Outstanding Issues, Next, and a COMPLETED / PARTIALLY COMPLETED / FAILED status (`.claude/agents/blueprint-mode.md:62-66`). The definition's own enforcement is the Self-Reflection gate: every rubric category must score above 8, failures create actionable issues, and after 3 unresolved iterations the task is marked FAILED (`.claude/agents/blueprint-mode.md:117-122`).
<!-- PROSE:END -->
