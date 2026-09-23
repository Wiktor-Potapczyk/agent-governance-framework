---
component: "mcp-irreversible-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: mcp-irreversible-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/mcp-irreversible-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

mcp-irreversible-guard.py — PreToolUse guard for irreversible MCP tool calls.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PreToolUse Gate-1 hook under the `mcp__.*` matcher. It imports the canonical predicate `mcp_tool_is_irreversible` from the shared `_irreversible_surface` module (`.claude/hooks/mcp-irreversible-guard.py:32`) and asks it whether the exact tool name, plus a payload predicate for dual-use tools, sits on the irreversible surface (`.claude/hooks/mcp-irreversible-guard.py:93`). Non-MCP tool names and unmatched tools pass silently; there is no blanket deny (`.claude/hooks/mcp-irreversible-guard.py:83`, `.claude/hooks/mcp-irreversible-guard.py:99`).

A match prints `permissionDecision: "deny"` with a reason naming the tool and the matched marker, and pointing at the decision-brief plus the !-prefix manual bypass path (`.claude/hooks/mcp-irreversible-guard.py:37`, `.claude/hooks/mcp-irreversible-guard.py:48`), then logs a `deny` event through `_event_emit` (`.claude/hooks/mcp-irreversible-guard.py:96`). Everything else is fail-open: an unparseable payload or an unloadable surface module exits 0 without denying (`.claude/hooks/mcp-irreversible-guard.py:79`).
<!-- PROSE:END -->
