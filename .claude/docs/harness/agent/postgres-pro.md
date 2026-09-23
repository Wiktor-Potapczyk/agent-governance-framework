---
component: "postgres-pro"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: postgres-pro

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/postgres-pro.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose db-migration-plan [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when you need to optimize PostgreSQL performance, design high-availability replication, or troubleshoot database issues at scale.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch; the process-build dispatch table lists it and the db-migration-plan skill mentions it in prose (page Reachability and Edges). The frontmatter scopes it to PostgreSQL performance optimization, high-availability replication, backup strategy, and troubleshooting at scale (.claude/agents/postgres-pro.md:3).

Tool surface: Read, Write, Edit, Bash, Glob, Grep on sonnet (.claude/agents/postgres-pro.md:4). When invoked it follows a four-step protocol: query deployment context, review configuration and metrics, analyze bottlenecks, implement solutions (.claude/agents/postgres-pro.md:10), against explicit targets such as query performance under 50ms and replication lag under 500ms (.claude/agents/postgres-pro.md:16).

The definition declares no structured output or metadata block; the only in-file check on its output is the Anti-Sycophancy section (.claude/agents/postgres-pro.md:27).
<!-- PROSE:END -->
