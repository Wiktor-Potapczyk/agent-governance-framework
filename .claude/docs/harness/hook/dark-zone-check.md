---
component: "dark-zone-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: dark-zone-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/dark-zone-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Dark Zone Check - Stop Hook
Detects when agent output may have been ignored by the main session.
Logs warnings when agents were dispatched but their findings aren't referenced
in the final response. Does NOT block; monitoring only.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This Stop hook reads the last 200KB of the transcript (.claude/hooks/dark-zone-check.py:26) and walks assistant entries, collecting Agent tool_use dispatches, response text blocks, and Write/Edit counts; seeing a new classification header resets the tally, so the measure covers the current turn (.claude/hooks/dark-zone-check.py:104).

If no agents were dispatched it exits silently (.claude/hooks/dark-zone-check.py:125). Otherwise it counts citation-shaped phrases in the response text against CITATION_PATTERNS such as "Per [agent]:" and "review identified" (.claude/hooks/dark-zone-check.py:35), treats file writes as utilization too, and derives a severity: high at zero citations and zero writes, medium below a 0.5 effective ratio, low otherwise (.claude/hooks/dark-zone-check.py:141).

It emits one dark-zone event to governance-log.jsonl carrying the agent list, counts, ratio, severity, and effort level. It never blocks; the docstring states monitoring only (.claude/hooks/dark-zone-check.py:159).
<!-- PROSE:END -->
