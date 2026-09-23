---
component: "agent-registry-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: agent-registry-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/retired/agent-registry-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SubagentStart Hook - Check registry for better specialist agents.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Retired: the file now lives under .claude/hooks/retired/ and is not registered; when active it ran as a SubagentStart hook (.claude/hooks/retired/agent-registry-check.py:2). It inspected only generic dispatches: a named specialist type was logged as a skip and passed through untouched (.claude/hooks/retired/agent-registry-check.py:21, .claude/hooks/retired/agent-registry-check.py:92).

For a generic dispatch it extracted the prompt's words and matched them against registry.json agent keywords, requiring at least 3 overlapping keywords and keeping the top 3 candidates (.claude/hooks/retired/agent-registry-check.py:24, .claude/hooks/retired/agent-registry-check.py:42).

On a match it printed a hookSpecificOutput additionalContext block suggesting the specialist agents (advisory only, never a block) and logged a nudge verdict; with no match it logged allow. Every verdict also went to hook-activity.jsonl via _governance_logger's log_fire (.claude/hooks/retired/agent-registry-check.py:131, .claude/hooks/retired/agent-registry-check.py:78).
<!-- PROSE:END -->
