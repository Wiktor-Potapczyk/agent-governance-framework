---
component: "technical-researcher"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: technical-researcher

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/technical-researcher.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-research/DISPATCHES.json), `EVD-003` (.claude/workflows/process-research.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound dispatches process-research
  - inbound invokes process-research
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to analyze code repositories, technical documentation, implementation details, or evaluate technical solutions.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The research pipeline's code-and-docs specialist: research-orchestrator deploys it for repository and implementation analysis, and the process-research dispatch table plus workflow script wire it in (page Reachability). Its description scopes it to code repositories, technical documentation, API references, and evaluation of technical solutions (.claude/agents/technical-researcher.md:5).

Tool surface: Read, Write, Edit, WebSearch, WebFetch, Bash on sonnet (.claude/agents/technical-researcher.md:3), giving it live web access for repository research. The contract fixes both the citation format (.claude/agents/technical-researcher.md:61) and a JSON output covering search_summary, repositories with stats and code_quality grades, technical_insights, and implementation_recommendations (.claude/agents/technical-researcher.md:64).

Enforcement is in-file and doubled: an output_format block at the top declares the trailing output_metadata section MANDATORY on every response, even brief ones (.claude/agents/technical-researcher.md:11), and the closing rules bind confidence of 0.9 or higher to cited sources for all claims (.claude/agents/technical-researcher.md:120).
<!-- PROSE:END -->
