---
component: "pretooluse-payload-probe"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: pretooluse-payload-probe

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/pretooluse-payload-probe.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

pretooluse-payload-probe.py: TEMPORARY PreToolUse probe (matcher: Write|Edit|MultiEdit).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A temporary PreToolUse probe written for a `Write|Edit|MultiEdit` matcher (`.claude/hooks/pretooluse-payload-probe.py:2`). No settings file registers it today, which matches the docstring's plan: deregistered after the probe window, retained as evidence alongside its log (`.claude/hooks/pretooluse-payload-probe.py:18`). The Usage line above records zero fires.

When it runs, it appends one metadata-only JSONL record per matched call to `_state/pretooluse-payload-probe.jsonl`: the sorted payload key names, the `agent_type` value or the explicit marker `<ABSENT>`, the tool name, and a boolean for `transcript_path` presence, never any content (`.claude/hooks/pretooluse-payload-probe.py:40`). It emits nothing else; any exception exits 0 silently (`.claude/hooks/pretooluse-payload-probe.py:51`).
<!-- PROSE:END -->
