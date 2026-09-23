---
component: "powershell-7-expert"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: powershell-7-expert

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/powershell-7-expert.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when building cross-platform cloud automation scripts, Azure infrastructure orchestration, or CI/CD pipelines requiring PowerShell 7+ with modern .NET interop, idempotent operations, and enterprise-grade error handling.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch; the process-build dispatch table lists it (page Reachability). The frontmatter scopes it to cross-platform cloud automation, Azure orchestration, and CI/CD pipelines on PowerShell 7+ (.claude/agents/powershell-7-expert.md:3). The page's Usage line records zero dispatches.

Tool surface: Read, Write, Edit, Bash, Glob, Grep on sonnet (.claude/agents/powershell-7-expert.md:4). The contract is checklist-driven: scripts must satisfy the Script Quality Checklist, including -WhatIf and -Confirm support on state changes and CI-ready non-interactive output (.claude/agents/powershell-7-expert.md:34), and cloud work must pass the Cloud Automation Checklist for subscription context, auth model, and secret handling (.claude/agents/powershell-7-expert.md:41).

No structured output or metadata block exists in the source; the Anti-Sycophancy section is the only in-file check on what it returns (.claude/agents/powershell-7-expert.md:53).
<!-- PROSE:END -->
