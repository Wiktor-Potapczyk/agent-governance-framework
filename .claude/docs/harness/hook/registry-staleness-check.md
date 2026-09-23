---
component: "registry-staleness-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: registry-staleness-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/registry-staleness-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SessionStart registry staleness check (GEN-CADENCE, 2026-06-01).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on SessionStart (registered in `.claude/settings.local.json` for both the `startup` and `resume` matchers). It computes the age of `.claude/registry.json` from the file's `generated_at` field, falling back to file mtime when the field is absent or unparseable (`.claude/hooks/registry-staleness-check.py:28`), and compares it to a 7-day threshold (`.claude/hooks/registry-staleness-check.py:25`).

A fresh registry produces zero noise: the hook logs a "fresh" fire and emits nothing (`.claude/hooks/registry-staleness-check.py:118`). A stale registry logs "stale" and prints `hookSpecificOutput.additionalContext` advising to rerun `generate_registry.py`; a missing registry gets a one-line first-run note, never an alarm (`.claude/hooks/registry-staleness-check.py:62`, emit at `.claude/hooks/registry-staleness-check.py:124`). All failure paths swallow errors and exit 0; it never blocks (`.claude/hooks/registry-staleness-check.py:11`).
<!-- PROSE:END -->
