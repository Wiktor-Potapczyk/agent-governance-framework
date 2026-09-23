---
component: "research-orchestrator"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: research-orchestrator

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/research-orchestrator.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-research/DISPATCHES.json), `EVD-003` (.claude/workflows/process-research.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-research
  - inbound invokes process-research
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to coordinate a comprehensive research project that requires multiple specialized agents working in sequence.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Head of the research pipeline: CLAUDE.md admits the research agents via process-research only, and this agent coordinates the full workflow from query clarification through final report (.claude/agents/research-orchestrator.md:5). The process-research dispatch table and workflow script wire it in (page Reachability); the page's Usage line records one dispatch, now dormant.

Tool surface: Read, Write, Edit, Task, TodoWrite on sonnet (.claude/agents/research-orchestrator.md:3). The contract is a five-phase workflow: query analysis, invoking query-clarifier when the query is ambiguous (.claude/agents/research-orchestrator.md:21); planning; parallel research via research-analyst and technical-researcher (.claude/agents/research-orchestrator.md:49); synthesis via research-synthesizer; and report generation via report-generator (.claude/agents/research-orchestrator.md:37). TodoWrite must track the phase checklist (.claude/agents/research-orchestrator.md:67).

Quality gates in the source require validating each agent's output before proceeding (.claude/agents/research-orchestrator.md:76) and allow one retry with refined input when an agent fails (.claude/agents/research-orchestrator.md:61). The mandatory AGENT OUTPUT METADATA block closes every response (.claude/agents/research-orchestrator.md:82).
<!-- PROSE:END -->
