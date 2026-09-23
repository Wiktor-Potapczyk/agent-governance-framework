---
component: "hook-activity.jsonl"
kind: "telemetry-sink"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# telemetry-sink: hook-activity.jsonl

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** (none recorded; unresolved registry entry, blocked: `BLK-006`)
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-006`
- **Usage:** Recorded use count 0 (source: `self:total_lines (sink line count, this run's own stream)`). Writer fire count sum: 0 (source: `hook-activity.jsonl:hook_fire.hook summed over this sink's EVD-010 writer stems (telemetry-vocabulary.json)`).
- **Edges:** (no edges recorded)
- **Twin state:** (none)
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Shared hook self-logging helper (E1, silent-zero instrumentation fix, 2026-05-30).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The sink holds one hook_fire record per line: a JSON object with ts, event, hook, decision, detail, and session (.claude/hooks/hook-activity.jsonl:1). Hooks append a line each time they fire through the shared self-logging helper, which makes the file the raw fire stream that usage roll-ups sum per hook stem.

The decision field carries each fire's outcome, and its values span the whole enforcement range: advisory fires log suggested (.claude/hooks/hook-activity.jsonl:4), warnings log warn (.claude/hooks/hook-activity.jsonl:37495), and hard gates log deny (.claude/hooks/hook-activity.jsonl:59554); passive observations leave decision null and put context in detail (.claude/hooks/hook-activity.jsonl:5).
<!-- PROSE:END -->
