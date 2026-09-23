---
component: "task-plan-auto-sync"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: task-plan-auto-sync

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/task-plan-auto-sync.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

H-4: task_plan.md auto-sync hook (2026-05-10).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A Stop hook (10 s timeout in settings.local.json). It reads the transcript tail for the last assistant message (.claude/hooks/task-plan-auto-sync.py:108) and exits unless that message holds a QA REPORT with a PASS verdict, matched either as a `| OVERALL | ... PASS` table row or a `PASS: N/N` line (.claude/hooks/task-plan-auto-sync.py:259, .claude/hooks/task-plan-auto-sync.py:89).

Task-ID extraction is SCOPE-field-first: IDs found in the QA block's SCOPE field are authoritative, with a whole-text fallback (.claude/hooks/task-plan-auto-sync.py:626), and a multi-candidate guard keeps only the first surviving ID (.claude/hooks/task-plan-auto-sync.py:637). The active project comes from the shared `_project_discovery` helper (.claude/hooks/task-plan-auto-sync.py:152), its task_plan.md files are ordered active-first (.claude/hooks/task-plan-auto-sync.py:170), and the first open `- [ ] **ID**` line wins (.claude/hooks/task-plan-auto-sync.py:191). An opt-in Haiku fallback behind `H4_ENABLE_HAIKU=1` handles regex misses (.claude/hooks/task-plan-auto-sync.py:73).

The write path runs dedup-check, undo-entry write, atomic single-line replacement, and post-write verification with revert on mismatch, then logs `SYNCED (regex|haiku)` to `.claude/hooks/logs/h4-sync.log` (.claude/hooks/task-plan-auto-sync.py:553, .claude/hooks/task-plan-auto-sync.py:594). The hook is always non-blocking: any top-level exception still exits 0 (.claude/hooks/task-plan-auto-sync.py:914).
<!-- PROSE:END -->
