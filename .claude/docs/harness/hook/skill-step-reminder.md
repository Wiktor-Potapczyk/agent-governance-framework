---
component: "skill-step-reminder"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: skill-step-reminder

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/skill-step-reminder.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Skill Step Reminder - PostToolUse Hook (matcher: Skill)
Fires after a process skill loads. Injects additionalContext reminding
about mandatory steps for that specific process skill.
Only fires for process-* skills. Non-process skills pass through silently.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires PostToolUse on the Skill tool, after the skill has loaded. It looks the skill name up in a five-entry reminder table covering process-research, process-analysis, process-build, process-planning, and process-qa (.claude/hooks/skill-step-reminder.py:13-57, .claude/hooks/skill-step-reminder.py:90-95); any other skill passes through with no output.

On a match it logs a "remind" record carrying the skill name to hook-activity.jsonl (.claude/hooks/skill-step-reminder.py:60-69, .claude/hooks/skill-step-reminder.py:99) and prints PostToolUse hookSpecificOutput.additionalContext with that skill's mandatory-step reminder (.claude/hooks/skill-step-reminder.py:101-107). There is no deny path in the file; it never blocks.
<!-- PROSE:END -->
