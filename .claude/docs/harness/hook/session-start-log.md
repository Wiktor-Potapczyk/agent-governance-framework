---
component: "session-start-log"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: session-start-log

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/session-start-log.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Session Start Logger - SessionStart Hook Helper
P1-B (2026-04-09): Writes a session_start event to governance-log.jsonl so
analytics scripts can detect session boundaries cleanly (instead of inferring
from first classification entry).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Runs at SessionStart on the startup and resume matchers. It recovers the session id from the payload or from the transcript filename (.claude/hooks/session-start-log.py:36-41), reads the start source (startup, resume, clear, compact) and the OBSERVABILITY_ENV test flag (.claude/hooks/session-start-log.py:43-47), then appends one session_start event through the shared _event_emit.emit_event writer (.claude/hooks/session-start-log.py:49-56). That sink is governance-log.jsonl, not hook-activity.jsonl, which is why the Usage line above reads zero.

Its second job is the dashboard: it refreshes yesterday's aggregate via _daily_aggregate.write_aggregate and, when any threshold tripped, emits a dashboard_alert event and prints a one-line summary to stderr so stdout stays JSON-clean per the hook contract (.claude/hooks/session-start-log.py:58-93). It never blocks; every error is swallowed so session start cannot break (.claude/hooks/session-start-log.py:9, .claude/hooks/session-start-log.py:94-95).
<!-- PROSE:END -->
