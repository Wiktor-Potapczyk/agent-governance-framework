---
component: "deferral-resurface"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: deferral-resurface

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/deferral-resurface.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Deferral Resurface (Guard B) - standalone sweep + close-advisor hook mode.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

One file, two modes, selected by whether --project is on argv (.claude/hooks/deferral-resurface.py:220). As the registered PostToolUse Write|Edit hook it runs the close advisor: it acts only when a write to a Projects/*/STATE.md, PROJECT.md, or task_plan.md sets status: done or status: archived (.claude/hooks/deferral-resurface.py:65). On match it writes a one-line stderr advisory telling the closer to run the sweep before certifying done, logs a "warn" fire record, and keeps the write; it never blocks and always exits 0 (.claude/hooks/deferral-resurface.py:207).

Run standalone with --project, it sweeps the project's task_plan.md, work/, and archive/ for deferral-class markers: Tier 3 / MEDIUM / DEFER / HOLD words, REPORT-ONLY and owner-decision-pending lines, and unchecked items under a Future Work or Deferred heading (.claude/hooks/deferral-resurface.py:58). It writes exactly one dated proposal file under work/, quoting every hit with file, line number, and a fenced verbatim quote plus an empty owner-disposition line; the sweep edits no existing file, and prior proposal files are excluded so reruns do not quote themselves (.claude/hooks/deferral-resurface.py:111).
<!-- PROSE:END -->
