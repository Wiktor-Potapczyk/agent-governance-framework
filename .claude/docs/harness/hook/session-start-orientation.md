---
component: "session-start-orientation"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: session-start-orientation

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/session-start-orientation.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SessionStart orientation reader (H-1, 2026-05-10).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Runs at SessionStart on the startup and resume matchers. It resolves the active project through the shared _project_discovery helper in three tiers: the .claude/active-project.txt override, then the most recently modified STATE.md, then the Agent-Governance-Research fallback (.claude/hooks/session-start-orientation.py:27-30, .claude/hooks/session-start-orientation.py:37-55).

It reads STATE.md and task_plan.md capped at 512KB each (.claude/hooks/session-start-orientation.py:228-246), extracts status and last_action from the frontmatter (.claude/hooks/session-start-orientation.py:58-83), up to ten open checkbox items (.claude/hooks/session-start-orientation.py:86-102), the last three Recent Decisions entries (.claude/hooks/session-start-orientation.py:105-125), and a best-effort cost line for the last 24 hours from cost-summary.py (.claude/hooks/session-start-orientation.py:128-149).

The composed orientation is printed as SessionStart hookSpecificOutput.additionalContext, and an "orient" record with project name and character count goes to hook-activity.jsonl (.claude/hooks/session-start-orientation.py:252-261). On any failure it logs "error" and emits an empty additionalContext rather than breaking session start (.claude/hooks/session-start-orientation.py:262-273).
<!-- PROSE:END -->
