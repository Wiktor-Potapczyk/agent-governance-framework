---
component: "research-analyst"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: research-analyst

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/research-analyst.md`
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

Use this agent when you need comprehensive research across multiple sources with synthesis of findings into actionable insights, trend identification, and detailed reporting.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The research pipeline's breadth specialist: research-orchestrator deploys it for web research, trends, and multi-source synthesis, and the process-research dispatch table plus the process-research workflow script wire it in (page Reachability). Its description scopes it to research across multiple sources synthesized into actionable insights and trend identification (.claude/agents/research-analyst.md:3).

Tool surface: Read, Write, Edit, Grep, Glob, WebFetch, WebSearch on sonnet (.claude/agents/research-analyst.md:4), making it one of the few vault agents with live web access. The contract runs three phases, planning, implementation, and quality assurance (.claude/agents/research-analyst.md:20), with source-credibility evaluation and cross-referencing required during implementation (.claude/agents/research-analyst.md:24).

Output must include executive summaries, detailed findings with source citations, methodology documentation, and recommendations (.claude/agents/research-analyst.md:30), and every response ends with the mandatory AGENT OUTPUT METADATA block whose rules tie high confidence to cited sources (.claude/agents/research-analyst.md:39, .claude/agents/research-analyst.md:54).
<!-- PROSE:END -->
