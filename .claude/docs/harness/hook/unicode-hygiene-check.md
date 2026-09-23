---
component: "unicode-hygiene-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: unicode-hygiene-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/unicode-hygiene-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

unicode-hygiene-check.py - PostToolUse Write|Edit hook  [LIVE, warn-only]

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PostToolUse hook on the `Write|Edit` matcher that re-checks the tool name (.claude/hooks/unicode-hygiene-check.py:87) and only scans arrivals to the raw layer: paths under `Inbox/` or `Clippings/`, excluding `_test_fixtures` (.claude/hooks/unicode-hygiene-check.py:46).

It takes `tool_input.content` for a Write or `new_string` for an Edit (.claude/hooks/unicode-hygiene-check.py:95) and runs it through `_unicode_hygiene.scan_text`, which holds the one class table for invisible and bidirectional characters (.claude/hooks/unicode-hygiene-check.py:41). On findings it emits one stdout `additionalContext` warning naming the classes and counts plus the same line on stderr (.claude/hooks/unicode-hygiene-check.py:106) and appends one record to `.claude/hooks/aggregates/unicode-hygiene.jsonl` (.claude/hooks/unicode-hygiene-check.py:126).

It is warn-only and fail-open: every branch exits 0 and the outer wrapper swallows any internal error (.claude/hooks/unicode-hygiene-check.py:138). Allow and warn verdicts also land in hook-activity.jsonl through `_governance_logger.log_fire` (.claude/hooks/unicode-hygiene-check.py:67).
<!-- PROSE:END -->
