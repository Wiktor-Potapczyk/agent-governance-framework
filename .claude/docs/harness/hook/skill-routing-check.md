---
component: "skill-routing-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: skill-routing-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/skill-routing-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Skill Routing Check - PreToolUse Hook (matcher: Skill)
Validates that the process skill being invoked matches the TASK TYPE from classification.
Allows non-process skills (task-classifier, save, ensemble, etc.) unconditionally.
Blocks misrouted process skills.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires PreToolUse on the Skill tool. It reads the invoked skill name from tool_input (.claude/hooks/skill-routing-check.py:58), logs every fire with that name to hook-activity.jsonl (.claude/hooks/skill-routing-check.py:64-74), and allows any non-process skill unconditionally; only the skills in the routing table are validated (.claude/hooks/skill-routing-check.py:19-29, .claude/hooks/skill-routing-check.py:81-82).

For a process skill it reads the last 200KB of the transcript (.claude/hooks/skill-routing-check.py:89-95) and walks assistant entries for the most recent TASK TYPE assertion, with fenced code stripped first (.claude/hooks/skill-routing-check.py:120, .claude/hooks/skill-routing-check.py:150-158). Two events reset a stale classification: a Workflow dispatch named after a process skill, and the Compound to process-analysis decomposition hand-off (.claude/hooks/skill-routing-check.py:159-196).

No classification found, or Quick, allows (.claude/hooks/skill-routing-check.py:199-200). A mismatch against the routing table denies via hookSpecificOutput permissionDecision "deny" and emits a deny event with the attempted and expected skill to governance-log.jsonl (.claude/hooks/skill-routing-check.py:207-233).
<!-- PROSE:END -->
