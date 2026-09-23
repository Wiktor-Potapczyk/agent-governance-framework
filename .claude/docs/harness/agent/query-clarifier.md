---
component: "query-clarifier"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: query-clarifier

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/query-clarifier.md`
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

Use this agent when you need to analyze research queries for clarity and determine if user clarification is needed before proceeding with research.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The research pipeline's entry gate: research-orchestrator's Phase 1 invokes it when a query is ambiguous or too broad, and its own description places it at the beginning of research workflows to test whether a query is specific and actionable (.claude/agents/query-clarifier.md:5). Page Reachability is registry-only and the Usage line records zero dispatches.

Tool surface: Read, Write, Edit on sonnet (.claude/agents/query-clarifier.md:3). It analyzes each query on five axes, from ambiguity through over-breadth (.claude/agents/query-clarifier.md:10), then applies a confidence-thresholded decision framework: proceed above 0.8, refine and proceed between 0.6 and 0.8, request clarification below 0.6 (.claude/agents/query-clarifier.md:17).

Output is doubly contracted: it must always return a valid JSON object with the exact needs_clarification, confidence_score, questions, refined_query, and focus_areas structure (.claude/agents/query-clarifier.md:30), and it must append the AGENT OUTPUT METADATA YAML block with honest confidence grading (.claude/agents/query-clarifier.md:77).
<!-- PROSE:END -->
