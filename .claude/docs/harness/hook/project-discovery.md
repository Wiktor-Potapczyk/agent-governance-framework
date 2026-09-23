---
component: "_project_discovery"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _project_discovery

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_project_discovery.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-005` (.claude/hooks/pre-compact.py)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound imports pre-compact
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

_project_discovery.py - the single shared project-discovery helper.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Shared library for its four importing hooks (pre-compact, session-start-orientation, task-plan-auto-sync, user-prompt-state-inject); nothing fires it directly. The invariant: a directory is a project if and only if it directly contains STATE.md (.claude/hooks/_project_discovery.py:9). discover_projects tests the children and grandchildren of Projects/ only, a deliberate depth-2 ceiling expressed as two explicit loops, skipping dot-directories and a cost-control skip set (work, archive, node_modules, and similar) (.claude/hooks/_project_discovery.py:93, .claude/hooks/_project_discovery.py:55).

Project identity is the full forward-slash relative path, never the bare leaf, because leaf names are not unique (.claude/hooks/_project_discovery.py:16). detect_active_project resolves in three tiers: an override file holding an exact identity, then the most recently modified STATE.md among discovered projects, then a verbatim fallback identity (.claude/hooks/_project_discovery.py:152). Every filesystem call is guarded individually so one unreadable directory can never take down a SessionStart hook (.claude/hooks/_project_discovery.py:41).
<!-- PROSE:END -->
