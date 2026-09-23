---
component: "token-breakdown"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: token-breakdown

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/token-breakdown.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Token Breakdown - Stop Hook
Aggregates token usage for the current turn: main session + per-subagent breakdown.
Emits a single 'token_breakdown' event to governance-log.jsonl via _event_emit.py.
Does NOT block — telemetry only.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A Stop hook, telemetry only (.claude/hooks/token-breakdown.py:5). It skips stop-hook retries via `stop_hook_active` (.claude/hooks/token-breakdown.py:421) and reads the last 200 KB of the transcript (.claude/hooks/token-breakdown.py:38, .claude/hooks/token-breakdown.py:437).

`aggregate_turn` finds the turn boundary by reverse-scanning for the last non-tool_result user entry (.claude/hooks/token-breakdown.py:193), then makes two passes: assistant entries accumulate main-session usage and tool-call counts, and user entries carrying a `toolUseResult` attribute subagent tokens through the `tool_use_id` to Agent-dispatch map, dropping any result that does not map to a dispatch in this turn so cross-turn tokens never pollute attribution (.claude/hooks/token-breakdown.py:323). USD cost uses hardcoded list prices (.claude/hooks/token-breakdown.py:53) with subagents priced at the Sonnet rate as an estimate (.claude/hooks/token-breakdown.py:382).

It emits exactly one `token_breakdown` event to governance-log.jsonl through `_event_emit.emit_event` (.claude/hooks/token-breakdown.py:484), skipping the emission when every counter is zero and no subagent ran (.claude/hooks/token-breakdown.py:462). It prints nothing to the conversation and never blocks.
<!-- PROSE:END -->
