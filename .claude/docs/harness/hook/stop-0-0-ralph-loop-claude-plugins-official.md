---
component: "Stop[0.0]@ralph-loop@claude-plugins-official"
kind: "hook"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# hook: Stop[0.0]@ralph-loop@claude-plugins-official

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0/hooks/stop-hook.sh`
- **Provenance:** plugin:claude-plugins-official/ralph-loop
- **Reachability:** `EVD-007` (C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0/hooks/hooks.json)
- **Usage:** No telemetry path exists for this row: plugin hook fires are not recorded in any harness sink (sentinel `NO_SOURCE_FOR_PLUGIN_HOOK`).
- **Edges:**
  - inbound registered_by_plugin plugin:claude-plugins-official/ralph-loop
- **Twin state:** not-applicable
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Implements the Ralph Wiggum technique: run Claude in a continuous loop on the same prompt file until the task completes, per its plugin.json and README. In this harness CLAUDE.md constrains it: the loop body orchestrates and consolidates only, delegating investigation to fresh sub-agents, with the architect-loop skill as the preferred wrapper.

Upstream: `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0`

(plugin-level WHY; per-component WHY declined by ruling)

## How

UNFILLED-HOW (see tier policy in README.md; plugin-internal mechanism, upstream source at `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0/hooks/stop-hook.sh`)
<!-- PROSE:END -->
