---
component: "mcp-developer"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: mcp-developer

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/mcp-developer.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-002` (.claude/skills/process-build/DISPATCHES.json), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound dispatches process-build
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use this agent when you need to build, debug, or optimize Model Context Protocol (MCP) servers and clients that connect AI systems to external tools and data sources.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached by Agent-tool dispatch for building, debugging, or optimizing MCP servers and clients (`.claude/agents/mcp-developer.md:3`); a MUST DISPATCH row binds it into the process-build skill for MCP-domain work (this page's Reachability line). The page's Usage line records no dispatch yet.

Tool surface: Read, Write, Edit, Bash, Glob, Grep (`.claude/agents/mcp-developer.md:4`). On invocation it gathers MCP requirements and integration needs, reviews existing server implementations and protocol compliance, then implements (`.claude/agents/mcp-developer.md:9-13`).

The contract is the core implementation bar: JSON-RPC 2.0 compliance, schema validation, transport optimization, security controls, comprehensive error handling, documentation, testing coverage above 90 percent, and performance benchmarking (`.claude/agents/mcp-developer.md:15`). No output-checking hook is named in the definition.
<!-- PROSE:END -->
