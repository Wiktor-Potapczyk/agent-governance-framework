---
component: "state-reconcile-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: state-reconcile-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/state-reconcile-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

WHY THIS EXISTS
---------------
The recurring defect: a new, accurate status block is written at the top of STATE.md or
task_plan.md, and the older entries below it are left describing the previous state. The
file then says two things, and which one a reader believes depends on where they stop
reading. A PM checkpoint reading only the top reports the work done; one reading further
down reports it pending. Both are reading the same file on the same day
(.claude/hooks/state-reconcile-check.py:4-15).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires PostToolUse on Write and Edit, scoped by filename regex to STATE.md and task_plan.md (.claude/hooks/state-reconcile-check.py:56, .claude/hooks/state-reconcile-check.py:380-381); setting STATE_RECONCILE_CHECK_DISABLED=1 switches it off (.claude/hooks/state-reconcile-check.py:54). It re-reads the just-saved file from disk and runs find_contradictions over its lines (.claude/hooks/state-reconcile-check.py:383-389).

Three rules produce findings (.claude/hooks/state-reconcile-check.py:224-361): Rule A, a task number recorded closed on one line and still described as open on another, handling both checkbox and prose forms with clause-scoped markers and a heading-scoped history exemption (.claude/hooks/state-reconcile-check.py:241-322); Rule B, two different commit SHAs each asserted as the current state (.claude/hooks/state-reconcile-check.py:324-342); Rule C, a staleness marker in a section header while the file records the same work shipped elsewhere (.claude/hooks/state-reconcile-check.py:344-359).

It never blocks. Findings come back as one [STATE-RECONCILE - ADVISORY] additionalContext message listing up to eight line-numbered findings (.claude/hooks/state-reconcile-check.py:394-410), and every evaluated file logs "advisory" or "silent" to hook-activity.jsonl (.claude/hooks/state-reconcile-check.py:390). The entry point is fail-open: any exception exits 0 so a state save is never broken (.claude/hooks/state-reconcile-check.py:414-418).
<!-- PROSE:END -->
