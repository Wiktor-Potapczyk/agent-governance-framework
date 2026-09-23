---
component: "mcp-circuit-breaker"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: mcp-circuit-breaker

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/mcp-circuit-breaker.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

mcp-circuit-breaker.py — PreToolUse guard for MCP tool calls (ECC-LEARN-E1).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The PreToolUse half of the MCP circuit breaker, registered under the `mcp__.*` matcher. It extracts the server segment from the `mcp__<server>__<tool>` name (`.claude/hooks/mcp-circuit-breaker.py:87`) and reads that server's failure state from `.claude/hooks/_state/mcp-circuit-breaker.json` (`.claude/hooks/mcp-circuit-breaker.py:69`), the file the PostToolUse record half maintains.

After pruning failures older than the 600-second window (`.claude/hooks/mcp-circuit-breaker.py:120`), the breaker counts as tripped when a `tripped_at` stamp is still inside the 1800-second cooldown, or the window holds 3 or more failures (`.claude/hooks/mcp-circuit-breaker.py:133`, `.claude/hooks/mcp-circuit-breaker.py:61`). A tripped breaker prints `permissionDecision: "deny"` with the failure count, remaining cooldown, and recovery instructions (`.claude/hooks/mcp-circuit-breaker.py:145`), and logs `breaker_blocked` toward governance-log.jsonl (`.claude/hooks/mcp-circuit-breaker.py:250`).

Two env escape hatches exist: `MCP_HEALTH_FAIL_OPEN=1` lets a tripped call through (`.claude/hooks/mcp-circuit-breaker.py:196`, `.claude/hooks/mcp-circuit-breaker.py:235`), and `MCP_BREAKER_RESET=<server>` clears that server's breaker on its next call (`.claude/hooks/mcp-circuit-breaker.py:201`, `.claude/hooks/mcp-circuit-breaker.py:223`). Every path exits 0; a parse failure fails open (`.claude/hooks/mcp-circuit-breaker.py:210`).
<!-- PROSE:END -->
