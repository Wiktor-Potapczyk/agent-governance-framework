---
component: "read-before-edit-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: read-before-edit-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/read-before-edit-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Read-Before-Edit Check - Stop Hook (instrumentation layer)

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on Stop (registered in `.claude/settings.local.json` with an empty matcher). It is instrumentation, not a gate: the built-in Edit and Write tool specs already require a prior Read, so this hook only documents patterns that escape the tool layer (`.claude/hooks/read-before-edit-check.py:8`).

It reads the last 200KB of the transcript (`.claude/hooks/read-before-edit-check.py:34`), walks back to the last user message (`.claude/hooks/read-before-edit-check.py:69`), then collects every Read path in the turn and every Edit or MultiEdit whose `file_path` never appeared in a Read (`.claude/hooks/read-before-edit-check.py:86`).

For each miss it emits an `edit_without_read` event to `governance-log.jsonl` and prints a stderr WARN; it never blocks and always exits 0 (`.claude/hooks/read-before-edit-check.py:123`).
<!-- PROSE:END -->
