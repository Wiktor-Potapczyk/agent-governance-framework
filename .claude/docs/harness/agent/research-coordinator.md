---
component: "research-coordinator"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: research-coordinator

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/research-coordinator.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to strategically plan and coordinate complex research tasks across multiple specialist researchers.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch only: page Reachability is registry-only and the Usage line records zero dispatches. Its description scopes it to strategic planning of complex research across multiple specialist researchers (.claude/agents/research-coordinator.md:5). Note: the specialists it plans for are academic-researcher, web-researcher, technical-researcher, and data-analyst (.claude/agents/research-coordinator.md:17); of these four, only technical-researcher exists in the vault's agent roster.

Tool surface: Read, Write, Edit, Task on sonnet (.claude/agents/research-coordinator.md:3); Task lets it dispatch researchers itself. Its planning process runs six steps, from complexity assessment (.claude/agents/research-coordinator.md:25) through quality assurance criteria (.claude/agents/research-coordinator.md:49).

The output contract is strict: it must emit a JSON plan following the exact strategy, iterations_planned, researcher_tasks, integration_plan, success_criteria, and contingency structure (.claude/agents/research-coordinator.md:61), and append the AGENT OUTPUT METADATA block (.claude/agents/research-coordinator.md:96).
<!-- PROSE:END -->
