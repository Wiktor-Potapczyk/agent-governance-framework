---
component: "mcp-circuit-breaker-record"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: mcp-circuit-breaker-record

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/mcp-circuit-breaker-record.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

mcp-circuit-breaker-record.py — PostToolUse half of the MCP circuit breaker.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The PostToolUse half of the MCP circuit breaker, registered under the `mcp__.*` matcher. It classifies each MCP `tool_response` as failure, success, or unknown, using the `is_error` flag, non-empty error fields, an "error"/"MCP error" text head, or a missing response entirely (`.claude/hooks/mcp-circuit-breaker-record.py:73`).

A failure appends an ISO timestamp to the server's `failures` list in `_state/mcp-circuit-breaker.json`, capped at 50 entries (`.claude/hooks/mcp-circuit-breaker-record.py:157`, `.claude/hooks/mcp-circuit-breaker-record.py:160`); a success clears the failure list and stamps `last_success_at`, but deliberately never clears `tripped_at` (`.claude/hooks/mcp-circuit-breaker-record.py:167`, `.claude/hooks/mcp-circuit-breaker-record.py:17`). An unknown verdict changes nothing (`.claude/hooks/mcp-circuit-breaker-record.py:169`).

It prints nothing to stdout. The only telemetry is a `log_fire` record on the two state transitions that carry signal, a new failure and a recovery; a steady stream of healthy calls stays silent by design (`.claude/hooks/mcp-circuit-breaker-record.py:151`, `.claude/hooks/mcp-circuit-breaker-record.py:162`, `.claude/hooks/mcp-circuit-breaker-record.py:166`). Exit code is 0 on every path (`.claude/hooks/mcp-circuit-breaker-record.py:20`).
<!-- PROSE:END -->
