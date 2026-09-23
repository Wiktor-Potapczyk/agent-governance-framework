---
component: "data-engineer"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: data-engineer

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/data-engineer.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-002` (.claude/skills/process-planning/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound dispatches process-build
  - inbound dispatches process-planning
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to design, build, or optimize data pipelines, ETL/ELT processes, and data infrastructure.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch for designing, building, or optimizing data pipelines, ETL/ELT processes, and data infrastructure (`.claude/agents/data-engineer.md:3`); MUST DISPATCH rows bind it into the process-analysis, process-build, and process-planning skills (this page's Reachability line).

Tool surface: Read, Write, Edit, Bash, Glob, Grep (`.claude/agents/data-engineer.md:4`). On invocation it queries for data requirements, reviews existing infrastructure, and analyzes performance and cost optimization opportunities before implementing (`.claude/agents/data-engineer.md:12`).

The contract is robust pipeline work with error handling, quality checks, incremental processing, and monitoring, optimized against named targets: 99.9 percent pipeline SLA, data freshness under 1 hour, zero data loss, and cost per TB reduction (`.claude/agents/data-engineer.md:16`). No fixed report format or output-checking hook is named in the definition.
<!-- PROSE:END -->
