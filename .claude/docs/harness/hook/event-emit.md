---
component: "_event_emit"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _event_emit

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_event_emit.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-005` (.claude/hooks/post-compact.py)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound imports post-compact
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Shared event-emit helper for observability v2 (2026-04-19).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Shared write path for governance-log.jsonl; it runs only when an importing hook calls emit_event. Each call appends one JSON line carrying the mandatory schema-2 fields ts, schema, event, hook, session, and environment, then merges the caller's extra keys without letting them overwrite the mandatory ones (.claude/hooks/_event_emit.py:144). Any failure is swallowed: telemetry must never break the parent hook (.claude/hooks/_event_emit.py:159).

The destination is resolved per call, not at import: a GOVERNANCE_LOG_PATH env override wins; failing that, when the call stack shows an un-redirected unittest.TestCase run, the write is diverted to a per-process temp file so tests cannot append to the live log (.claude/hooks/_event_emit.py:105, .claude/hooks/_event_emit.py:44).

is_test_session flags synthetic session ids (fixture-, pentest-, h5-, and similar prefixes) for downstream aggregators; the write itself is never suppressed, because filtering is a read concern (.claude/hooks/_event_emit.py:113).
<!-- PROSE:END -->
