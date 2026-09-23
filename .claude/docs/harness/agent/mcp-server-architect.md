---
component: "mcp-server-architect"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: mcp-server-architect

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/mcp-server-architect.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-002` (.claude/skills/process-planning/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound dispatches process-planning
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

MCP server architecture and implementation specialist.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch. The process-build and process-planning skills bind it through their MCP-domain dispatch rows (the page's Reachability line names both DISPATCHES.json files). Its frontmatter marks it for proactive use on MCP server design, transport layers, tool definitions, completion support, and protocol compliance (.claude/agents/mcp-server-architect.md:3), and it runs on sonnet (.claude/agents/mcp-server-architect.md:5).

Tool surface: Read, Write, Edit, Bash (.claude/agents/mcp-server-architect.md:4). The contract is a seven-step implementation approach, from requirements analysis through documentation (.claude/agents/mcp-server-architect.md:45), ending in complete, production-ready MCP server implementations rather than sketches (.claude/agents/mcp-server-architect.md:74).

The definition declares no structured output or metadata block; the only in-file check on its output is the Anti-Sycophancy stance section (.claude/agents/mcp-server-architect.md:76). The governance log records zero dispatches (page Usage line), so no runtime output exists to audit.
<!-- PROSE:END -->
