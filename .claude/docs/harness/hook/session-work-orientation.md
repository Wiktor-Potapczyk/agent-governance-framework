---
component: "session-work-orientation"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: session-work-orientation

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/session-work-orientation.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

session-work-orientation.py: SessionStart work/-directory cleanliness nudge.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Runs at SessionStart on the startup and resume matchers. Project resolution tries the payload `cwd` first: a path inside Projects/<name> wins directly (.claude/hooks/session-work-orientation.py:90-121, .claude/hooks/session-work-orientation.py:163-175); otherwise one os.scandir pass over Projects/ picks the candidate with a work/ subdirectory whose STATE.md mtime is newest (.claude/hooks/session-work-orientation.py:124-160). When nothing resolves it logs "skip" and exits silently (.claude/hooks/session-work-orientation.py:284-292).

A single non-recursive scandir over work/ counts N top-level .md files and M of them untouched for over 30 days (.claude/hooks/session-work-orientation.py:66, .claude/hooks/session-work-orientation.py:178-212). K counts basenames appearing within 300 characters after a task_plan.md header containing an unnegated CLOSED; a missing or unreadable plan reports "n/a" rather than 0 (.claude/hooks/session-work-orientation.py:215-257).

It prints one [WORK-DIR ORIENTATION] line as SessionStart additionalContext and logs an "emit" record with the counts (.claude/hooks/session-work-orientation.py:298-308). Every exception path exits 0 with no stdout at all (.claude/hooks/session-work-orientation.py:310-313).
<!-- PROSE:END -->
