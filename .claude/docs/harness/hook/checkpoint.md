---
component: "checkpoint"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: checkpoint

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/checkpoint.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose n8n-patterns [unresolved: prose mention only]
  - inbound mentioned_in_prose pm [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound mentioned_in_prose save [unresolved: prose mention only]
  - inbound registered_in settings.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound imports _governance_logger
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PostToolUse hook: periodic save checkpoint reminder.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This PostToolUse hook is registered in settings.json against Bash, Agent, WebFetch, WebSearch, and every MCP tool. Its logic is entirely time-file based: it keeps a last-checkpoint timestamp in ~/.claude/last-checkpoint (.claude/hooks/checkpoint.py:8) and computes the seconds elapsed since the previous fire (.claude/hooks/checkpoint.py:36).

Under 60 seconds it prints an empty object and exits, which throttles it to at most one reminder per minute (.claude/hooks/checkpoint.py:39). Past the throttle it rewrites the timestamp and emits hookSpecificOutput.additionalContext: the save-routing reminder that maps finding types to STATE.md, task_plan.md, or memory (.claude/hooks/checkpoint.py:47), escalated to an explicit "write STATE.md NOW" checkpoint line once 300 seconds have passed (.claude/hooks/checkpoint.py:56). Each emitted reminder is logged as "checkpoint" or "save-check" with the idle time, only past the throttle so a PostToolUse hook does not write one record per tool call (.claude/hooks/checkpoint.py:63).
<!-- PROSE:END -->
