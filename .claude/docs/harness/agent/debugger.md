---
component: "debugger"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: debugger

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/debugger.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-analysis/DISPATCHES.json), `EVD-003` (.claude/workflows/process-analysis.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose n8n-review [unresolved: prose mention only]
  - inbound dispatches process-analysis
  - inbound invokes process-analysis
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-pentest [unresolved: prose mention only]
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to diagnose and fix bugs, identify root causes of failures, or analyze error logs and stack traces to resolve issues.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch to diagnose and fix bugs, identify root causes of failures, or analyze error logs and stack traces (`.claude/agents/debugger.md:3`); a MUST DISPATCH row binds it into the process-analysis skill (this page's Reachability line).

Tool surface: Read, Write, Edit, Bash, Glob, Grep (`.claude/agents/debugger.md:4`). Its fixed procedure: collect logs and reproduction steps, reproduce systematically, form hypotheses and isolate the root cause, verify the fix and side effects, then document prevention (`.claude/agents/debugger.md:10-15`).

The contract is its excellence criteria: root cause identified and clearly documented, fix implemented and validated, side effects verified, performance impact assessed, and knowledge captured to prevent recurrence (`.claude/agents/debugger.md:21`). No output-checking hook is named in the definition.
<!-- PROSE:END -->
