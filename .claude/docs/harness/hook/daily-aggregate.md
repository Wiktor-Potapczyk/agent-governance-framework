---
component: "_daily_aggregate"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _daily_aggregate

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_daily_aggregate.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Daily aggregate builder for observability v2 (2026-04-19).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Library plus CLI, not an event-fired hook: session-start-log imports it, and it can be run directly as python _daily_aggregate.py [YYYY-MM-DD] (.claude/hooks/_daily_aggregate.py:160). aggregate_for_date streams governance-log.jsonl and keeps only rows whose ts starts with the target date, whose session id does not match the test-session regex, and whose environment is prod (.claude/hooks/_daily_aggregate.py:73).

It counts sessions, classifications (explicit classification_emitted events plus legacy rows), classifier blocks, QA fails, agent dispatches, and warn downgrades (.claude/hooks/_daily_aggregate.py:85), then derives quick_ratio and up to four human-readable alert strings, for example "N classifier block(s) today" (.claude/hooks/_daily_aggregate.py:117).

write_aggregate persists the summary JSON to aggregates/daily/<date>.json, creating the directory as needed, and still returns the data if the write fails (.claude/hooks/_daily_aggregate.py:150). It blocks nothing and prints nothing in hook context.
<!-- PROSE:END -->
