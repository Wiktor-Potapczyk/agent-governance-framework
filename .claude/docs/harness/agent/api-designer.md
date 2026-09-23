---
component: "api-designer"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: api-designer

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/api-designer.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound dispatches process-build
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when designing new APIs, creating API specifications, or refactoring existing API architecture for scalability and developer experience.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch; MUST DISPATCH rows bind it into the process-analysis and process-build skills (this page's Reachability line). The firing condition is designing new APIs, writing API specifications, or refactoring existing API architecture for scalability and developer experience (`.claude/agents/api-designer.md:3`).

Tool surface: Read, Write, Edit, Bash, Glob, Grep (`.claude/agents/api-designer.md:4`). It works through three fixed phases: domain analysis, then API specification, then developer-experience optimization (`.claude/agents/api-designer.md:97-151`).

The contract is a complete API design: the checklist requires a finished OpenAPI 3.1 specification, consistent naming, comprehensive error responses, correct pagination, rate limiting, and defined authentication patterns (`.claude/agents/api-designer.md:17-25`). No output-checking enforcement is named in the definition; the checklist is the contract.
<!-- PROSE:END -->
