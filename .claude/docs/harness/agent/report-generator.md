---
component: "report-generator"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: report-generator

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/report-generator.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-002` (.claude/skills/process-research/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-003` (.claude/workflows/process-research.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound dispatches process-research
  - inbound invokes process-research
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to transform synthesized research findings into a comprehensive, well-structured final report.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The final step of the research pipeline: dispatched after synthesis to turn synthesized findings into the finished report (.claude/agents/report-generator.md:5). The process-analysis and process-research dispatch tables carry it, and both matching workflow scripts invoke it (page Reachability).

Tool surface: Read, Write, Edit on sonnet (.claude/agents/report-generator.md:3). The contract is a seven-part report structure from executive summary through references (.claude/agents/report-generator.md:19), markdown formatting standards with sequential numbered citations (.claude/agents/report-generator.md:58), and required inclusions on every output: citation numbering, a date stamp, and attribution to the research system (.claude/agents/report-generator.md:101).

Two in-file checks apply: the quality assurance checklist requires every claim to carry a supporting citation (.claude/agents/report-generator.md:76), and the mandatory AGENT OUTPUT METADATA block grades confidence and data quality on each response (.claude/agents/report-generator.md:110).
<!-- PROSE:END -->
