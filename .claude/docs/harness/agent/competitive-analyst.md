---
component: "competitive-analyst"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: competitive-analyst

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/competitive-analyst.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent to apply formal competitive frameworks (SWOT, feature matrices, Porter's Five Forces, pricing grids, positioning maps) to pre-gathered research data and produce strategic recommendations.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by discretionary Agent-tool dispatch in a sequential handoff: research-orchestrator or research-analyst collects raw facts with source URLs first, then this agent applies frameworks to that material (`.claude/agents/competitive-analyst.md:10`). The firing condition is applying formal competitive frameworks (SWOT, feature matrices, Porter's Five Forces, pricing grids, positioning maps) to pre-gathered research data (`.claude/agents/competitive-analyst.md:3`). No MUST DISPATCH row binds it; this page's Reachability line lists only the registry catalog.

Tool surface: Read, Write, Edit, Grep, Glob, WebFetch, WebSearch (`.claude/agents/competitive-analyst.md:4`). WebSearch and WebFetch are limited to filling specific gaps identified during analysis, and every gap-fill must be flagged as such (`.claude/agents/competitive-analyst.md:10`).

Contract: every matrix cell and SWOT quadrant carries specific evidence, missing data is marked with an explicit NO DATA tag rather than invented, each framework output carries a High/Medium/Low confidence label, and the deliverable is 3 to 5 ranked recommendations or a precise gap report, saved under Projects/<name>/work/ with YAML frontmatter and wiki-links (`.claude/agents/competitive-analyst.md:12-20`).
<!-- PROSE:END -->
