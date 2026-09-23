---
component: "research-synthesizer"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: research-synthesizer

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/research-synthesizer.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-002` (.claude/skills/process-research/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-003` (.claude/workflows/process-research.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound dispatches process-research
  - inbound invokes process-research
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to consolidate and synthesize findings from multiple research sources or specialist researchers into a unified, comprehensive analysis.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The pipeline's consolidation step: dispatched after specialist researchers return, to merge their findings into one analysis without losing information (.claude/agents/research-synthesizer.md:5). The process-analysis and process-research dispatch tables carry it, and both workflow scripts invoke it (page Reachability).

Tool surface: Read, Write, Edit on sonnet (.claude/agents/research-synthesizer.md:3). Its six responsibilities run from merging findings through preserving all unique citations (.claude/agents/research-synthesizer.md:10), under key principles that forbid cherry-picking and require contradictions to stay visible (.claude/agents/research-synthesizer.md:26).

Output is contracted to a JSON structure covering major_themes, unique_insights, contradictions, evidence_assessment, knowledge_gaps, all_citations, and a synthesis_summary (.claude/agents/research-synthesizer.md:41), plus the mandatory AGENT OUTPUT METADATA block (.claude/agents/research-synthesizer.md:111).
<!-- PROSE:END -->
