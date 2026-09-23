---
component: "subagent-governance"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: subagent-governance

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/subagent-governance.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SubagentStart Hook - Inject governance context into subagent.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on SubagentStart with an empty matcher, so every subagent dispatch triggers it. It parses the payload, then appends one line with timestamp, agent_type, and agent_id to its own .claude/hooks/subagent-governance.log to prove the fire (.claude/hooks/subagent-governance.py:22-32); it writes nothing to hook-activity.jsonl, which is why the Usage line above reads zero.

Its output is one SubagentStart hookSpecificOutput.additionalContext block that injects the governance instructions into the subagent's context: use multiple perspectives, cite specific evidence, flag unexpected discoveries, state uncertainty, and follow the blind analysis rule (.claude/hooks/subagent-governance.py:34-48). There is no blocking path; any stdin or parse failure returns silently (.claude/hooks/subagent-governance.py:8-20).
<!-- PROSE:END -->
