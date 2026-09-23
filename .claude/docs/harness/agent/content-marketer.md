---
component: "content-marketer"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: content-marketer

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/content-marketer.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose doc-consistency [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose repo-sync [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when marketing copy or external-audience content must be written: blog posts, case studies, white papers, award submissions, LinkedIn posts, or reports.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by discretionary Agent-tool dispatch when external-audience copy must be written: blog posts, case studies, white papers, award submissions, LinkedIn posts, or reports; it writes, it does not research (`.claude/agents/content-marketer.md:3`). No MUST DISPATCH row binds it; this page's Reachability line lists only the registry catalog.

Tool surface: Read, Write, Edit, Glob, Grep, WebFetch, WebSearch (`.claude/agents/content-marketer.md:4`); the web tools may only verify competitor positioning or a factual claim, never do primary research (`.claude/agents/content-marketer.md:22`).

Contract: never fabricate; data gaps are flagged in the draft as DATA NEEDED (`.claude/agents/content-marketer.md:10`). Format-specific rules govern award submissions, case studies, blog posts, and LinkedIn posts (`.claude/agents/content-marketer.md:16-20`), a pre-save check verifies no fabricated data, no cliches, every rubric dimension addressed, and word limits respected (`.claude/agents/content-marketer.md:22`), and output is saved under Projects/<name>/work/ with YAML frontmatter (`.claude/agents/content-marketer.md:24`). No output-checking hook is named in the definition.
<!-- PROSE:END -->
