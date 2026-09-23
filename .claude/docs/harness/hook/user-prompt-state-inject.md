---
component: "user-prompt-state-inject"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: user-prompt-state-inject

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/user-prompt-state-inject.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

UserPromptSubmit state-injection hook (H-3, 2026-05-10).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A UserPromptSubmit hook (5 s timeout). It first filters itself out: subagent invocations, low-effort turns, and trivial ack prompts all emit empty context (.claude/hooks/user-prompt-state-inject.py:211, .claude/hooks/user-prompt-state-inject.py:47).

The active project is the most-recently-modified STATE.md found by the shared `_project_discovery` helper (.claude/hooks/user-prompt-state-inject.py:64). It then consults a throttle file at `.claude/hooks/_state/last-state-inject.json` and fires only when the project changed, the STATE.md mtime changed, or 30 minutes have elapsed (.claude/hooks/user-prompt-state-inject.py:115, .claude/hooks/user-prompt-state-inject.py:43).

When it fires, it builds an orientation block: project name, `status:` and `last_action:` from STATE.md, and up to five open `- [ ]` tasks from task_plan.md (.claude/hooks/user-prompt-state-inject.py:131), stamps the throttle state (.claude/hooks/user-prompt-state-inject.py:244), and prints the block as UserPromptSubmit `additionalContext` (.claude/hooks/user-prompt-state-inject.py:250). Any failure falls back to emitting empty context so the prompt submission is never broken (.claude/hooks/user-prompt-state-inject.py:258).
<!-- PROSE:END -->
