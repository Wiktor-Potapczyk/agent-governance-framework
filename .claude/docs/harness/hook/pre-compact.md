---
component: "pre-compact"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: pre-compact

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/pre-compact.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound registered_in settings.json
  - outbound imports _governance_logger
  - outbound imports _project_discovery
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PreCompact hook — comprehensive state save before compaction.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PreCompact (registered in `.claude/settings.json` with an empty matcher), just before compaction. It reads `transcript_path` from stdin (`.claude/hooks/pre-compact.py:17`), discovers projects with one bounded depth-2 scan via `_project_discovery` (`.claude/hooks/pre-compact.py:31`), then collects every project's STATE.md (`.claude/hooks/pre-compact.py:52`) and the In Progress and Shaped sections of each task_plan.md (`.claude/hooks/pre-compact.py:62`). If discovery fails, the snapshot is stamped DEGRADED and a "degraded" fire is logged instead of silently losing state (`.claude/hooks/pre-compact.py:37`).

It also parses up to 50KB of the transcript tail to recover the last three user messages, the last task-classification line, and up to ten recently written file paths (`.claude/hooks/pre-compact.py:86`). Everything lands in one recovery file at `~/.claude/pre-compact-recovery.md`, which SessionStart(compact) injects via restore-compact.sh (`.claude/hooks/pre-compact.py:4`, write at `.claude/hooks/pre-compact.py:172`).

After the write it logs a "snapshot" fire with the byte count (`.claude/hooks/pre-compact.py:179`) and resets the `~/.claude/last-checkpoint` timer (`.claude/hooks/pre-compact.py:188`). It prints nothing to stdout: PreCompact rejects `additionalContext`, per the removed stdout block documented at `.claude/hooks/pre-compact.py:196`.
<!-- PROSE:END -->
